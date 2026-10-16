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


def test_sunburst_textures_and_atlas_exist():
    for slug in ('sandogasa_weave', 'sode_lacquer', 'jinmaku_stripe', 'sashimono_maple'):
        jpg = TEXTURES / f'{slug}.jpg'
        prov = TEXTURES / f'{slug}.provenance.json'
        assert jpg.is_file(), f'Missing Sunburst texture {jpg}'
        assert prov.is_file(), f'Missing texture provenance {prov}'
        data = json.loads(prov.read_text())
        assert data['requested_model'] == 'gpt-image-2.5-sunburst'
        assert data['quality'] == 'high'
    atlas = TEXTURES / 'swordcamp_atlas.jpg'
    assert atlas.is_file()
    im = Image.open(atlas)
    assert im.size == (2048, 2048)


def test_combat_hit_registration_and_ronin_camp_wired():
    combat_cpp = (SOURCE / 'AdventureMoveSetCombat.cpp').read_text()
    assert 'else if (Now && bArmed && IsAttack(Name)) BladePoints(PreviousBlade);' in combat_cpp
    assert 'for (const ECollisionChannel Chan : { ECC_Visibility, ECC_Pawn })' in combat_cpp
    assert 'bool UAdventureMoveSet::GetBladePose' in combat_cpp
    trainer_cpp = (SOURCE / 'SwordTrainer.cpp').read_text()
    assert 'void ASwordTrainer::SpawnRoninCamp' in trainer_cpp
    assert 'void ASwordTrainer::AlertCamp' in trainer_cpp
    assert 'whiff_space' in trainer_cpp
    gamemode_cpp = (SOURCE / 'JapanGameMode.cpp').read_text()
    assert 'ASwordTrainer::SpawnRoninCamp(W);' in gamemode_cpp
