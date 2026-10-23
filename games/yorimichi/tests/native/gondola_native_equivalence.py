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

sys.dont_write_bytecode=True
GAME=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(GAME/'unreal/Scripts'),str(GAME/'world'),str(GAME/'tools'),str(Path(__file__).parent)]
import yori  # noqa: E402
from atelier.atomic_files import atomic_json
from atelier.file_copy import copy_file
from atelier.export_manifest import real_directory
from atomic_equivalence_io import require
from track_native_equivalence import (actor_scope,release_actor,retire_owned,assets,fixture_files,receiving_startup)

SPEC=S=ROOT=ARCHIVE=None
ACTORS=[]


def native_imports():
    """Load the actual receiving/import/capture helpers with no host geometry verifier."""
    global unreal,E,M,TOOLS,yori,import_texture,node,link,save_material,assign_materials,mesh_import,gondola_native,capture
    import unreal
    import yori
    from material_assets import import_texture,node,link,save_material
    from mesh_materials import assign_materials
    import mesh_import
    import gondola_native
    import atomic_equivalence_capture as capture
    E=unreal.EditorAssetLibrary;M=unreal.MaterialEditingLibrary;TOOLS=unreal.AssetToolsHelpers.get_asset_tools()


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


def capture_bounds(before,after,parent,frame=None):
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
        rows.append(dict(original=old,actual=observed))
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

def allowed_packages(spec,manifest):
    """Only the finite selected source/material roster authorizes package retirement."""
    root=spec['namespace']
    return ({root+'/Before/World/'+name for name in spec['original_names']} |
            {root+'/After/World/'+name for name in spec['current_names']} |
            {root+'/Materials/'+name for name in manifest['materials']} |
            {root+'/Textures/GD_'+texture+'_'+channel for texture in set(manifest['textured_materials'].values())
             if texture for channel in ('color','rough')})


def run_native(spec_path,spec_sha):
    """@cc [owner:fontanierh,label:correctness] actual-three-owner-gondola-native-fixture
    Preserve actual original finishing, shaders, collision and every LOD. Emit
    complete actual source/GPU/cooked/material and logical box/sphere evidence.
    The HOST MUST compare it after whole0/empty; embedded code MUST NOT import
    the host geometry verifier, NumPy or mesh IR. Recorded actors and owned
    packages MUST use strict detach/destroy and complete referencer preflight.
    Access MUST pass exact original/current positive, negative and seam ray/capsule
    checks. Ropes MUST retain actual NoCollision and only negative controls; never
    enable collision to manufacture a positive result. Fixture scope MUST remain
    distinct from production runtime, normal fitting and package cook acceptance.
    """
    global EDITOR,SPEC,S,ROOT,ARCHIVE,ACTORS
    sys.dont_write_bytecode=True
    SPEC=Path(spec_path).absolute();payload=SPEC.read_bytes()
    require(hashlib.sha256(payload).hexdigest()==spec_sha,'Native fixture spec is not byte-bound')
    S=json.loads(payload);ROOT=Path(S['out'])/'gondola';ARCHIVE=Path(S['archive']);ACTORS=[]
    native_imports()
    if S.get('schema')!=2 or S.get('region')!='gondola-native':raise ValueError('Foreign native spec')
    if any(os.environ.get(name) for name in ('ATELIER_BUILD_TASK','ATELIER_BUILD_GAME','ATELIER_BUILD_SCRIPT','ATELIER_MESH_REUSE_NONCE')):
        raise ValueError('Native fixture must not inherit a build/reuse invocation')
    content=real_directory(Path(unreal.Paths.project_content_dir()).absolute()).resolve()
    if content!=Path(S['content']):raise ValueError('Native receiving Content is not the explicit private owner')
    namespace=S['namespace']
    if not re.fullmatch(r'/Game/AtelierValidation/GondolaAtomicNative_[0-9a-f]{12}',namespace):raise ValueError('Foreign native fixture namespace')
    if os.path.lexists(content/namespace.removeprefix('/Game/')):raise ValueError('Private fixture Content owner root is occupied')
    unchanged(S['source_files']);unchanged(S['frozen_files'])
    startup=receiving_startup(S,unreal)
    if unreal.EditorLoadingAndSavingUtils.new_blank_map(False) is None:raise ValueError('Cannot create private evidence world')
    unreal.SystemLibrary.execute_console_command(None,'Interchange.FeatureFlags.Import.FBX 0')
    unreal.SystemLibrary.execute_console_command(None,'Editor.AsyncStaticMeshCompilation 0')
    unreal.SystemLibrary.execute_console_command(None,'MessageLog.DisablePopup 1')
    require(unreal.SystemLibrary.get_console_variable_int_value('MessageLog.DisablePopup')==1,'Import modal notification suppression unavailable')
    unreal.load_module('StaticMeshEditor');EDITOR=unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
    if EDITOR is None:raise ValueError('StaticMeshEditor unavailable')
    yori.OUT=Path(S['out']);yori.GAME=content.parent.parent
    output=real_directory(Path(S['output']).absolute())
    require(output.is_dir(),'Missing prepared private Gondola output')
    atomic_json(output/'startup-ddc.json',startup)
    actor_editor=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    require(actor_editor is not None,'Missing owned actor subsystem')
    partial=lambda:dict(package=S['namespace'],observed_packages=sorted(assets(E,S['namespace'])))
    with actor_scope(ACTORS,actor_editor,unreal.StaticMeshComponent,output,partial):
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
        frame=json.loads((Path(SPEC).parent/'source-evidence/current-access-rim/results/proof.json').read_text())['station_frame']
        evidence={}
        for parent,names in parents.items():
            before=component(old[parent]);meshes=[E.load_asset(gondola_native.DESTINATION+'/'+name) for name in names]
            family=[mesh.get_path_name() for mesh in meshes]
            after=[component(mesh,parent.removesuffix('_LOD0'),family) for mesh in meshes]
            bounds=capture_bounds(before,after,parent,frame if parent=='GD_floor_rim_Access' else None)
            left,right,seams=controls(parent,before,after,received)
            inputs=[SPEC,*map(Path,S['frozen_files'])]
            baseline=capture.capture([before],parent,output/parent/'before',controls=left,inputs=inputs)
            baseline=retain_packages(baseline,output/parent/'before/packages')
            actual=capture.capture(after,parent,output/parent/'after',controls=right,seams=seams,inputs=inputs)
            actual=retain_packages(actual,output/parent/'after/packages')
            evidence[parent]=dict(before=baseline,after=actual,bounds_observations=bounds)
            atomic_json(output/'native.json',evidence)
            for actor in tuple(ACTORS):release_actor(actor,actor_editor,unreal.StaticMeshComponent,ACTORS)
            before=after=meshes=family=actor=None
            unreal.log('GONDOLA ACTUAL NATIVE CAPTURED '+parent)
        allowed=allowed_packages(S,manifest)
        require(assets(E,namespace)==allowed,'Foreign or incomplete Gondola fixture package membership')
        scope.clear();old.clear();scope=old=None
        import gc
        gc.collect();unreal.SystemLibrary.collect_garbage()
        retire_owned(unreal,allowed,allowed)
        require(not assets(E,namespace),'Gondola fixture registry is not empty')
        remaining=fixture_files(content/namespace.removeprefix('/Game/'),allowed,namespace)
        atomic_json(output/'cleanup.json',dict(root=str(content/namespace.removeprefix('/Game/')),
            remaining=remaining,allowed_packages=sorted(allowed)))
        unchanged(S['source_files']);unchanged(S['frozen_files'])
        require(SPEC.read_bytes()==payload,'Gondola native spec changed')
    unreal.log('GONDOLA THREE LARGE OWNER NATIVE CAPTURE COMPLETE '+spec_sha)


def main():
    run_native(Path(os.environ['ATELIER_GONDOLA_NATIVE_SPEC']),os.environ['ATELIER_GONDOLA_NATIVE_SPEC_SHA256'])


if __name__=='__main__':main()
