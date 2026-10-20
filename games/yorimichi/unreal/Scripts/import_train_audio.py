"""Import the Belmonte train sounds (build/yorimichi/audio/train, built by assets/audio/train/make.py) as /Game/Audio/Train/<cue>_<nn>.

    UnrealEditor-Cmd Yorimichi.uproject -run=pythonscript -script=Scripts/import_train_audio.py -unattended -nosplash -NullRHI -stdout

ABelmonteTrainService loads each cue by name (<cue>_01). The manifest's loops (idle, effort, roll) are imported looping;
waves of cues the recipe no longer builds are removed.
"""
import sys as _sys; from pathlib import Path as _Path; _sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / 'world')); import yori  # noqa: E402  (build/yorimichi = yori.OUT)
import json
from pathlib import Path
import unreal as U

ROOT = yori.OUT
SOURCE = ROOT / 'audio/train'
DEST = '/Game/Audio/Train'
LOOPS = set(json.loads((SOURCE / 'manifest.json').read_text())['loops'])
E = U.EditorAssetLibrary; AT = U.AssetToolsHelpers.get_asset_tools()
E.make_directory(DEST)
files = sorted(SOURCE.glob('*/*.wav'))
# A cue the recipe no longer builds (make.py SPEC unchosen) leaves no stale wave the game would still play.
removed = []
for path in E.list_assets(DEST, recursive=False, include_folder=False):
    package = str(path).split('.')[0]
    name = package.rsplit('/', 1)[-1]
    if name not in {p.stem for p in files}:
        assert E.delete_asset(package), f'train audio: could not delete the stale {package}'
        # A commandlet exits before the editor's deferred cleanup removes the package file: remove this owned file here.
        Path(U.Paths.convert_relative_path_to_full(U.Paths.project_content_dir()), package[len('/Game/'):] + '.uasset').unlink(missing_ok=True)
        removed.append(name)
tasks = []
for wav in files:
    task = U.AssetImportTask()
    for k, v in dict(filename=str(wav), destination_path=DEST, destination_name=wav.stem, automated=True, replace_existing=True, save=False).items():
        task.set_editor_property(k, v)
    task.set_editor_property('factory', U.SoundFactory())
    tasks.append(task)
AT.import_asset_tasks(tasks)
imported = {}
for task in tasks:
    for path in task.get_editor_property('imported_object_paths'):
        wave = E.load_asset(path)
        if not isinstance(wave, U.SoundWave): continue
        loop = wave.get_name().rsplit('_', 1)[0] in LOOPS
        wave.set_editor_property('looping', loop)
        E.save_loaded_asset(wave)
        imported[wave.get_name()] = {'path': wave.get_path_name(), 'duration': wave.get_editor_property('duration'), 'looping': loop}
missing = sorted({p.stem for p in files} - set(imported))
(ROOT / 'train_audio_import.json').write_text(json.dumps({'imported': imported, 'missing': missing, 'removed': removed}, indent=2) + '\n')
if missing: raise SystemExit(f'train audio: {len(missing)} files not imported: {missing}')
U.log(f'TRAIN AUDIO IMPORT COMPLETE {len(imported)} waves')
