"""Verify the Kasa Ronin & Roadside Mini-Camp Sunburst concepts, texture atlas, procedural builder, and combat C++ wiring."""
import json
from pathlib import Path
from PIL import Image

REPO = Path(__file__).resolve().parents[3]
GAME = REPO / 'games' / 'yorimichi'
CONCEPTS = GAME / 'assets' / 'swordcamp' / 'concepts'
TEXTURES = GAME / 'assets' / 'swordcamp' / 'textures'
REGION = GAME / 'world' / 'regions' / 'swordcamp'
SOURCE = GAME / 'unreal' / 'Source' / 'Yorimichi'


def test_sunburst_concepts_and_provenance_records_exist():
    import hashlib
    for slug in ('ronin_armor_kit', 'camp_kit'):
        jpg = CONCEPTS / f'{slug}.jpg'
        prov = CONCEPTS / f'{slug}.provenance.json'
        prompt = CONCEPTS / f'{slug}.prompt.txt'
        assert jpg.is_file(), f'Missing concept image {jpg}'
        assert prov.is_file(), f'Missing provenance ledger {prov}'
        assert prompt.is_file(), f'Missing prompt file {prompt}'
        data = json.loads(prov.read_text())
        assert data['requested_model'] == 'gpt-image-2.5-sunburst'
        assert data['quality'] == 'high'
        assert data['status'] == 'done'
        assert data['compact_copy']['file'] == jpg.name
        assert data['compact_copy']['sha256'] == hashlib.sha256(jpg.read_bytes()).hexdigest()


def test_sunburst_textures_and_atlas_exist(tmp_path):
    import hashlib
    for slug in ('sandogasa_weave', 'sode_lacquer', 'jinmaku_stripe', 'sashimono_maple'):
        jpg = TEXTURES / f'{slug}.jpg'
        prov = TEXTURES / f'{slug}.provenance.json'
        assert jpg.is_file(), f'Missing Sunburst texture {jpg}'
        assert prov.is_file(), f'Missing texture provenance {prov}'
        data = json.loads(prov.read_text())
        assert data['requested_model'] == 'gpt-image-2.5-sunburst'
        assert data['quality'] == 'high'
        assert data['compact_copy']['file'] == jpg.name
        assert data['compact_copy']['sha256'] == hashlib.sha256(jpg.read_bytes()).hexdigest()
    import sys
    sys.path.insert(0, str(REGION))
    import make_atlas
    out = tmp_path / 'swordcamp_atlas.jpg'
    make_atlas.build_atlas(out)
    im = Image.open(out)
    assert im.size == (2048, 2048)


def test_combat_hit_registration_and_ronin_camp_wired():
    combat_cpp = (SOURCE / 'AdventureMoveSetCombat.cpp').read_text()
    assert 'else if (Now && bArmed && IsAttack(Name)) BladePoints(PreviousBlade);' in combat_cpp
    assert 'for (const ECollisionChannel Chan : { ECC_Visibility, ECC_Pawn })' in combat_cpp
    assert 'bool UAdventureMoveSet::GetBladePose' in combat_cpp
    moveset_h = (SOURCE / 'AdventureMoveSet.h').read_text()
    assert 'void SetCombatTarget(AActor* NewTarget)' in moveset_h
    trainer_cpp = (SOURCE / 'SwordTrainer.cpp').read_text()
    assert 'void ASwordTrainer::SpawnRoninCamp' in trainer_cpp
    assert 'void ASwordTrainer::AlertCamp' in trainer_cpp
    assert 'whiff_space' in trainer_cpp
    assert 'SM_GuardJingasa' in trainer_cpp
    assert 'SM_CaptainKabuto' in trainer_cpp
    assert 'SM_RoninDo' in trainer_cpp
    assert 'SM_RoninWakizashi' in trainer_cpp
    assert 'M_RoninBody' in trainer_cpp
    assert 'GetAnimatedWorldQuat' in trainer_cpp
    assert 'SetCombatTarget' in trainer_cpp
    assert 'PeerRepulse' in trainer_cpp
    gamemode_cpp = (SOURCE / 'JapanGameMode.cpp').read_text()
    assert 'ASwordTrainer::SpawnRoninCamp(W);' in gamemode_cpp
