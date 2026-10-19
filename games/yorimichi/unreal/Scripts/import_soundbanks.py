"""Import checked banks into the exclusively owned /Game/AudioBanks root.

This creates a candidate receipt only. A second, cold editor must verify saved
packages before a registry can be staged. Existing Original cue assets are untouched.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'world'))
import yori
import unreal as U

from soundbank_package_data import ROOT, asset, clear_packages, media, packages, preflight, publish, receipt, require
from soundbank_assets import E, TOOLS, data_asset, save, verify, wave_check


def main():
    plan = preflight(yori.OUT)
    identity = receipt(plan)
    # Resolve required reflected types before deleting any owned package.
    require(all(hasattr(U, name) for name in ('JapanSoundBank', 'JapanSoundPool', 'SkateSoundSet', 'SkateSoundPool')),
            'Missing compiled soundbank types')
    folder = yori.OUT / 'soundbank_import'
    (folder / 'registry.json').unlink(missing_ok=True)
    (folder / 'candidate.json').unlink(missing_ok=True)
    clear_packages(yori.GAME / 'unreal/Content', E)
    require(E.make_directory(ROOT), 'Cannot create soundbank package root')
    for row in plan['banks']:
        runtime = row['runtime']
        waves = {}
        for wav in row['waves']:
            target, name = wav['asset'].split('.')[0].rsplit('/', 1)
            task = U.AssetImportTask()
            for key, value in dict(filename=str(media(yori.OUT, wav)), destination_path=target, destination_name=name,
                                   automated=True, replace_existing=True, save=False, factory=U.SoundFactory()).items():
                task.set_editor_property(key, value)
            TOOLS.import_asset_tasks([task])
            require(list(task.get_editor_property('imported_object_paths')) == [wav['asset']], 'Unexpected wave import result')
            sound = E.load_asset(wav['asset'])
            require(isinstance(sound, U.SoundWave), 'Wave importer did not produce a SoundWave')
            sound.set_editor_property('looping', wav['loop'])
            sound.set_editor_property('loading_behavior', U.SoundWaveLoadingBehavior.FORCE_INLINE)
            sound.set_sound_asset_compression_type(U.SoundAssetCompressionType.PCM)
            wave_check(sound, wav)
            save(sound)
            waves[wav['name']] = sound
            U.log('Soundbank wave saved: ' + wav['asset'])
        if not runtime['legacy']:
            skate = data_asset(asset(runtime['id'], 'DA_Skate'), U.SkateSoundSet)
            skate.set_editor_property('one_shots', {U.Name(k): U.SkateSoundPool(variants=[waves[n] for n in names])
                                                   for k, names in row['oneshots'].items()})
            skate.set_editor_property('loops', {U.Name(k): waves[n] for k, n in row['loops'].items()})
            save(skate)
            bank = data_asset(runtime['asset'], U.JapanSoundBank)
            for key, value in dict(key=U.Name(runtime['id']), source_manifest_hash=runtime['source_manifest_sha256'],
                                   skate=skate, audition=waves['Audition'],
                                   footsteps={U.Name(k): U.JapanSoundPool(variants=[waves[n] for n in names])
                                              for k, names in row['footsteps'].items()}).items():
                bank.set_editor_property(key, value)
            save(bank)
    verify(plan)
    require(preflight(yori.OUT) == plan and receipt(plan) == identity, 'Soundbank inputs changed during import')
    publish(folder / 'candidate.json', {**identity, 'packages': packages(yori.GAME / 'unreal/Content')})
    U.log('SOUNDBANK IMPORT COMPLETE')


main()
