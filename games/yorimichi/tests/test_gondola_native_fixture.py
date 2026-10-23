"""Immutable native finishing keeps all operations; only explicit shader package literals move."""
import ast
import importlib.util
from pathlib import Path

import pytest

PATH=Path(__file__).parent/'native/prepare_gondola_native.py'
spec=importlib.util.spec_from_file_location('gondola_native_host_test',PATH)
host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)


def test_selected_native_finishing_keeps_complete_body_and_order():
    source=(host.GAME/'unreal/Scripts/import_gondola.py').read_text()
    original=next(node for node in ast.parse(source).body if isinstance(node,ast.For) and isinstance(node.target,ast.Tuple))
    selected=ast.parse(host.finishing(source,'selected')).body[0]
    assert [ast.dump(node,include_attributes=False) for node in selected.body]==[ast.dump(node,include_attributes=False) for node in original.body]
    assert [arg.arg for arg in selected.args.args]==['folder','dest','names']


def test_shader_namespace_mapping_is_finite_and_reversible():
    source=(host.GAME/'unreal/Scripts/import_gondola.py').read_text()
    material=next(node for node in ast.parse(source).body if isinstance(node,ast.FunctionDef) and node.name=='material')
    text=ast.unparse(material)
    actual=host.material_namespace(text,'/Game/AtelierValidation/GondolaAtomicNative_0123456789ab')
    assert '/Game/Gondola/' not in actual
    assert actual.count('/Game/AtelierValidation/GondolaAtomicNative_0123456789ab/Textures')==2
    with pytest.raises(ValueError,match='literals changed'):
        host.material_namespace(text.replace('/Game/Gondola/Materials','/Game/Other/Materials'),'/Game/Fixture')


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def test_actual_gondola_unreal_import_closure_refuses_host_only_dependencies(tmp_path):
    import subprocess
    import sys
    native=PATH.parent
    code=r'''
import ast,importlib.abc,pathlib,sys,types
native=pathlib.Path(sys.argv[1]);game=native.parents[1]
sys.dont_write_bytecode=True
sys.path[:0]=[str(native),str(game/'unreal/Scripts')]
class BlockHost(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='atomic_equivalence' or fullname.split('.')[0] in ('numpy','mesh_ir') or fullname=='atelier.mesh_ir':
   raise ModuleNotFoundError('host-only dependency forbidden: '+fullname)
sys.meta_path.insert(0,BlockHost())
u=types.ModuleType('unreal');u.EditorAssetLibrary=types.SimpleNamespace();u.MaterialEditingLibrary=types.SimpleNamespace()
u.AssetToolsHelpers=types.SimpleNamespace(get_asset_tools=lambda:object());u.AssetRegistryHelpers=types.SimpleNamespace(get_asset_registry=lambda:object());u.log=lambda *args:None
sys.modules['unreal']=u
import gondola_native_equivalence as fixture
fixture.native_imports()
assert callable(fixture.capture.capture) and callable(fixture.gondola_native.validate_receiving)
legacy=fixture.load('actual_gondola_mesh_import',game/'unreal/Scripts/mesh_import.py')
assert callable(legacy.import_mesh)
import prepare_gondola_native as prepare
text=(game/'unreal/Scripts/import_gondola.py').read_text()
material=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='material')
scope={};exec(prepare.material_namespace(ast.unparse(material),'/Game/AtelierValidation/GondolaAtomicNative_0123456789ab'),scope)
exec(prepare.finishing(text,'actual_finish'),scope)
assert callable(scope['material']) and callable(scope['actual_finish'])
assert 'atomic_equivalence' not in sys.modules and 'numpy' not in sys.modules and 'atelier.mesh_ir' not in sys.modules
from track_native_equivalence import actor_scope,release_actor,retire_owned,receiving_startup
assert fixture.actor_scope is actor_scope and fixture.release_actor is release_actor and fixture.retire_owned is retire_owned and fixture.receiving_startup is receiving_startup
print('ACTUAL GONDOLA STDLIB NATIVE CLOSURE VERIFIED')
'''
    result=subprocess.run([sys.executable,'-I','-S','-c',code,str(native)],cwd=tmp_path,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'ACTUAL GONDOLA STDLIB NATIVE CLOSURE VERIFIED' in result.stdout


def test_native_asset_capture_and_retirement_share_strict_failure_boundary():
    tree=ast.parse((PATH.parent/'gondola_native_equivalence.py').read_text())
    native=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_native')
    boundary=[n for n in ast.walk(native) if isinstance(n,ast.With) and any(
        ast.unparse(item.context_expr).startswith('actor_scope(') for item in n.items)]
    assert len(boundary)==1
    calls={ast.unparse(n.func) for n in ast.walk(boundary[0]) if isinstance(n,ast.Call)}
    assert {'capture.capture','release_actor','retire_owned','fixture_files'} <= calls
    assert not any(isinstance(n,ast.Attribute) and n.attr=='delete_directory' for n in ast.walk(tree))
    assert 'compare' not in {n.name for n in tree.body if isinstance(n,ast.FunctionDef)}


def host_runner():
    return module('gondola_actual_host_test',PATH.with_name('run_gondola_native_equivalence.py'))


@pytest.mark.parametrize('field',['source_lods','render_lods','cooked','hulls','settings','source_presence','policy'])
def test_host_comparison_rejects_each_actual_native_basis_difference(monkeypatch,field):
    import copy
    runner=host_runner()
    original=dict(policy_scope='fixture',source_lods={0:1,1:1,2:1},render_lods={0:1,1:1,2:1},cooked={},hulls={},settings={},source_presence={},policy={},
        seams=set(),probes=dict(controls=[dict(kind='ray_negative',hit=None)]))
    actual=copy.deepcopy(original)
    if field in ('source_lods','render_lods'):actual[field][0]=2
    else:actual[field]={'changed':True}
    monkeypatch.setattr(runner.eq,'native_raw_set',lambda record,parent:record)
    with pytest.raises(ValueError,match='differs'):
        runner.compare(original,actual,'GD_L1_Rope_LOD0')


def test_host_comparison_refuses_missing_authored_gpu_lod(monkeypatch):
    runner=host_runner();row=dict(policy_scope='fixture',source_lods={0:1},render_lods={0:1})
    monkeypatch.setattr(runner.eq,'native_raw_set',lambda record,parent:record)
    with pytest.raises(ValueError,match='LOD census'):runner.compare(row,row,'GD_L1_Rope_LOD0')


def test_host_fullproof_stops_before_reads_or_cleanup_on_failed_guard(tmp_path,monkeypatch):
    import json
    runner=host_runner();called=[]
    monkeypatch.setattr(runner,'unchanged',lambda value:called.append('inputs'))
    monkeypatch.setattr(runner,'strict_cleanup',lambda *args:called.append('cleanup'))
    with pytest.raises(ValueError,match='Guard evidence'):
        runner.finalize(tmp_path/'spec.json',json.dumps(dict(output=str(tmp_path))).encode(),{}, {},lambda:called.append('native'))
    assert called==[]


def test_host_true_sphere_refuses_same_box_with_changed_radius():
    runner=host_runner()
    def row(radius):
        return dict(component_bounds=dict(origin=[0,0,0],extent=[1,2,3],sphere_radius=radius),
            bounds_scale=1.,lod_coordinated=False,logical_bounds=None,matrix=[[1,0],[0,1]])
    with pytest.raises(ValueError,match='sphere'):
        runner.compare_bounds([dict(original=row(4),actual=[row(4),row(5)])],'GD_L1_Rope_LOD0')


def frozen_fixture(tmp_path):
    import json
    root=tmp_path/'frozen';root.mkdir();files={};exports=[];rope=dict(assets={},native_fixture={})
    def put(relative,data):
        path=root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        files[str(path)]=host.identity(path);return path
    site=put('site.json',b'{"unit_source_copy_fixture":true}')
    for parent in host.PARENTS:
        pairs=[]
        for lod in (range(3) if '_Rope_' in parent else range(1)):
            key=parent.replace('_LOD0',f'_LOD{lod}')
            before=put(f'out/gondola/world/assets/{key}.fbx',('unit original '+key).encode())
            actual=[];pieces=[]
            for index in range(2):
                name=key+f'_Piece{index:02d}'
                path=put(f'out/gondola/world/atomic-assets/{name}.fbx',('unit bounded '+name).encode())
                actual.append(dict(path=str(path),sha256=host.identity(path)['sha256']))
                pieces.append(dict(name=name,sha256=host.identity(path)['sha256'],triangles=1))
            pairs.append(dict(baseline=dict(path=str(before),sha256=host.identity(before)['sha256']),actual=actual))
            exports.append(dict(name=key,materials=['GD_Test'],pieces=pieces))
            if '_Rope_' in parent:rope['assets'][key]=dict(source_exact=True,serialized_fbx_exact=True,max_piece_triangles=1,stored_contact=dict(pass_=True))
        if '_Rope_' in parent:rope['native_fixture'][parent[3:5]]=dict(lods=pairs)
        else:access=dict(source_exact=True,actual_serialized_fbx_exact=True,max_piece_triangles=1,seams=list(range(8)),native_fixture=pairs[0])
    for row in rope['assets'].values():row['stored_contact']={'pass':True}
    rope['profiles_sha256']=host.identity(site)['sha256']
    put('out/gondola/manifest.json',b'{"unit_copy_only":true}')
    for index in range(12):put(f'out/gondola/textures/GD_unit{index}.png',('unit shader '+str(index)).encode())
    for kind,report in [('current-rope',rope),('current-access-rim',access)]:
        for name,value in [('whole-result.json',dict(exit_code=0,source_and_fixture_unchanged=True)),
                           ('inputs.json',dict(unit_fixture=True)),
                           ('guard/memory-health-tree.json',dict(state='child_exited',cleanup_complete=True,processes=[],footprint_bytes=0)),
                           ('results/proof.json',report)]:put('source-evidence/'+kind+'/'+name,json.dumps(value).encode())
    for name in ('mesh_import.py','import_gondola.py'):put('archive/'+name,(host.GAME/'unreal/Scripts'/name).read_bytes())
    for name in ('material.py','finish_before.py','finish_after.py'):put('archive/'+name,b'# unexecuted prior namespace wrapper\n')
    site.write_text(json.dumps(dict(inputs=dict(
        kit={Path(name).relative_to(root/'out/gondola').as_posix():row['sha256'] for name,row in files.items()
             if name.startswith(str(root/'out/gondola/textures')+'/') or name==str(root/'out/gondola/manifest.json')},
        code={'games/yorimichi/unreal/Scripts/'+name:files[str(root/'archive'/name)]['sha256']
              for name in ('mesh_import.py','import_gondola.py')}))))
    files[str(site)]=host.identity(site)
    rope['profiles_sha256']=host.identity(site)['sha256']
    report=root/'source-evidence/current-rope/results/proof.json';report.write_text(json.dumps(rope));files[str(report)]=host.identity(report)
    source=tmp_path/'actual_source.py';source.write_text('# frozen source authority\n')
    spec=dict(schema=1,region='gondola-native',original_revision=host.ORIGINAL,original_names=list(host.PARENTS),exports=exports,
        current_names=sorted(p['name'] for row in exports if '_Rope_LOD1' not in row['name'] and '_Rope_LOD2' not in row['name'] for p in row['pieces']),
        frozen_files=files,source_files={str(source):host.identity(source)},scope='unit source-copy fixture; no actual native acceptance')
    path=root/'spec.json';path.write_text(json.dumps(spec));return root,path,spec


def test_preparation_reuses_only_exact_frozen_inputs_and_rebinds_current_driver(tmp_path,monkeypatch):
    import json
    root,path,old=frozen_fixture(tmp_path)
    # The old live producer is retired. Its exact independent frozen handoff,
    # not a producer checkout or old native certificate, is the consumed authority.
    for name in old['source_files']:Path(name).unlink()
    monkeypatch.setattr(host,'bind_code',lambda rows:rows.update({str(PATH):host.identity(PATH)}))
    engine=tmp_path/'engine/Engine';(engine/'Config').mkdir(parents=True);(engine/'Config/BaseEngine.ini').write_text('unit engine config')
    monkeypatch.setattr(host,'runtime_binding',lambda output:({'unit_compiled_binding':True},{'engine_dir':str(engine)}))
    target=tmp_path/'prepared';result=host.reuse_frozen(root,target,tmp_path/'receiving/Content',host.identity(path)['sha256'])
    current=json.loads(result.read_bytes())
    assert current['schema']==2 and current['native']=={'unit_compiled_binding':True}
    assert current['source_fixture']['consumed_authority']=='frozen_files'
    assert not set(old['source_files']) & set(current['source_files'])
    assert str(PATH) in current['source_files']
    assert len(list((target/'out').rglob('*.fbx')))==21
    assert len(list((target/'out/gondola/textures').glob('*.png')))==12
    assert current['namespace'] in (target/'archive/material.py').read_text()
    assert not (target/'current/native.json').exists()
    assert all(host.identity(Path(name))==row for name,row in old['frozen_files'].items())
    assert not {str(path) for path in target.rglob('*.fbx')} & set(old['frozen_files'])


@pytest.mark.parametrize('fault',['authority','changed_fbx','missing_member','failed_source'])
def test_frozen_preparation_refuses_before_copy_or_native_binding(tmp_path,monkeypatch,fault):
    import json
    root,path,spec=frozen_fixture(tmp_path);expected=host.identity(path)['sha256'];calls=[]
    monkeypatch.setattr(host,'runtime_binding',lambda output:calls.append('native'))
    if fault=='authority':expected='0'*64
    if fault=='changed_fbx':next((root/'out').rglob('*.fbx')).write_bytes(b'changed actual bytes')
    if fault=='missing_member':
        del spec['frozen_files'][str(next((root/'out').rglob('*.fbx')))];path.write_text(json.dumps(spec));expected=host.identity(path)['sha256']
    if fault=='failed_source':
        report=root/'source-evidence/current-rope/whole-result.json';report.write_text('{"exit_code":1}')
        spec['frozen_files'][str(report)]=host.identity(report);path.write_text(json.dumps(spec));expected=host.identity(path)['sha256']
    target=tmp_path/'refused'
    with pytest.raises(ValueError):host.reuse_frozen(root,target,tmp_path/'receiving/Content',expected)
    assert not target.exists() and calls==[]


def test_host_finalization_refuses_changed_module_after_real_whole_empty_gate(tmp_path,monkeypatch):
    import json
    runner=host_runner();called=[]
    def bound(name,value):
        path=tmp_path/name;path.write_text(json.dumps(value));return runner.binding(path)
    marker='actual native capture completed'
    stdout=tmp_path/'stdout.log';stdout.write_text(marker)
    evidence=dict(receipt=bound('guard.json',dict(state='child_exited',cleanup_complete=True,processes=[],footprint_bytes=0)),
        stdout=runner.binding(stdout),marker=marker,whole_result=bound('whole.json',dict(exit_code=0)))
    spec=tmp_path/'spec.json';spec.write_text(json.dumps(dict(output=str(tmp_path),native={'module':'bound-original'})))
    monkeypatch.setattr(runner,'unchanged',lambda value:called.append('inputs'))
    monkeypatch.setattr(runner,'strict_cleanup',lambda *args:called.append('cleanup'))
    with pytest.raises(ValueError,match='native modules differ'):
        runner.finalize(spec,spec.read_bytes(),evidence,{'module':'changed'},lambda:called.append('native'))
    assert called==[] and not (tmp_path/'host-result.json').exists()
