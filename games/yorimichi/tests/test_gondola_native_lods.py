"""Source-LOD admission never reassigns already-equal validated native bindings."""
import importlib.util
import json
from pathlib import Path
import sys
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
