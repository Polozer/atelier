"""Source-LOD admission never reassigns already-equal validated native bindings."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest
from types import SimpleNamespace


def test_equal_source_and_actual_geometry_skip_lod_reassignment_but_changes_miss(tmp_path,monkeypatch):
    names={level:tmp_path/f'GD_L1_Rope_LOD{level}_Piece00.fbx' for level in (1,2)}
    for path in names.values():path.write_bytes(b'original source')
    metadata={};writes=[];imports=[];positions={1:1,2:2}
    mesh=SimpleNamespace(get_num_triangles=lambda level:1,get_num_lods=lambda:3)
    library=SimpleNamespace(get_metadata_tag=lambda *_:metadata.get('value',''),
        set_metadata_tag=lambda _,key,value:(metadata.update(value=value),writes.append(key)))
    def snapshot(_,name,first,maximum,lod):
        return json.dumps(dict(schema=1,source_available=True,source_count=1,render_count=1,
            source=dict(triangles=[positions[lod]]),render=dict(triangles=[positions[lod]]),cooked=[]))
    unreal=SimpleNamespace(EditorAssetLibrary=library,
        NativeAtomicEquivalence=SimpleNamespace(snapshot=snapshot),
        GondolaLogicalMeshComponent=SimpleNamespace(rope_lod_source=lambda _,lod:str(names[lod])))
    monkeypatch.setitem(sys.modules,'unreal',unreal)
    path=Path(__file__).resolve().parents[1]/'unreal/Scripts/gondola_native.py'
    spec=importlib.util.spec_from_file_location('gondola_native_lod_test',path)
    native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
    editor=SimpleNamespace(import_lod=lambda _,lod,source:(imports.append(lod) or lod))
    native.import_lods(mesh,'GD_L1_Rope_LOD0_Piece00',tmp_path,editor)
    assert imports==[1,2] and len(writes)==1
    imports.clear();writes.clear()
    native.import_lods(mesh,'GD_L1_Rope_LOD0_Piece00',tmp_path,editor)
    assert imports==writes==[]
    names[2].write_bytes(b'changed source')
    native.import_lods(mesh,'GD_L1_Rope_LOD0_Piece00',tmp_path,editor)
    assert imports==[2] and len(writes)==1
    imports.clear();writes.clear();positions[1]=99
    native.import_lods(mesh,'GD_L1_Rope_LOD0_Piece00',tmp_path,editor)
    assert imports==[1] and len(writes)==1


def native_module(monkeypatch,snapshot):
    monkeypatch.setitem(sys.modules,'unreal',SimpleNamespace(NativeAtomicEquivalence=SimpleNamespace(snapshot=snapshot)))
    path=Path(__file__).resolve().parents[1]/'unreal/Scripts/gondola_native.py'
    spec=importlib.util.spec_from_file_location('gondola_native_receiving_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def native_page(first,maximum,count):
    triangle=dict(corners=[dict(position=value) for value in ([0,0,0],[1,0,0],[0,1,0])])
    rows=[triangle for _ in range(maximum)]
    return dict(schema=1,source_available=True,source_count=count,render_count=count,cooked_count=count,
        first=first,lod=0,slots=[dict(name='GD_Timber',material='material')],settings=dict(lods=1),bounds=[[0,0,0],[1,1,1]],
        source=dict(triangles=rows),render=dict(triangles=rows),cooked=[[[0,0,0],[1,0,0],[0,1,0]] for _ in rows])


def test_receiving_pages_require_complete_actual_source_gpu_and_cooked_inventory(monkeypatch):
    calls=[]
    def snapshot(mesh,name,first,maximum,lod):
        calls.append((first,maximum));return json.dumps(native_page(first,maximum,4097))
    native=native_module(monkeypatch,snapshot)
    value=native.native_pages(object(),'GD_floor_rim_Access_Piece00',0,4097)
    assert calls==[(0,4096),(4096,1)] and len(value['triangles'])==4097
    assert len(value['sha256'])==64


@pytest.mark.parametrize('damage',['unavailable','wrong_count','missing_source','missing_render','missing_cooked','changed_header'])
def test_receiving_missing_or_changing_native_data_refuses(monkeypatch,damage):
    def snapshot(mesh,name,first,maximum,lod):
        page=native_page(first,maximum,4097)
        if first:
            if damage=='unavailable':page['source_available']=False
            elif damage=='wrong_count':page['render_count']-=1
            elif damage=='changed_header':page['bounds'][1][0]=2
            elif damage=='missing_cooked':page['cooked']=[]
            else:page[damage.removeprefix('missing_')]['triangles']=[]
        return json.dumps(page)
    native=native_module(monkeypatch,snapshot)
    with pytest.raises(ValueError):native.native_pages(object(),'GD_floor_rim_Access_Piece00',0,4097)


def test_retirement_requires_the_complete_validated_current_roster(monkeypatch):
    native=native_module(monkeypatch,lambda *_:'')
    for proof in (None,(),('GD_floor_rim_Access_Piece00',)):
        state=dict(current=['GD_floor_rim_Access_Piece00','GD_floor_rim_Access_Piece01'],validated_current=proof)
        with pytest.raises(ValueError,match='before retirement'):native.retire(state)


def test_current_access_seam_validation_refuses_missing_cross_owned_boundary(monkeypatch):
    native=native_module(monkeypatch,lambda *_:'')
    with pytest.raises(ValueError,match='no actual shared'):
        native.validate_access_seams({},dict(A=[[(0,0,0),(1,0,0),(0,1,0)]],B=[[(2,0,0),(3,0,0),(2,1,0)]]))
