"""Complete face ownership, fixed cross-LOD identities and explicit oversize refusal."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'world'))
from gondola.parts import face_groups,names,access_groups


@pytest.mark.parametrize('line,counts',[('L1',(47176,4632,1888)),('L2',(59392,5080,2056))])
def test_all_original_faces_survive_two_coordinated_lod_members(line,counts):
    for lod,triangles in enumerate(counts):
        faces=[(0,1,2,3)]*(triangles//2)
        groups=face_groups(f'GD_{line}_Rope_LOD{lod}',faces,2)
        assert [key for key,_ in groups]==names(line,lod)
        assert [index for _,members in groups for index in members]==list(range(len(faces)))
        assert all(sum(len(faces[index])-2 for index in members)<=32768 for _,members in groups)


def test_declared_members_remain_stable_below_budget_and_l3_keeps_original_names():
    faces=[(0,1,2)]*100
    assert len(face_groups('GD_L1_Rope_LOD1',faces,2))==2
    assert face_groups('GD_L3_Rope_LOD0',faces,1)==[('GD_L3_Rope_LOD0',tuple(range(100)))]
    with pytest.raises(ValueError,match='authored'):
        face_groups('GD_L1_Rope_LOD0',faces,1)
    with pytest.raises(ValueError,match='bounded'):
        face_groups('GD_L2_Rope_LOD0',[(0,1,2,3)]*40000,2)


def test_large_original_ngon_cannot_be_discarded_or_split_to_hide_a_budget_failure():
    with pytest.raises(ValueError,match='bounded'):
        face_groups('GD_L1_Rope_LOD0',[tuple(range(40000)),(0,1,2)],2)


def test_oversized_access_keeps_all_original_collision_faces_in_two_bounded_members():
    faces=[(0,1,2,3)]*(38820//2)
    groups=access_groups('GD_floor_rim_Access',faces)
    assert [key for key,_ in groups]==['GD_floor_rim_Access_Piece00','GD_floor_rim_Access_Piece01']
    assert [index for _,members in groups for index in members]==list(range(len(faces)))
    assert all(sum(len(faces[index])-2 for index in members)<=32768 for _,members in groups)
    with pytest.raises(ValueError):access_groups('GD_southeast_Access',faces)
