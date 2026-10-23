"""Actual three-owner source/GPU/cooked/bounds/query comparison in exclusive private Content.

Host prepare freezes all inputs. This process runs no Git, subprocess or generator.
NoCollision rope queries stay negative; access retains original complex collision.
Fixture policy does not claim normal fitting, production runtime or package cooking.
"""
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import sys

import unreal

sys.dont_write_bytecode=True
SPEC=Path(os.environ['ATELIER_GONDOLA_NATIVE_SPEC'])
if hashlib.sha256(SPEC.read_bytes()).hexdigest()!=os.environ['ATELIER_GONDOLA_NATIVE_SPEC_SHA256']:
    raise ValueError('Native fixture spec is not byte-bound')
S=json.loads(SPEC.read_text());GAME=Path(S['game']);ROOT=Path(S['out'])/'gondola';ARCHIVE=Path(S['archive'])
sys.path[:0]=[str(GAME/'unreal/Scripts'),str(GAME/'world'),str(GAME/'tools')]
import yori  # noqa: E402
from atelier.atomic_files import atomic_json  # noqa: E402
from atelier.file_copy import copy_file  # noqa: E402
from atelier.export_manifest import real_directory  # noqa: E402
from material_assets import import_texture,node,link,save_material  # noqa: E402
from mesh_materials import assign_materials  # noqa: E402
import mesh_import  # noqa: E402
import gondola_native  # noqa: E402
import atomic_equivalence_capture as capture  # noqa: E402
import atomic_equivalence as eq  # noqa: E402

E=unreal.EditorAssetLibrary
M=unreal.MaterialEditingLibrary
TOOLS=unreal.AssetToolsHelpers.get_asset_tools()
ACTORS=[]


def unchanged(rows):
    for raw,row in rows.items():
        path=Path(raw);real_directory(path.parent)
        if path.is_symlink() or not path.is_file():raise ValueError('Frozen native source is unavailable')
        stat=path.stat()
        actual=dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),stat=[stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns])
        if actual!=row:raise ValueError('Frozen native source changed: '+raw)


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def value(raw):
    if not raw:raise ValueError('Native observer refused unavailable evidence')
    result=json.loads(raw)
    if 'refusal' in result:raise ValueError('Native observer refusal: '+str(result))
    return result


def component(mesh,parent=None,family=None):
    editor=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actor=editor.spawn_actor_from_class(unreal.Actor if parent else unreal.StaticMeshActor,unreal.Vector(0.,0.,0.))
    if not actor:raise ValueError('Cannot create selected owned component')
    ACTORS.append(actor)
    if parent:
        part=unreal.GondolaLogicalMeshComponent.create_evidence_component(actor,mesh,parent,family)
        if not part or not isinstance(part,unreal.GondolaLogicalMeshComponent):raise ValueError('Production logical component unavailable')
    else:
        part=actor.static_mesh_component;part.set_mobility(unreal.ComponentMobility.MOVABLE)
        if not part.set_static_mesh(mesh):raise ValueError('Original fixture mesh unavailable')
        part.set_editor_property('generate_overlap_events',False)
        part.set_collision_object_type(unreal.CollisionChannel.ECC_WORLD_STATIC)
        part.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION if '_Rope_' in mesh.get_name() else unreal.CollisionEnabled.QUERY_AND_PHYSICS)
        if mesh.get_num_lods()==3:part.set_forced_lod_model(1)
    return part


def bounds_equal(before,after,parent,frame=None):
    poses=[unreal.Transform()]
    if frame is not None:
        import math
        origin,along,_,z=frame;yaw=-math.degrees(math.atan2(along[1],along[0]))
        poses.append(unreal.Transform(location=unreal.Vector(origin[0]*100.,-origin[1]*100.,z*100.),rotation=unreal.Rotator(0.,yaw,0.)))
    rows=[]
    for pose in poses:
        for part in [before,*after]:part.set_world_transform(pose,False,False)
        old=value(unreal.NativeAtomicEquivalence.component_policy(before))
        observed=[value(unreal.NativeAtomicEquivalence.component_policy(part)) for part in after]
        if any(row['component_bounds']!=old['component_bounds'] or row['matrix']!=old['matrix'] for row in observed):
            raise ValueError('Original logical box/true sphere/placement differs: '+parent)
        rows.append(dict(original=old['component_bounds'],actual=[row['component_bounds'] for row in observed],matrix=old['matrix']))
    for part in [before,*after]:part.set_world_transform(unreal.Transform(),False,False)
    return rows


def controls(parent,before,after,current_receipt):
    old=[];new=[];seams=[]
    def add(key,kind,query,part):
        old.append(dict(id=key,kind=kind,input=query,target=before.get_path_name()))
        new.append(dict(id=key,kind=kind,input=query,target=part.get_path_name()))
    if parent=='GD_floor_rim_Access':
        ids=[]
        for index,row in enumerate(current_receipt['access_seams']['controls']):
            query=dict(row['input'],channel='Pawn',trace_complex=True)
            if row['capsule']:query.update(radius_cm=.1,half_height_cm=.2,orientation=[0.,0.,0.,1.])
            kind='seam_capsule' if row['capsule'] else 'seam_ray';key=kind+'-'+str(index)
            part=next(part for part in after if part.get_editor_property('static_mesh').get_name()==row['member'])
            add(key,kind,query,part);ids.append(key)
            # Independent positive controls retain the very same observed query, without
            # selecting it by agreement with the original result.
            add('positive-'+str(index),'capsule_positive' if row['capsule'] else 'ray_positive',query,part)
        seams=[dict(a=after[0].get_editor_property('static_mesh').get_path_name(),b=after[1].get_editor_property('static_mesh').get_path_name(),controls=ids)]
    for index,part in enumerate(after):
        page=value(unreal.NativeAtomicEquivalence.snapshot(part.get_editor_property('static_mesh'),parent,0,1,0))
        box=page['bounds'];point=[box[1][axis]+1000. for axis in range(3)]
        for capsule in (False,True):
            query=dict(start=point,end=[point[0]+100.,point[1],point[2]],channel='Pawn',trace_complex=True)
            if capsule:query.update(radius_cm=.1,half_height_cm=.2,orientation=[0.,0.,0.,1.])
            add(('capsule' if capsule else 'ray')+'-negative-'+str(index),'capsule_negative' if capsule else 'ray_negative',query,part)
        if '_Rope_' in parent:
            # Cross an actual native source triangle. The original production
            # NoCollision component MUST still miss, as must each bounded child.
            corners=page['source']['triangles'][0]['corners'];points=[row['position'] for row in corners]
            center=[sum(point[axis] for point in points)/3 for axis in range(3)]
            for capsule in (False,True):
                query=dict(start=[center[0],center[1],center[2]+10.],end=[center[0],center[1],center[2]-10.],channel='Pawn',trace_complex=True)
                if capsule:query.update(radius_cm=.1,half_height_cm=.2,orientation=[0.,0.,0.,1.])
                add(('capsule' if capsule else 'ray')+'-surface-negative-'+str(index),'capsule_negative' if capsule else 'ray_negative',query,part)
    return old,new,seams



def retain_packages(descriptor,root):
    root.mkdir(parents=True)
    bindings=[]
    for row in descriptor['saved_packages']:
        source=Path(row['path']);target=root/(hashlib.sha256(row['path'].encode()).hexdigest()+source.suffix)
        copy_file(source,target)
        if hashlib.sha256(source.read_bytes()).hexdigest()!=row['sha256'] or hashlib.sha256(target.read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('Actual saved native package changed during retention')
        bindings.append(dict(path=str(target),sha256=row['sha256']))
    descriptor['saved_packages']=bindings
    atomic_json(root.parent/'native-descriptor.json',descriptor)
    return descriptor

def compare(before,after,parent):
    original=eq.native_raw_set(before,parent);actual=eq.native_raw_set(after,parent)
    for field in ('source_lods','render_lods','cooked','hulls','settings','source_presence','policy'):
        if original[field]!=actual[field]:raise ValueError('Actual native '+field+' differs: '+parent)
    if parent=='GD_floor_rim_Access':
        count=eq.compare_probes(original['probes'],actual['probes'],parent,set(actual['meshes']),set(original['meshes']),actual['seams'])
    else:
        if actual['seams']:raise ValueError('Rope family unexpectedly creates a source-edge seam')
        left=original['probes']['controls'];right=actual['probes']['controls']
        if not left or len(left)!=len(right):raise ValueError('NoCollision actual query inventory is missing')
        for a,b in zip(left,right):
            if a['hit'] is not None or b['hit'] is not None or not a['kind'].endswith('_negative') or {k:v for k,v in a.items() if k!='target'}!={k:v for k,v in b.items() if k!='target'}:
                raise ValueError('Original rope NoCollision query policy differs')
        for binding in [*before['component_policies'],*after['component_policies']]:
            row=eq.json_artifact(binding)
            if row['collision_enabled']!=0:raise ValueError('Rope fixture changed original NoCollision policy')
        count=len(left)
    return dict(source_gpu_cooked_material_lod_policy_exact=True,actual_controls=count,scope='actual imported native fixture; production runtime and package cook remain separate')


def main():
    """@cc [owner:fontanierh,label:correctness] actual-three-owner-gondola-native-fixture
    Preserve actual original finishing, shaders, collision and every LOD. Compare
    all actual source/GPU/cooked/material fields and complete logical box/sphere.
    Access MUST pass exact original/current positive, negative and seam ray/capsule
    checks. Ropes MUST retain actual NoCollision and only negative controls; never
    enable collision to manufacture a positive result. Fixture scope MUST remain
    distinct from production runtime, normal fitting and package cook acceptance.
    """
    global EDITOR
    if S.get('schema')!=1 or S.get('region')!='gondola-native':raise ValueError('Foreign native spec')
    if any(os.environ.get(name) for name in ('ATELIER_BUILD_TASK','ATELIER_BUILD_GAME','ATELIER_BUILD_SCRIPT','ATELIER_MESH_REUSE_NONCE')):
        raise ValueError('Native fixture must not inherit a build/reuse invocation')
    content=real_directory(Path(unreal.Paths.project_content_dir()).absolute()).resolve()
    if content!=Path(S['content']):raise ValueError('Native receiving Content is not the explicit private owner')
    namespace=S['namespace']
    if not re.fullmatch(r'/Game/AtelierValidation/GondolaAtomicNative_[0-9a-f]{12}',namespace):raise ValueError('Foreign native fixture namespace')
    if os.path.lexists(content/namespace.removeprefix('/Game/')):raise ValueError('Private fixture Content owner root is occupied')
    unchanged(S['source_files']);unchanged(S['frozen_files'])
    if unreal.EditorLoadingAndSavingUtils.new_blank_map(False) is None:raise ValueError('Cannot create private evidence world')
    unreal.SystemLibrary.execute_console_command(None,'Interchange.FeatureFlags.Import.FBX 0')
    unreal.SystemLibrary.execute_console_command(None,'Editor.AsyncStaticMeshCompilation 0')
    unreal.load_module('StaticMeshEditor');EDITOR=unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
    if EDITOR is None:raise ValueError('StaticMeshEditor unavailable')
    yori.OUT=Path(S['out']);yori.GAME=content.parent.parent
    manifest=json.loads((ROOT/'manifest.json').read_text())
    legacy=load('gondola_immutable_mesh_import',ARCHIVE/'mesh_import.py')
    scope=dict(ROOT=ROOT,E=E,M=M,TOOLS=TOOLS,unreal=unreal,import_texture=import_texture,node=node,link=link,save_material=save_material,
               assign_materials=assign_materials,EDITOR=EDITOR,import_mesh=legacy.import_mesh,manifest=manifest,report={})
    exec(compile((ARCHIVE/'material.py').read_text(),str(ARCHIVE/'material.py'),'exec'),scope)
    scope['mats']={name:scope['material'](name,*values,manifest['textured_materials'].get(name)) for name,values in manifest['materials'].items()}
    exec(compile((ARCHIVE/'finish_before.py').read_text(),str(ARCHIVE/'finish_before.py'),'exec'),scope)
    scope['finish_before'](ROOT/'world',namespace+'/Before/World',S['original_names'])
    old={name:E.load_asset(namespace+'/Before/World/'+name) for name in S['original_names']}
    if any(mesh is None for mesh in old.values()):raise ValueError('Original native receiver missing')
    parents={parent:[parent+f'_Piece{index:02d}' for index in range(2)] for parent in S['original_names']}
    site=dict(exports=S['exports'],rope_groups={line:parents['GD_'+line+'_Rope_LOD0'] for line in ('L1','L2')})
    gondola_native.DESTINATION=namespace+'/After/World'
    gondola_native.MATERIAL_DESTINATION=namespace+'/Materials'
    scope.update(import_mesh=mesh_import.import_mesh,gondola_native=gondola_native,site=site,report={})
    exec(compile((ARCHIVE/'finish_after.py').read_text(),str(ARCHIVE/'finish_after.py'),'exec'),scope)
    scope['finish_after'](ROOT/'world',gondola_native.DESTINATION,S['current_names'])
    for parent,names in parents.items():gondola_native.finish_family(parent.removesuffix('_LOD0'),names,3 if '_Rope_' in parent else 1,scope['report'])
    state=dict(current=S['current_names'])
    received=gondola_native.validate_receiving(site,ROOT/'world/atomic-assets',EDITOR,state)
    output=Path(S['output']);output.mkdir();evidence={};frame=json.loads((Path(SPEC).parent/'source-evidence/current-access-rim/results/proof.json').read_text())['station_frame']
    try:
        for parent,names in parents.items():
            before=component(old[parent]);meshes=[E.load_asset(gondola_native.DESTINATION+'/'+name) for name in names]
            family=[mesh.get_path_name() for mesh in meshes]
            after=[component(mesh,parent.removesuffix('_LOD0'),family) for mesh in meshes]
            bounds=bounds_equal(before,after,parent,frame if parent=='GD_floor_rim_Access' else None)
            left,right,seams=controls(parent,before,after,received)
            inputs=[SPEC,*map(Path,S['frozen_files'])]
            baseline=capture.capture([before],parent,output/parent/'before',controls=left,inputs=inputs)
            baseline=retain_packages(baseline,output/parent/'before/packages')
            actual=capture.capture(after,parent,output/parent/'after',controls=right,seams=seams,inputs=inputs)
            actual=retain_packages(actual,output/parent/'after/packages')
            result=compare(baseline,actual,parent);result['logical_bounds_exact']=bounds
            evidence[parent]=result
            atomic_json(output/(parent+'-comparison.json'),result)
            unreal.log('GONDOLA ACTUAL NATIVE EXACT '+parent)
    finally:
        editor=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        for actor in ACTORS:
            if not editor.destroy_actor(actor):raise ValueError('Owned native fixture actor cleanup failed')
    if not E.delete_directory(namespace):raise ValueError('Owned native fixture package cleanup refused')
    remaining=[str(path.relative_to(content)) for path in (content/namespace.removeprefix('/Game/')).rglob('*') if path.is_file()]
    if remaining:raise ValueError('Owned native fixture package files remain after deletion')
    unchanged(S['source_files']);unchanged(S['frozen_files'])
    atomic_json(output/'result.json',dict(schema=1,owners=evidence,scope=S['scope']))
    unreal.log('GONDOLA THREE LARGE OWNER NATIVE FIXTURE COMPLETE')


if __name__=='__main__':main()
