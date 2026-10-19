"""Unreal asset operations shared by import and a separate cold reload verifier."""
import unreal as U

from soundbank_package_data import ROOT, asset, require

E = U.EditorAssetLibrary
TOOLS = U.AssetToolsHelpers.get_asset_tools()


def load(path, kind):
    result = E.load_asset(path)
    require(isinstance(result, kind) and result.get_path_name() == path, 'Missing or wrong soundbank asset: ' + path)
    return result


def save(value):
    require(E.save_loaded_asset(value, only_if_is_dirty=False), 'Could not save soundbank asset')


def data_asset(path, kind):
    folder, name = path.split('.')[0].rsplit('/', 1)
    factory = U.DataAssetFactory()
    factory.set_editor_property('data_asset_class', kind)
    result = TOOLS.create_asset(name, folder, kind, factory)
    require(isinstance(result, kind), 'Could not create soundbank data asset')
    return result


def wave_check(wave, row):
    require(isinstance(wave, U.SoundWave) and wave.get_path_name() == row['asset']
            and wave.get_editor_property('num_channels') == 1
            and wave.get_editor_property('imported_sample_rate') == 48000
            and abs(wave.get_editor_property('duration') - row['frames'] / 48000) < 1 / 48000
            and wave.get_editor_property('looping') is row['loop']
            and wave.get_editor_property('loading_behavior') == U.SoundWaveLoadingBehavior.FORCE_INLINE
            and wave.get_sound_asset_compression_type() == U.SoundAssetCompressionType.PCM,
            'Imported soundbank PCM/loop/loading policy mismatch: ' + row['asset'])


def properties(value, fields):
    for key, expected in fields.items():
        require(value.get_editor_property(key) == expected, 'Saved soundbank property mismatch: ' + key)


def verify(plan):
    """Inspect the full saved object/reference closure; a caller in a fresh editor proves reload."""
    expected = set()
    for row in plan['banks']:
        runtime = row['runtime']
        identity = runtime['id']
        waves = {}
        for wav in row['waves']:
            sound = load(wav['asset'], U.SoundWave)
            wave_check(sound, wav)
            waves[wav['name']] = sound
            expected.add(wav['asset'].split('.')[0])
        if runtime['legacy']:
            continue
        skate_path = asset(identity, 'DA_Skate')
        skate = load(skate_path, U.SkateSoundSet)
        expected.add(skate_path.split('.')[0])
        properties(skate, {'loops': {U.Name(k): waves[n] for k, n in row['loops'].items()}})
        shots = skate.get_editor_property('one_shots')
        require({str(k) for k in shots} == set(row['oneshots']), 'Unexpected saved skate cues')
        for key, names in row['oneshots'].items():
            properties(shots[U.Name(key)], {'variants': [waves[n] for n in names]})
        bank = load(runtime['asset'], U.JapanSoundBank)
        expected.add(runtime['asset'].split('.')[0])
        properties(bank, {'key': U.Name(identity), 'source_manifest_hash': runtime['source_manifest_sha256'],
                          'skate': skate, 'audition': waves['Audition']})
        feet = bank.get_editor_property('footsteps')
        require({str(k) for k in feet} == set(row['footsteps']), 'Unexpected saved foot pools')
        for key, names in row['footsteps'].items():
            properties(feet[U.Name(key)], {'variants': [waves[n] for n in names]})
    actual = {path.split('.')[0] for path in E.list_assets(ROOT, recursive=True, include_folder=False)}
    require(actual == expected, 'Unexpected or missing packages in owned AudioBanks root')
