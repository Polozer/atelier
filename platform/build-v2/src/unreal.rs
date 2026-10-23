//! C3: the controller side of the Unreal job worker.
//!
//! One `UnrealEditor-Cmd` per admitted session serves that session's units one at a time over the
//! framed protocol (`atelier/build_v2/unreal_worker.py` inside the editor). Unreal is not
//! sandboxed: it runs under normal admission and the guard, and per-job isolation is detection
//! (scratch content, saved-package membership, resident-package and settings checks), with the
//! clean-room T2 comparison as the safety net.
//!
//! This module holds what the controller owns before and around launch:
//! - [`UnrealContext`], the session's native context and its scheduling `profile`;
//! - [`ScratchProject`], a per-session project outside the checkout whose binaries are read-only
//!   APFS clones recorded in a hash receipt, so no mutable `Binaries`, `Content`, `Intermediate` or
//!   `Saved` folder is ever shared;
//! - [`job_loop_command`], the worker's command line;
//! - the two evidence files the worker writes beside protocol version 1, which carries neither:
//!   the session's [`ContextReport`] (written before `hello`) and each job's [`ImportEvidence`].
use crate::launch::WorkerCommand;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File};
use std::io::{self, Read};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};

/// Version the Unreal job loop announces in `hello`.
pub const UNREAL_JOB_LOOP_VERSION: &str = "atelier-unreal-job-1";
/// The editor-only worker plugin every session loads. It is never enabled in a game project.
pub const WORKER_PLUGIN: &str = "AtelierBuildWorker";
/// The scratch project's descriptor. Unreal takes Content, Config and Saved from its folder.
pub const PROJECT_FILE: &str = "Atelier.uproject";
/// What the worker must find loaded before it says `hello`, relative to the scratch project.
pub const EXPECTED_CONTEXT: &str = "Atelier/expected-context.json";
/// The hash receipt of every cloned binary, in the session folder.
pub const RECEIPT_FILE: &str = "scratch-receipt.json";
/// The worker's report of what it actually loaded, written atomically to the session folder
/// before `hello`. The controller verifies it before the first `Run`.
pub const CONTEXT_REPORT: &str = "unreal-context.json";
/// Each job's import tables, beside (never inside) `output/`, so output membership is unchanged.
pub const IMPORT_EVIDENCE: &str = "evidence/imports.json";
pub const EVIDENCE_VERSION: u32 = 1;
const EDITOR_CMD: &str = "Engine/Binaries/Mac/UnrealEditor-Cmd";
/// Flags after the descriptor and the script: no prompts, no source control, no splash, logs on
/// stdout, and no RHI (imports only; jobs that need a real RHI are unsupported here).
pub const UNREAL_WORKER_FLAGS: [&str; 7] = [
    "-unattended",
    "-nop4",
    "-nosplash",
    "-stdout",
    "-AllowStdOutLogVerbosity",
    "-NullRHI",
    // An ensure inside a job starts no crash reporter and writes no report under the user's
    // Library; the worker counts it and fails the job instead.
    "-nocrashreports",
];
/// The only declared settings a context passes through: ini overrides and forced CVars. They are
/// semantic, so the units' A3 keys must bind them too; the profile only groups sessions.
const SETTING_PREFIXES: [&str; 2] = ["-ini:", "-ForceDPCVars="];

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Module {
    pub name: String,
    /// The descriptor's module type, e.g. `Runtime`, `Editor` or `UncookedOnly`.
    pub kind: String,
    pub loading_phase: String,
}

/// A produced binary folder and the content identity of its bytes ([`tree_identity`]), so a
/// rebuild that produces the same bytes is the same context.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Binaries {
    pub identity: String,
    /// The folder to clone, e.g. a restored editor compile's `Binaries/Mac`.
    pub dir: PathBuf,
}

/// A platform plugin: its `<name>.uplugin` and `Binaries/` are cloned, never its sources. The
/// identity covers exactly those files.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Plugin {
    pub name: String,
    pub identity: String,
    pub dir: PathBuf,
}

/// Everything a session's editor loads natively. Locations are not identity: contexts that differ
/// only in where their binaries were restored share a `profile`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct UnrealContext {
    /// The installed engine: platform context, never in item keys.
    pub engine_root: PathBuf,
    /// The installed engine's BuildId. It separates sessions but stays out of item keys.
    pub build_id: String,
    /// The project module binaries.
    pub editor: Binaries,
    pub modules: Vec<Module>,
    /// Engine plugins enabled by name (installed platform).
    pub engine_plugins: Vec<String>,
    /// Platform plugins cloned into the scratch project, including [`WORKER_PLUGIN`].
    pub plugins: Vec<Plugin>,
    /// Declared `-ini:` and `-ForceDPCVars=` arguments, passed verbatim and in order.
    pub settings: Vec<String>,
}

fn invalid(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, message.into())
}

fn damaged(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message.into())
}

fn name_ok(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-')
}

fn digest_ok(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

/// Command-line text: UTF-8 with no whitespace or quotes, so Unreal's own argument parsing can
/// never split or rejoin it.
fn argument(path: &Path, label: &str) -> io::Result<String> {
    let text = path
        .to_str()
        .ok_or_else(|| invalid(format!("{label} is not UTF-8: {}", path.display())))?;
    if text
        .chars()
        .any(|c| c.is_whitespace() || c == '"' || c == '\'')
    {
        return Err(invalid(format!("{label} has whitespace or quotes: {text}")));
    }
    Ok(text.to_string())
}

impl UnrealContext {
    pub fn validate(&self) -> io::Result<()> {
        if !self.engine_root.is_absolute() {
            return Err(invalid("the engine root must be absolute"));
        }
        // The engine root only names the program, which is never part of Unreal's own command
        // line, so it may hold spaces (the installed engine lives under `Epic Games`).
        if self.engine_root.to_str().is_none() {
            return Err(invalid("the engine root is not UTF-8"));
        }
        if self.build_id.is_empty() || self.build_id.chars().any(char::is_control) {
            return Err(invalid("the engine BuildId is missing"));
        }
        if !digest_ok(&self.editor.identity) {
            return Err(invalid(
                "the editor binaries identity is not a sha256 digest",
            ));
        }
        if self.modules.is_empty() {
            return Err(invalid("a session loads at least one project module"));
        }
        let mut names = BTreeSet::new();
        for module in &self.modules {
            if !name_ok(&module.name) || !name_ok(&module.kind) || !name_ok(&module.loading_phase) {
                return Err(invalid(format!("invalid module {:?}", module.name)));
            }
            if !names.insert(module.name.clone()) {
                return Err(invalid(format!("module {} is declared twice", module.name)));
            }
        }
        let mut plugins = BTreeSet::new();
        for name in &self.engine_plugins {
            if !name_ok(name) || !plugins.insert(name.clone()) {
                return Err(invalid(format!("invalid or repeated plugin {name:?}")));
            }
        }
        for plugin in &self.plugins {
            if !name_ok(&plugin.name) || !plugins.insert(plugin.name.clone()) {
                return Err(invalid(format!(
                    "invalid or repeated plugin {:?}",
                    plugin.name
                )));
            }
            if !digest_ok(&plugin.identity) {
                return Err(invalid(format!(
                    "plugin {} identity is not a sha256 digest",
                    plugin.name
                )));
            }
        }
        if !self
            .plugins
            .iter()
            .any(|plugin| plugin.name == WORKER_PLUGIN)
        {
            return Err(invalid(format!("the {WORKER_PLUGIN} plugin is required")));
        }
        for setting in &self.settings {
            let allowed = SETTING_PREFIXES.iter().any(|p| setting.starts_with(p));
            if !allowed
                || setting
                    .chars()
                    .any(|c| c.is_whitespace() || c == '"' || c == '\'')
            {
                return Err(invalid(format!(
                    "setting {setting:?} is not a declared ini or CVar override"
                )));
            }
        }
        Ok(())
    }

    /// The identity fields, without locations.
    pub fn identity(&self) -> serde_json::Value {
        let mut engine_plugins = self.engine_plugins.clone();
        engine_plugins.sort();
        let plugins: BTreeMap<_, _> = self
            .plugins
            .iter()
            .map(|plugin| (plugin.name.clone(), plugin.identity.clone()))
            .collect();
        serde_json::json!({
            "worker_version": UNREAL_JOB_LOOP_VERSION,
            "build_id": self.build_id,
            "editor": self.editor.identity,
            "modules": self.modules,
            "engine_plugins": engine_plugins,
            "plugins": plugins,
            "rhi": "null",
            "settings": self.settings,
        })
    }

    /// Scheduling compatibility only (A9 groups by it; the session refuses a mismatch). It is not
    /// a key ingredient: semantic settings and module bytes must bind each unit's A3 key directly.
    pub fn profile(&self) -> String {
        let digest = Sha256::digest(self.identity().to_string().as_bytes());
        format!("unreal-{digest:x}")
    }

    pub fn editor_cmd(&self) -> PathBuf {
        self.engine_root.join(EDITOR_CMD)
    }
}

fn sha256_file(path: &Path) -> io::Result<String> {
    let mut file = File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buffer = vec![0u8; 1 << 16];
    loop {
        let count = file.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        hasher.update(&buffer[..count]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}

/// Regular files under `root`, relative and sorted. Links and other types are refused: a clone
/// must never follow or copy one.
fn tree(root: &Path) -> io::Result<Vec<PathBuf>> {
    let mut found = vec![];
    let mut pending = vec![PathBuf::new()];
    while let Some(relative) = pending.pop() {
        for entry in fs::read_dir(root.join(&relative))? {
            let entry = entry?;
            let path = relative.join(entry.file_name());
            let kind = entry.file_type()?;
            if kind.is_dir() {
                pending.push(path);
            } else if kind.is_file() {
                found.push(path);
            } else {
                return Err(invalid(format!(
                    "{} is not a regular file or folder",
                    root.join(&path).display()
                )));
            }
        }
    }
    found.sort();
    Ok(found)
}

/// Folders under `root` (including itself), parents first.
fn folders(root: &Path) -> io::Result<Vec<PathBuf>> {
    let mut found = vec![root.to_path_buf()];
    let mut index = 0;
    while index < found.len() {
        let mut children = vec![];
        for entry in fs::read_dir(&found[index])? {
            let entry = entry?;
            if entry.file_type()?.is_dir() {
                children.push(entry.path());
            }
        }
        children.sort();
        found.extend(children);
        index += 1;
    }
    Ok(found)
}

fn utf8(path: &Path) -> io::Result<String> {
    path.to_str()
        .map(str::to_owned)
        .ok_or_else(|| invalid(format!("{} is not UTF-8", path.display())))
}

/// The files a binary identity covers, relative to the folder: the whole tree for project
/// binaries; the descriptor and `Binaries/` for a plugin.
fn covered(dir: &Path, plugin: Option<&str>) -> io::Result<Vec<PathBuf>> {
    match plugin {
        None => tree(dir),
        Some(name) => {
            let mut files = vec![PathBuf::from(format!("{name}.uplugin"))];
            files.extend(
                tree(&dir.join("Binaries"))?
                    .into_iter()
                    .map(|p| Path::new("Binaries").join(p)),
            );
            Ok(files)
        }
    }
}

/// The content identity of a binary folder: sha256 over each covered file's relative path and
/// sha256, in path order. Locations and timestamps never enter it.
pub fn tree_identity(dir: &Path, plugin: Option<&str>) -> io::Result<String> {
    let mut manifest = String::new();
    for relative in covered(dir, plugin)? {
        let path = dir.join(&relative);
        if !fs::symlink_metadata(&path)?.is_file() {
            return Err(invalid(format!("{} is not a regular file", path.display())));
        }
        manifest.push_str(&format!("{}\0{}\n", utf8(&relative)?, sha256_file(&path)?));
    }
    Ok(format!("{:x}", Sha256::digest(manifest.as_bytes())))
}

#[cfg(target_os = "macos")]
fn clone_file(source: &Path, destination: &Path) -> io::Result<()> {
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;
    // Darwin SDK sys/clonefile.h: never follow a link at the source.
    const CLONE_NOFOLLOW: libc::c_uint = 0x0001;
    let text = |path: &Path| {
        CString::new(path.as_os_str().as_bytes()).map_err(|_| invalid("path contains NUL"))
    };
    let (source, destination) = (text(source)?, text(destination)?);
    if unsafe { libc::clonefile(source.as_ptr(), destination.as_ptr(), CLONE_NOFOLLOW) } == 0 {
        Ok(())
    } else {
        Err(io::Error::last_os_error())
    }
}

#[cfg(not(target_os = "macos"))]
fn clone_file(_: &Path, _: &Path) -> io::Result<()> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "APFS clone requires macOS",
    ))
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ClonedFile {
    pub source: PathBuf,
    pub sha256: String,
}

/// Every cloned file, by its path relative to the scratch project.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ScratchReceipt {
    pub profile: String,
    pub files: BTreeMap<String, ClonedFile>,
}

/// What the worker must find loaded, and later reports it found ([`ContextReport`]).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LoadedContext {
    pub worker_version: String,
    pub profile: String,
    pub build_id: String,
    pub modules: BTreeSet<String>,
    pub plugins: BTreeSet<String>,
    /// sha256 of every loaded project or plugin library, by its path relative to the project.
    pub libraries: BTreeMap<String, String>,
    pub rhi: String,
}

/// The session evidence file (`unreal-context.json`): what the worker actually loaded, written
/// atomically before `hello`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ContextReport {
    pub version: u32,
    pub loaded: LoadedContext,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PackageImports {
    /// The saved package's logical name, e.g. `/Game/Meshes/Rock`.
    pub package: String,
    /// Each import as `[path, class]`, in the package's import-table order.
    pub imports: Vec<(String, String)>,
}

/// The per-job evidence file (`evidence/imports.json`): every saved package's import table.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ImportEvidence {
    pub version: u32,
    pub packages: Vec<PackageImports>,
}

/// One session's Unreal project, outside the checkout:
/// - `Atelier.uproject`, with only the declared modules and plugins;
/// - `Binaries/Mac/` and `Plugins/<name>/{<name>.uplugin, Binaries/}`: read-only APFS clones;
/// - `Content/` (`/Game`, empty), `Config/`, `Saved/` and `Intermediate/`, session-owned;
/// - `Atelier/expected-context.json`, what the worker must find loaded before `hello`.
#[derive(Debug)]
pub struct ScratchProject {
    session: PathBuf,
    root: PathBuf,
    expected: LoadedContext,
    receipt: ScratchReceipt,
}

impl ScratchProject {
    /// Build the session's project in `<session>/project`, which must not exist yet. Every
    /// declared binary identity is checked against the bytes actually cloned.
    pub fn prepare(session: &Path, context: &UnrealContext) -> io::Result<Self> {
        context.validate()?;
        let session = session.canonicalize()?;
        argument(&session, "the session folder")?;
        let root = session.join("project");
        fs::create_dir(&root)?;
        let mut receipt = ScratchReceipt {
            profile: context.profile(),
            files: BTreeMap::new(),
        };
        for folder in [
            "Content",
            "Config",
            "Saved",
            "Intermediate",
            "Atelier",
            "Plugins",
        ] {
            fs::create_dir(root.join(folder))?;
        }
        fs::create_dir(session.join("user"))?;
        let sources = std::iter::once((
            &context.editor.dir,
            None,
            &context.editor.identity,
            root.join("Binaries/Mac"),
        ))
        .chain(context.plugins.iter().map(|plugin| {
            (
                &plugin.dir,
                Some(plugin.name.as_str()),
                &plugin.identity,
                root.join("Plugins").join(&plugin.name),
            )
        }));
        for (dir, plugin, identity, target) in sources {
            let mut manifest = String::new();
            for relative in covered(dir, plugin)? {
                let from = dir.join(&relative);
                if !fs::symlink_metadata(&from)?.is_file() {
                    return Err(invalid(format!("{} is not a regular file", from.display())));
                }
                let to = target.join(&relative);
                fs::create_dir_all(to.parent().expect("a cloned file has a parent"))?;
                clone_file(&from, &to)?;
                // The clone is what Unreal loads; its bytes are what the identity must name.
                let sha256 = sha256_file(&to)?;
                manifest.push_str(&format!("{}\0{sha256}\n", utf8(&relative)?));
                let key = utf8(to.strip_prefix(&root).expect("inside the project"))?;
                receipt.files.insert(
                    key,
                    ClonedFile {
                        source: from,
                        sha256,
                    },
                );
            }
            let actual = format!("{:x}", Sha256::digest(manifest.as_bytes()));
            if &actual != identity {
                return Err(damaged(format!(
                    "{} does not hold the declared binaries {identity} (found {actual})",
                    dir.display()
                )));
            }
        }
        let mut plugins: Vec<serde_json::Value> = context
            .engine_plugins
            .iter()
            .chain(context.plugins.iter().map(|plugin| &plugin.name))
            .map(|name| serde_json::json!({"Name": name, "Enabled": true}))
            .collect();
        plugins.sort_by_key(|value| value.to_string());
        let descriptor = serde_json::json!({
            "FileVersion": 3,
            "EngineAssociation": "",
            "Category": "",
            "Description": "Atelier build-v2 scratch project for one Unreal worker session.",
            "Modules": context.modules.iter().map(|module| serde_json::json!({
                "Name": module.name, "Type": module.kind, "LoadingPhase": module.loading_phase,
            })).collect::<Vec<_>>(),
            "Plugins": plugins,
        });
        let expected = LoadedContext {
            worker_version: UNREAL_JOB_LOOP_VERSION.into(),
            profile: receipt.profile.clone(),
            build_id: context.build_id.clone(),
            modules: context.modules.iter().map(|m| m.name.clone()).collect(),
            plugins: context
                .engine_plugins
                .iter()
                .chain(context.plugins.iter().map(|p| &p.name))
                .cloned()
                .collect(),
            libraries: receipt
                .files
                .iter()
                .filter(|(path, _)| path.ends_with(".dylib"))
                .map(|(path, file)| (path.clone(), file.sha256.clone()))
                .collect(),
            rhi: "null".into(),
        };
        fs::write(
            root.join(PROJECT_FILE),
            serde_json::to_vec_pretty(&descriptor)?,
        )?;
        fs::write(
            root.join(EXPECTED_CONTEXT),
            serde_json::to_vec_pretty(&expected)?,
        )?;
        fs::write(
            session.join(RECEIPT_FILE),
            serde_json::to_vec_pretty(&receipt)?,
        )?;
        let project = Self {
            session,
            root,
            expected,
            receipt,
        };
        project.set_read_only(true)?;
        Ok(project)
    }

    pub fn session(&self) -> &Path {
        &self.session
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn uproject(&self) -> PathBuf {
        self.root.join(PROJECT_FILE)
    }

    /// `/Game`: empty between jobs.
    pub fn content(&self) -> PathBuf {
        self.root.join("Content")
    }

    /// The session's own Unreal user folder (`-UserDir`).
    pub fn user_dir(&self) -> PathBuf {
        self.session.join("user")
    }

    pub fn receipt(&self) -> &ScratchReceipt {
        &self.receipt
    }

    pub fn expected(&self) -> &LoadedContext {
        &self.expected
    }

    /// Every clone and its source still hold the receipt's bytes, the clones are still read-only,
    /// and the cloned trees hold nothing the receipt doesn't list.
    pub fn verify(&self) -> io::Result<()> {
        let mut seen = BTreeSet::new();
        for top in ["Binaries", "Plugins"] {
            for relative in tree(&self.root.join(top))? {
                seen.insert(utf8(&Path::new(top).join(relative))?);
            }
        }
        let listed: BTreeSet<_> = self.receipt.files.keys().cloned().collect();
        if seen != listed {
            return Err(damaged(
                "the cloned binaries differ from the receipt's file list",
            ));
        }
        for (relative, file) in &self.receipt.files {
            let clone = self.root.join(relative);
            if fs::symlink_metadata(&clone)?.permissions().mode() & 0o222 != 0 {
                return Err(damaged(format!("{relative} is writable")));
            }
            if sha256_file(&clone)? != file.sha256 {
                return Err(damaged(format!("{relative} changed after it was cloned")));
            }
            if sha256_file(&file.source)? != file.sha256 {
                return Err(damaged(format!(
                    "{} changed after it was cloned",
                    file.source.display()
                )));
            }
        }
        Ok(())
    }

    /// The session evidence the worker wrote before `hello`. Missing, malformed or different
    /// evidence refuses the session before its first `Run`.
    pub fn verify_context_report(&self) -> io::Result<ContextReport> {
        let path = self.session.join(CONTEXT_REPORT);
        let report: ContextReport = serde_json::from_slice(&fs::read(&path)?)
            .map_err(|error| damaged(format!("{CONTEXT_REPORT}: {error}")))?;
        if report.version != EVIDENCE_VERSION {
            return Err(damaged(format!(
                "{CONTEXT_REPORT} has an unsupported version"
            )));
        }
        if report.loaded != self.expected {
            return Err(damaged(format!(
                "the worker loaded a different native context than the session declared"
            )));
        }
        Ok(report)
    }

    /// The clones' folders and files, and the two generated files, are read-only: an editor that
    /// wants to rebuild a module fails, by design.
    fn set_read_only(&self, read_only: bool) -> io::Result<()> {
        let (file_mode, folder_mode) = if read_only {
            (0o444, 0o555)
        } else {
            (0o644, 0o755)
        };
        let mut locked = vec![];
        for top in ["Binaries", "Plugins"] {
            locked.extend(folders(&self.root.join(top))?);
        }
        if !read_only {
            for folder in &locked {
                fs::set_permissions(folder, fs::Permissions::from_mode(folder_mode))?;
            }
        }
        for relative in self.receipt.files.keys() {
            fs::set_permissions(
                self.root.join(relative),
                fs::Permissions::from_mode(file_mode),
            )?;
        }
        for path in [self.uproject(), self.root.join(EXPECTED_CONTEXT)] {
            fs::set_permissions(path, fs::Permissions::from_mode(file_mode))?;
        }
        if read_only {
            // Children before parents, so every folder can still be entered while it is locked.
            for folder in locked.iter().rev() {
                fs::set_permissions(folder, fs::Permissions::from_mode(folder_mode))?;
            }
        }
        Ok(())
    }

    /// Unlock and delete the whole session project. Called only after the session's cleanup
    /// receipt; the receipt and evidence files in the session folder stay.
    pub fn remove(self) -> io::Result<()> {
        self.set_read_only(false)?;
        fs::remove_dir_all(&self.root)
    }
}

/// A job's import evidence, refused when missing or malformed, or when it names a package the job
/// did not declare as an output.
pub fn read_import_evidence(
    job_dir: &Path,
    declared: &BTreeSet<String>,
) -> io::Result<ImportEvidence> {
    let path = job_dir.join(IMPORT_EVIDENCE);
    let evidence: ImportEvidence = serde_json::from_slice(&fs::read(&path)?)
        .map_err(|error| damaged(format!("{IMPORT_EVIDENCE}: {error}")))?;
    if evidence.version != EVIDENCE_VERSION {
        return Err(damaged(format!(
            "{IMPORT_EVIDENCE} has an unsupported version"
        )));
    }
    let mut seen = BTreeSet::new();
    for package in &evidence.packages {
        if !declared.contains(&package.package) || !seen.insert(package.package.clone()) {
            return Err(damaged(format!(
                "{IMPORT_EVIDENCE} names an undeclared or repeated package {}",
                package.package
            )));
        }
    }
    if &seen != declared {
        return Err(damaged(format!(
            "{IMPORT_EVIDENCE} omits a declared package"
        )));
    }
    Ok(evidence)
}

/// The Unreal job loop: the installed `UnrealEditor-Cmd` on the session's scratch project, running
/// `unreal_worker.py` through the stock `pythonscript` commandlet. The launcher appends the two
/// protocol descriptor flags at the end, where the worker reads them from the engine command line.
pub fn job_loop_command(
    context: &UnrealContext,
    scratch: &ScratchProject,
    worker_script: &Path,
) -> io::Result<WorkerCommand> {
    context.validate()?;
    if scratch.receipt.profile != context.profile() {
        return Err(invalid(
            "the scratch project was prepared for another context",
        ));
    }
    let mut args = vec![
        argument(&scratch.uproject(), "the scratch descriptor")?,
        "-run=pythonscript".into(),
        format!("-script={}", argument(worker_script, "the worker script")?),
    ];
    args.extend(UNREAL_WORKER_FLAGS.iter().map(|flag| flag.to_string()));
    args.push(format!(
        "-UserDir={}",
        argument(&scratch.user_dir(), "the user folder")?
    ));
    args.extend(context.settings.iter().cloned());
    Ok(WorkerCommand {
        program: context.editor_cmd(),
        args,
        env: BTreeMap::from([("LC_ALL".into(), "C".into()), ("TZ".into(), "UTC".into())]),
        cwd: PathBuf::from("/"),
    })
}
