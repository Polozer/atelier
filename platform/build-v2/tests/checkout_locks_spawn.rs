//! A child that has forked but not yet exec'd still holds every inherited descriptor, so a
//! just-released checkout lock can look busy. Callers retry with a bounded deadline; this pins
//! that contract deterministically with a controlled `pre_exec` window.
#![cfg(unix)]
use atelier_build_v2::checkout_locks::{CheckoutLocks, LockError};
use std::fs;
use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant};

static NEXT: AtomicU64 = AtomicU64::new(0);

struct Workspace(PathBuf);

impl Workspace {
    fn new() -> Self {
        let path = std::env::temp_dir().canonicalize().unwrap().join(format!(
            "atelier-v2-locks-spawn-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn locks(&self) -> CheckoutLocks {
        CheckoutLocks::open(&self.0).unwrap()
    }
}

impl Drop for Workspace {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

#[test]
fn lock_busy_is_transient_during_spawn() {
    let workspace = Workspace::new();
    let locks = workspace.locks();
    let build = locks.try_build_exclusive().unwrap();

    let (mut reader, writer) = std::io::pipe().unwrap();
    let write_fd = writer.as_raw_fd();
    let mut command = Command::new("/usr/bin/true");
    // SAFETY: after fork and before exec this only writes one byte and calls nanosleep; both are
    // async-signal-safe. The parent reads the byte to know the fork happened while the inherited
    // lock descriptor is still open in the child.
    unsafe {
        command.pre_exec(move || {
            if libc::write(write_fd, b"x".as_ptr().cast(), 1) != 1 {
                return Err(std::io::Error::last_os_error());
            }
            let mut remaining = libc::timespec {
                tv_sec: 0,
                tv_nsec: 200_000_000,
            };
            loop {
                let request = remaining;
                if libc::nanosleep(&request, &mut remaining) == 0 {
                    return Ok(());
                }
                let error = std::io::Error::last_os_error();
                if error.kind() != std::io::ErrorKind::Interrupted {
                    return Err(error);
                }
            }
        });
    }

    std::thread::scope(|scope| {
        let spawner = scope.spawn(move || {
            let mut command = command;
            command.spawn()
        });

        let mut pollfd = libc::pollfd {
            fd: reader.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        };
        let ready = unsafe { libc::poll(&mut pollfd, 1, 2000) };
        assert_eq!(ready, 1, "child did not reach its pre-exec window");
        let mut byte = [0u8; 1];
        reader.read_exact(&mut byte).unwrap();
        drop(writer);
        drop(build);

        assert!(
            matches!(locks.try_build_exclusive(), Err(LockError::Busy)),
            "a fork that has not exec'd yet must keep the inherited build lock busy"
        );

        let started = Instant::now();
        let guard = loop {
            match locks.try_build_exclusive() {
                Ok(guard) => break guard,
                Err(LockError::Busy) => {
                    assert!(
                        started.elapsed() < Duration::from_secs(2),
                        "checkout build lock stayed busy beyond 2 s after the spawn exec'd"
                    );
                    std::thread::sleep(Duration::from_millis(2));
                }
                Err(error) => panic!("unexpected checkout lock error: {error}"),
            }
        };
        drop(guard);

        let mut child = spawner
            .join()
            .expect("spawner thread")
            .expect("spawn /usr/bin/true");
        assert!(child.wait().unwrap().success());
    });
}
