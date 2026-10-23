"""Build-v2 Unreal job loop: one editor per admitted session, one job at a time.

Started by the controller (`platform/build-v2/src/unreal.rs`) as

    UnrealEditor-Cmd <scratch>/Atelier.uproject -run=pythonscript -script=unreal_worker.py \\
        -unattended -nop4 -nosplash -stdout -AllowStdOutLogVerbosity -NullRHI -nocrashreports \\
        -UserDir=<session>/user \\
        [declared -ini:/-ForceDPCVars=] --request-fd N --response-fd M

It speaks protocol version 1 (`protocol.py`) on the two inherited pipes, made close-on-exec at once
so no helper process the editor starts inherits them. Stdout and stderr are the editor's logs.

**Unreal is not sandboxed.** Per-job isolation is detection only:
- each job's input packages are copied into the session's empty `/Game` at their logical paths,
  read-only, and removed afterwards;
- the packages saved during the job must be exactly the declared output packages (a package saved
  twice to one file counts once), nothing may be left dirty, no input may change, and no ensure may
  fail (with -nocrashreports an ensure starts no crash reporter and fails the job instead);
- after every job, every package it touched is unloaded, garbage is collected synchronously through
  the plugin, and each package must be gone by `find_object` (neither the unload call's result nor
  `SystemLibrary.collect_garbage`, which only schedules a collection, is trusted); no `/Game`
  package may stay loaded, `/Game` and the asset registry must be empty, the Python state is
  restored, every console variable that existed before the job must keep its value, and one
  registered during the job must still be at its default.

A job whose reset fails still gets its terminal reply; the worker then exits instead of serving
another job, so the controller ends the session (a clean exit after a terminal reply is never crash
evidence for that job). Before `hello` the worker writes the session evidence file
`unreal-context.json` (what it actually loaded) and refuses to start if that differs from
`Atelier/expected-context.json`. Each job's import tables go to `evidence/imports.json` beside, never
inside, `output/`.

The editor surface is `Editor`: the `unreal` module plus the editor-only `AtelierBuildWorker`
plugin library, whose functions this file defines by use (the T0 stand-in implements the same).
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import runpy
import shutil
import stat
import sys

if __package__:
    from . import protocol
else:  # run by the editor as a script: load the sibling module by path
    _spec = importlib.util.spec_from_file_location('build_v2_protocol', Path(__file__).with_name('protocol.py'))
    protocol = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(protocol)

WORKER_VERSION = 'atelier-unreal-job-1'
EXPECTED_CONTEXT = 'Atelier/expected-context.json'
CONTEXT_REPORT = 'unreal-context.json'
IMPORT_EVIDENCE = 'evidence/imports.json'
EVIDENCE_VERSION = 1
GAME = '/Game/'
INPUT_CONTENT = 'in/content/Game/'
OUTPUT_CONTENT = 'content/Game/'
PACKAGE_FILES = ('.uasset', '.umap', '.uexp', '.ubulk', '.uptnl')
PRIMARY_FILES = ('.uasset', '.umap')


class JobRefused(Exception):
    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


class StartRefused(Exception):
    """The editor's native context is not the declared one: no `hello`."""


def log(message):
    print(f'atelier-unreal-worker: {message}', file=sys.stderr, flush=True)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 16), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write_atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    with open(temporary, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, indent=1)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def protocol_fds(command_line):
    """`--request-fd N --response-fd M` from the engine command line (`-script` arguments aside)."""
    tokens = command_line.split()
    found = {}
    for flag in ('--request-fd', '--response-fd'):
        if tokens.count(flag) != 1 or tokens.index(flag) + 1 >= len(tokens):
            raise StartRefused(f'the command line must carry exactly one {flag}')
        value = tokens[tokens.index(flag) + 1]
        if not value.isdigit():
            raise StartRefused(f'{flag} is not a descriptor number')
        found[flag] = int(value)
    request, response = found['--request-fd'], found['--response-fd']
    for fd in (request, response):
        if not stat.S_ISFIFO(os.fstat(fd).st_mode):
            raise StartRefused(f'descriptor {fd} is not a pipe')
        os.set_inheritable(fd, False)
    return request, response


def package_of(relative, root):
    """`/Game/A/B` for `root/A/B.uasset`; None for a non-primary package file."""
    if not relative.startswith(root):
        return None
    rest = relative[len(root):]
    for suffix in PRIMARY_FILES:
        if rest.endswith(suffix):
            return GAME + rest[:-len(suffix)]
    return None


def package_owning(relative, root):
    """`/Game/A/B` for any package file `root/A/B.<package suffix>` (companions included), else None."""
    if not relative.startswith(root):
        return None
    rest = relative[len(root):]
    for suffix in PACKAGE_FILES:
        if rest.endswith(suffix):
            return GAME + rest[:-len(suffix)]
    return None


def _job_relative(path, label):
    parts = path.split('/')
    if not path or path.startswith('/') or '\\' in path or '\0' in path or any(p in ('', '.', '..') for p in parts):
        raise JobRefused('protocol', f'{label} is not a job-relative path: {path!r}')
    return path


class Editor:
    """Everything the loop asks of the editor."""

    def __init__(self, unreal):
        self.unreal = unreal
        self.library = unreal.AtelierBuildWorkerLibrary

    def command_line(self):
        return self.unreal.SystemLibrary.get_command_line()

    def project_dir(self):
        paths = self.unreal.Paths
        return Path(paths.convert_relative_path_to_full(paths.project_dir())).resolve()

    def engine_dir(self):
        paths = self.unreal.Paths
        return Path(paths.convert_relative_path_to_full(paths.engine_dir())).resolve()

    def native_context(self):
        """{build_id, modules, plugins: {name: folder}, libraries: [path], rhi} from the plugin."""
        return json.loads(self.library.native_context())

    def begin_job(self):
        self.library.begin_ensure_count()
        self.library.begin_save_recording()

    def ensures(self):
        """Failed ensures since `begin_job` (the editor runs with -nocrashreports, so none is reported elsewhere)."""
        return self.library.ensure_count()

    def saved_packages(self):
        """[{package, filename}] saved since `begin_job`."""
        return json.loads(self.library.end_save_recording())

    def finish_background_work(self):
        self.library.finish_background_work()

    def dirty_packages(self):
        return list(self.library.dirty_package_names())

    def loaded_game_packages(self):
        return sorted(self.library.loaded_package_names(GAME))

    def imports(self, package):
        return [list(item) for item in json.loads(self.library.package_imports(package))]

    def settings(self):
        """{console variable: [value, set by]}; set by "Constructor" means still at its default."""
        return json.loads(self.library.settings_snapshot())

    def scan(self, files):
        registry = self.unreal.AssetRegistryHelpers.get_asset_registry()
        registry.scan_files_synchronous([str(path) for path in files], True)

    def forget(self, files):
        """Drop deleted files from the asset registry (a commandlet watches no folders)."""
        self.library.forget_files([str(path) for path in files])

    def registry_game_assets(self):
        registry = self.unreal.AssetRegistryHelpers.get_asset_registry()
        return len(registry.get_assets_by_path('/Game', True))

    def unload(self, packages, passes=3):
        """Unload `packages` with a synchronous garbage collection, and say which are still in memory.

        One pass is not enough after an import: while the import task still holds its assets the first
        unload leaves them standalone (it frees nothing), and only a second unload after the collection
        drops them. Up to `passes` passes run until nothing is left. The unload call's own result ("any",
        not "all") is never trusted.
        """
        remaining = list(packages)
        for _ in range(passes):
            objects = [self.unreal.find_object(None, name) for name in remaining]
            objects = [value for value in objects if value is not None]
            if objects:
                self.unreal.EditorLoadingAndSavingUtils.unload_packages(objects)
            del objects
            # SystemLibrary.collect_garbage only schedules a collection for the next engine tick, which a
            # commandlet script never reaches; the plugin collects now.
            self.library.collect_garbage_now()
            remaining = [name for name in remaining if self.unreal.find_object(None, name) is not None]
            if not remaining:
                break
        return remaining


class Context:
    """What an op sees: its params, staged inputs and declared outputs; no repository paths."""

    def __init__(self, job_dir, inputs, packages, params, outputs, content_dir):
        self.job_dir = Path(job_dir)
        self.inputs = inputs  # name -> logical package (staged) or job-folder path
        self.packages = packages  # name -> logical package, for staged package inputs
        self.params = params
        self.outputs = outputs  # declared output packages
        self.content_dir = Path(content_dir)


class Worker:
    def __init__(self, editor, requests, responses):
        self.editor = editor
        self.requests = requests
        self.responses = responses
        self.project = editor.project_dir()
        self.content = self.project / 'Content'

    def send(self, message):
        protocol.write_frame(self.responses, protocol.RESPONSE, message)

    def start(self):
        """Report the loaded context as session evidence, then refuse a mismatch before `hello`."""
        expected = json.loads((self.project / EXPECTED_CONTEXT).read_text(encoding='utf-8'))
        native = self.editor.native_context()
        declared = set(expected['plugins'])
        plugins = {name for name, folder in native['plugins'].items()
                   if name in declared or Path(folder).resolve().is_relative_to(self.project)}
        libraries = {}
        for library in native['libraries']:
            path = Path(library).resolve()
            if path.is_relative_to(self.project):
                libraries[str(path.relative_to(self.project))] = sha256(path)
            elif not path.is_relative_to(self.editor.engine_dir()):
                libraries[str(path)] = sha256(path)  # neither project nor engine: always a mismatch
        loaded = {'worker_version': WORKER_VERSION, 'profile': expected['profile'], 'build_id': native['build_id'],
                  'modules': sorted(native['modules']), 'plugins': sorted(plugins), 'libraries': libraries,
                  'rhi': native['rhi']}
        write_atomic(self.project.parent / CONTEXT_REPORT, {'version': EVIDENCE_VERSION, 'loaded': loaded})
        if loaded != {**expected, 'modules': sorted(expected['modules']), 'plugins': sorted(expected['plugins'])}:
            raise StartRefused('the editor loaded a different native context than the session declared')
        if any(self.content.iterdir()) or self.editor.registry_game_assets():
            raise StartRefused('/Game is not empty at startup')

    def serve(self):
        """Serve jobs until `shutdown`, the end of the request stream, or a failed reset."""
        self.send({'type': 'hello', 'worker_version': WORKER_VERSION})
        while True:
            request = protocol.read_frame(self.requests, protocol.REQUEST)
            if request is None:
                return 'requests ended'
            if request['type'] == 'shutdown':
                self.send({'type': 'stopped'})
                return 'shutdown'
            if request['type'] == 'run':
                reset_problem = self.run(request['job'])
                if reset_problem:
                    log(f'retiring after a terminal reply: {reset_problem}')
                    return 'retired'
            # A cancel can only be read between jobs, so it always names a finished job: no reply.

    def run(self, job):
        """Run one job; returns why the editor may not serve another, or None."""
        job_id = job['job_id']
        self.send({'type': 'started', 'job_id': job_id})
        state = _PythonState()
        touched, moved = set(), []
        try:
            files = self.execute(job, touched, moved)
        except JobRefused as refusal:
            reply = {'type': 'failed', 'job_id': job_id, 'failure': {'kind': refusal.kind, 'message': str(refusal)}}
        except Exception as error:  # the op's own failure
            reply = {'type': 'failed', 'job_id': job_id,
                     'failure': {'kind': 'job', 'message': f'{type(error).__name__}: {error}'}}
        else:
            reply = {'type': 'completed', 'job_id': job_id, 'outputs': {'files': files}}
        try:
            problem = self.reset(job, touched, moved, state)
        except Exception as error:  # the editor is in an unknown state: reply, then retire
            problem = f'reset raised {type(error).__name__}: {error}'
        self.send(reply)
        return problem

    def execute(self, job, touched, moved):
        job_dir = Path(job['job_dir'])
        if not job_dir.is_absolute() or not (job_dir / 'output').is_dir():
            raise JobRefused('protocol', 'the job folder is not a staged absolute folder with output/')
        if any((job_dir / 'output').iterdir()):
            raise JobRefused('protocol', 'output/ is not empty before the job')
        if any(self.content.iterdir()):
            raise JobRefused('dependency', '/Game is not empty before the job')
        declared, required = {}, set()
        for item in job['outputs']:
            path = _job_relative(item['path'], 'output')
            if not path.startswith(OUTPUT_CONTENT) or not path.endswith(PACKAGE_FILES):
                raise JobRefused('protocol', f'output {path!r} is not a package file under {OUTPUT_CONTENT}')
            declared[path] = item['required']
        packages = {package_of(path, OUTPUT_CONTENT) for path in declared} - {None}
        required = {package_of(path, OUTPUT_CONTENT) for path, need in declared.items() if need} - {None}
        if job['script'] not in job['code']:
            raise JobRefused('protocol', 'the entry script is outside the declared code')
        staged, inputs, input_packages = {}, {}, {}
        for item in job['inputs']:
            path = _job_relative(item['path'], 'input')
            source = job_dir / path
            present = item['identity']['state'] != 'absent'
            if present != os.path.lexists(source):
                raise JobRefused('protocol', f'input {item["name"]!r} does not match its staged presence')
            package = package_of(path, INPUT_CONTENT)
            if path.startswith(INPUT_CONTENT) and present:
                if not path.endswith(PACKAGE_FILES):
                    raise JobRefused('protocol', f'input {path!r} is not a package file')
                target = self.content / path[len(INPUT_CONTENT):]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                os.chmod(target, 0o444)
                staged[target] = sha256(target)
                if package:
                    input_packages[item['name']] = package
                    touched.add(package)
                    if package in packages:
                        raise JobRefused('protocol', f'{package} is both an input and an output')
                inputs[item['name']] = package or str(target)
            else:
                inputs[item['name']] = str(source) if present else None
        if staged:
            self.editor.scan(staged)
        self.settings = self.editor.settings()
        self.editor.begin_job()
        recording = True
        try:
            entry = runpy.run_path(str(job_dir / job['script']), run_name='atelier_unreal_job')
            if not callable(entry.get('run')):
                raise JobRefused('protocol', 'the entry script defines no run(context)')
            entry['run'](Context(job_dir, inputs, input_packages, job['params'], sorted(packages), self.content))
            self.editor.finish_background_work()
            saved = self.editor.saved_packages()
            recording = False
        finally:
            if recording:
                touched.update(item['package'] for item in self.editor.saved_packages())
        files_of = {}
        for item in saved:  # a rename saves the same package twice to the same file: one save
            files_of.setdefault(item['package'], set()).add(item['filename'])
        names = set(files_of)
        touched.update(names | packages)
        split = sorted(name for name, files in files_of.items() if len(files) > 1)
        if split:
            raise JobRefused('dependency', f'saved packages to more than one file: {split}')
        ensures = self.editor.ensures()
        if ensures:
            raise JobRefused('job', f'the editor reported {ensures} failed ensure(s) during the job')
        if names - packages:
            raise JobRefused('dependency', f'saved undeclared packages: {sorted(names - packages)}')
        if required - names:
            raise JobRefused('job', f'did not save declared packages: {sorted(required - names)}')
        dirty = sorted(name for name in self.editor.dirty_packages() if name.startswith(GAME))
        if dirty:
            raise JobRefused('job', f'left unsaved changes in {dirty}')
        for target, digest in staged.items():
            if not target.is_file() or sha256(target) != digest:
                raise JobRefused('dependency', f'input {target.relative_to(self.content)} changed')
        files = {}
        for directory, _, names_here in os.walk(self.content):
            for name in names_here:
                path = Path(directory, name)
                if path in staged:
                    continue
                relative = OUTPUT_CONTENT + str(path.relative_to(self.content))
                if relative not in declared:
                    raise JobRefused('dependency', f'wrote undeclared file {relative}')
                if package_owning(relative, OUTPUT_CONTENT) not in names:
                    # Only the editor's package saves produce outputs, never plain file writes.
                    raise JobRefused('dependency', f'{relative} was written without saving its package')
                files[relative] = path
        for relative, path in files.items():
            target = job_dir / 'output' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            moved.append(path)
            shutil.move(path, target)
        write_atomic(job_dir / IMPORT_EVIDENCE, {'version': EVIDENCE_VERSION, 'packages': [
            {'package': name, 'imports': self.editor.imports(name)} for name in sorted(names)]})
        return sorted(files)

    def reset(self, job, touched, moved, state):
        """Return the editor to its between-jobs state; returns the first problem, or None."""
        problems = []
        state.restore(Path(job['job_dir']))
        removed = list(moved)  # outputs moved to the job folder left /Game as well
        for directory, folders, names in os.walk(self.content, topdown=False):
            for name in names:
                path = Path(directory, name)
                os.chmod(path, 0o644)
                path.unlink()
                removed.append(path)
            for name in folders:
                Path(directory, name).rmdir()
        if removed:
            self.editor.forget(removed)
        remaining = self.editor.unload(sorted(touched | set(self.editor.loaded_game_packages())))
        if remaining:
            problems.append(f'packages still loaded after unload: {remaining}')
        if self.editor.loaded_game_packages():
            problems.append(f'/Game packages still loaded: {self.editor.loaded_game_packages()}')
        if self.editor.registry_game_assets():
            problems.append('the asset registry still lists /Game assets')
        before = getattr(self, 'settings', None)
        if before is not None:
            after = self.editor.settings()
            changed = sorted(name for name, value in before.items() if after.get(name) != value)
            # A variable registered during the job (a module loaded on demand) may stay only at its default.
            moved = sorted(name for name, value in after.items() if name not in before and value[1] != 'Constructor')
            if changed or moved:
                problems.append(f'the job changed editor settings: {(changed + moved)[:8]}')
        self.settings = None
        return '; '.join(problems) or None


class _PythonState:
    """sys.path, argv, environment, cwd and the module table, as they were before the job."""

    def __init__(self):
        self.path = list(sys.path)
        self.argv = list(sys.argv)
        self.environ = dict(os.environ)
        self.cwd = os.getcwd()
        self.modules = set(sys.modules)

    def restore(self, job_dir):
        sys.path[:] = self.path
        sys.argv[:] = self.argv
        os.environ.clear()
        os.environ.update(self.environ)
        os.chdir(self.cwd)
        for name in set(sys.modules) - self.modules:
            module = sys.modules.get(name)
            location = getattr(module, '__file__', None) or ''
            # Modules the job brought in from its own folder never outlive it.
            if location and Path(location).resolve().is_relative_to(job_dir.resolve()):
                del sys.modules[name]


def main():
    import unreal  # inside the editor

    editor = Editor(unreal)
    try:
        request_fd, response_fd = protocol_fds(editor.command_line())
        requests = os.fdopen(request_fd, 'rb', buffering=0)
        responses = os.fdopen(response_fd, 'wb', buffering=0)
        worker = Worker(editor, requests, responses)
        worker.start()
    except StartRefused as refusal:
        log(f'refusing to start: {refusal}')
        raise SystemExit(3)
    log(f'stopping: {worker.serve()}')


if __name__ == '__main__':
    main()
