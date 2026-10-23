"""A stand-in `UnrealEditor-Cmd` for T0: no engine, the same command line and worker surface.

Tests install this file, after a `#!<python> -sS` line, as `<engine>/Engine/Binaries/Mac/UnrealEditor-Cmd`.
It accepts only the command line `unreal.rs` builds, loads the declared project modules from the
scratch project's `Binaries/Mac` (a library whose bytes are `stale` makes it try to rebuild that
module, which fails on the read-only clone, as the real editor would), then installs a minimal
`unreal` module and runs the `-script` as `__main__`, as the `pythonscript` commandlet does.

The fake `unreal` module models only what the worker uses: a package table (loaded, dirty, pinned),
saved-package recording, the asset registry's view of `/Game`, settings, and `find_object`. Its
test-only `AtelierFake` class lets fixture ops create, save, load, pin and dirty packages, set a
CVar and write a stray file. Real Unreal behaviour is proven only by the admitted T2 session.
"""
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import types

FLAGS = ['-unattended', '-nop4', '-nosplash', '-stdout', '-AllowStdOutLogVerbosity', '-NullRHI']
ENGINE = Path(__file__).resolve().parents[3]
DEFAULT_ENGINE_PLUGINS = {'ContentBrowserData': ENGINE / 'Engine/Plugins/Editor/ContentBrowserData'}


def fail(message):
    print(f'fake-unreal: {message}', file=sys.stderr, flush=True)
    raise SystemExit(1)


argv = sys.argv[1:]
if len(argv) < 10 or argv[1] != '-run=pythonscript' or not argv[2].startswith('-script='):
    fail(f'unexpected command line {argv}')
if argv[3:9] != FLAGS or not argv[9].startswith('-UserDir='):
    fail(f'unexpected flags {argv[3:10]}')
settings = []
for token in argv[10:]:
    if token == '--request-fd':
        break
    if not token.startswith(('-ini:', '-ForceDPCVars=')):
        fail(f'undeclared argument {token}')
    settings.append(token)
uproject, script = Path(argv[0]), argv[2][len('-script='):]
project = uproject.parent
descriptor = json.loads(uproject.read_text())
build_id = json.loads((ENGINE / 'Engine/Build/Build.version').read_text())['BuildId']

libraries = []
for module in descriptor['Modules']:
    library = project / 'Binaries/Mac' / f'UnrealEditor-{module["Name"]}.dylib'
    if not library.is_file():
        fail(f'module {module["Name"]} is missing')
    if library.read_bytes() == b'stale':
        try:
            library.write_bytes(b'rebuilt')
        except OSError as error:
            fail(f'could not rebuild module {module["Name"]}: {error}')
    libraries.append(str(library))
plugins = dict(DEFAULT_ENGINE_PLUGINS)
for plugin in descriptor['Plugins']:
    if not plugin['Enabled']:
        continue
    folder = project / 'Plugins' / plugin['Name']
    plugins[plugin['Name']] = folder if folder.is_dir() else ENGINE / 'Engine/Plugins' / plugin['Name']
    libraries.extend(str(path) for path in sorted(folder.glob('Binaries/Mac/*.dylib')))
libraries.append(str(ENGINE / 'Engine/Binaries/Mac/libUnrealEditor-Core.dylib'))

CONTENT = project / 'Content'
packages = {}  # name -> {'loaded', 'dirty', 'pinned', 'imports'}
cvars = {token: '' for token in settings}
registry = set()
recording = None


def file_of(name):
    if not name.startswith('/Game/'):
        raise ValueError(f'{name} is not under /Game')
    return CONTENT / (name[len('/Game/'):] + '.uasset')


def name_of(path):
    relative = Path(path).resolve().relative_to(CONTENT.resolve())
    return '/Game/' + str(relative.with_suffix(''))


class Package:
    def __init__(self, name):
        self.name = name

    def get_name(self):
        return self.name


unreal = types.ModuleType('unreal')


class SystemLibrary:
    @staticmethod
    def get_command_line():
        return ' '.join(argv)

    @staticmethod
    def collect_garbage():
        for name in [n for n, p in packages.items() if not p['loaded'] and not p['pinned']]:
            del packages[name]


class Paths:
    @staticmethod
    def project_dir():
        return str(project) + '/'

    @staticmethod
    def engine_dir():
        return str(ENGINE / 'Engine') + '/'

    @staticmethod
    def convert_relative_path_to_full(path):
        return path


class EditorLoadingAndSavingUtils:
    @staticmethod
    def unload_packages(objects):
        any_unloaded = False
        for value in objects:
            entry = packages.get(value.get_name())
            if entry and not entry['pinned']:
                entry['loaded'] = False
                any_unloaded = True
        return any_unloaded


def find_object(outer, name):
    entry = packages.get(name)
    return Package(name) if entry and (entry['loaded'] or entry['pinned']) else None


class Registry:
    def scan_files_synchronous(self, files, force):
        registry.update(str(Path(path).resolve()) for path in files if Path(path).is_file())

    def get_assets_by_path(self, path, recursive):
        return sorted(registry)


class AssetRegistryHelpers:
    @staticmethod
    def get_asset_registry():
        return Registry()


class AtelierBuildWorkerLibrary:
    @staticmethod
    def native_context():
        return json.dumps({'build_id': build_id, 'modules': [m['Name'] for m in descriptor['Modules']],
                           'plugins': {name: str(folder) for name, folder in plugins.items()},
                           'libraries': libraries, 'rhi': 'null'})

    @staticmethod
    def begin_save_recording():
        global recording
        recording = []

    @staticmethod
    def end_save_recording():
        global recording
        saved, recording = recording or [], None
        return json.dumps(saved)

    @staticmethod
    def finish_background_work():
        pass

    @staticmethod
    def dirty_package_names():
        return [name for name, entry in packages.items() if entry['dirty']]

    @staticmethod
    def loaded_package_names(prefix):
        return [name for name, entry in packages.items()
                if name.startswith(prefix) and (entry['loaded'] or entry['pinned'])]

    @staticmethod
    def package_imports(name):
        return json.dumps(packages.get(name, {}).get('imports', []))

    @staticmethod
    def settings_digest():
        return hashlib.sha256(json.dumps(cvars, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def forget_files(paths):
        for path in paths:
            registry.discard(str(Path(path).resolve()))


class AtelierFake:
    """Test-only editor actions for fixture ops."""

    @staticmethod
    def create_package(name, payload, imports=()):
        packages[name] = {'loaded': True, 'dirty': True, 'pinned': False, 'payload': payload,
                          'imports': [list(item) for item in imports]}

    @staticmethod
    def save_package(name):
        entry = packages[name]
        path = file_of(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(entry['payload'])
        entry['dirty'] = False
        registry.add(str(path.resolve()))
        if recording is not None:
            recording.append({'package': name, 'filename': str(path)})

    @staticmethod
    def load_package(name):
        path = file_of(name)
        packages[name] = {'loaded': True, 'dirty': False, 'pinned': False, 'payload': path.read_bytes(),
                          'imports': []}
        return packages[name]['payload']

    @staticmethod
    def dirty(name):
        packages[name]['dirty'] = True

    @staticmethod
    def keep_alive(name):
        packages[name]['pinned'] = True

    @staticmethod
    def set_cvar(name, value):
        cvars[name] = value

    @staticmethod
    def write_file(relative, data):
        path = CONTENT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


for value in (SystemLibrary, Paths, EditorLoadingAndSavingUtils, AssetRegistryHelpers, AtelierBuildWorkerLibrary,
              AtelierFake):
    setattr(unreal, value.__name__, value)
unreal.find_object = find_object
sys.modules['unreal'] = unreal
sys.argv = [script]
runpy.run_path(script, run_name='__main__')
