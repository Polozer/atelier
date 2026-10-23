"""Exact fitted Gondola receiving membership and native three-LOD logical bounds."""
import json
import hashlib
from pathlib import Path
import re

import unreal
from atelier import native_membership
from atelier.export_manifest import real_directory

DESTINATION = '/Game/Gondola/World'
MATERIAL_DESTINATION = '/Game/Gondola/Materials'
LOD_PROOF = 'Gondola.SourceLods.v1'


def lod_geometry(mesh,name,lod):
    """Read actual source/render/cooked fields; missing evidence cannot certify reuse."""
    count=mesh.get_num_triangles(lod)
    if not 0<count<=32768:return None
    digest=hashlib.sha256()
    for first in range(0,count,4096):
        raw=unreal.NativeAtomicEquivalence.snapshot(mesh,name,first,min(4096,count-first),lod)
        if not raw:return None
        row=json.loads(raw)
        if (row.get('schema')!=1 or row.get('source_available') is not True
                or row.get('source_count')!=count or row.get('render_count')!=count):return None
        fields={key:row[key] for key in ('source','render','cooked')}
        digest.update(json.dumps(fields,sort_keys=True,separators=(',',':')).encode())
    return digest.hexdigest()


def import_lods(mesh,name,folder,editor):
    """@cc [owner:fontanierh,label:correctness] gondola-source-lod-binding-reuse
    An already-equal validated LOD source binding MUST NOT be reassigned solely
    to finish an owner. Reuse MUST bind current source bytes, actual source-model
    filenames and actual saved/render/cooked geometry; a filename, metadata hint
    or package existence alone MUST NOT certify it. Misses use the original LOD
    importer and verify its resulting source binding before recording evidence.
    """
    value=unreal.EditorAssetLibrary.get_metadata_tag(mesh,LOD_PROOF)
    prior=json.loads(value) if value else {}
    current={}
    for lod in (1,2):
        path=Path(folder)/(name.replace('_LOD0',f'_LOD{lod}')+'.fbx')
        real_directory(path.parent)
        if path.is_symlink() or not path.is_file():raise ValueError('Missing actual Gondola LOD source')
        source=str(path.resolve());source_sha=hashlib.sha256(path.read_bytes()).hexdigest()
        actual=unreal.GondolaLogicalMeshComponent.rope_lod_source(mesh,lod)
        geometry=lod_geometry(mesh,name,lod) if mesh.get_num_lods()>lod else None
        entry=dict(source=source,sha256=source_sha,geometry=geometry)
        if not geometry or not actual or Path(actual).resolve()!=path.resolve() or prior.get(str(lod))!=entry:
            if editor.import_lod(mesh,lod,str(path))!=lod:raise ValueError(name+': failed original rope LOD import')
            actual=unreal.GondolaLogicalMeshComponent.rope_lod_source(mesh,lod)
            geometry=lod_geometry(mesh,name,lod)
            if not geometry or not actual or Path(actual).resolve()!=path.resolve():
                raise ValueError('Gondola actual source LOD evidence unavailable after import')
            entry['geometry']=geometry
        current[str(lod)]=entry
    if mesh.get_num_lods()!=3:raise ValueError('Incomplete original Gondola authored LOD membership')
    text=json.dumps(current,sort_keys=True,separators=(',',':'))
    if text!=value:unreal.EditorAssetLibrary.set_metadata_tag(mesh,LOD_PROOF,text)


def configure(site):
    if site.get('atomic') is not True: raise ValueError('Native Gondola requires bounded source membership')
    current = [piece['name'] for row in site['exports'] for piece in row['pieces']
               if not any(token in piece['name'] for token in ('_Rope_LOD1','_Rope_LOD2'))]
    if not current or len(current) != len(set(current)): raise ValueError('Incomplete native Gondola membership')
    previous = native_membership.inventory(unreal.EditorAssetLibrary,DESTINATION,'GD_')
    logical = {row['name'] for row in site['exports'] if not any(token in row['name'] for token in ('_Rope_LOD1','_Rope_LOD2'))}
    for package in previous:
        key = package.rsplit('/',1)[-1]
        if key not in logical and key not in current and not re.fullmatch(r'GD_(?:L[12]_Rope_LOD0|floor_rim_Access)_Piece0[01]',key):
            raise ValueError('Foreign Gondola world member prevents retirement: '+key)
    return dict(previous=previous,current=current)


def finish_family(parent,names,lods,report):
    parts=[unreal.EditorAssetLibrary.load_asset(DESTINATION+'/'+name) for name in names]
    if len(parts)!=2 or any(part is None or part.get_num_lods()!=lods for part in parts):
        raise ValueError('Incomplete declared native Gondola family')
    result=unreal.GondolaLogicalMeshComponent.finish_logical_family(parent,parts)
    if not result:raise ValueError('Actual native Gondola logical bounds are unavailable')
    value=json.loads(result)
    if set(value)!={'origin','extent','sphere_radius'}:raise ValueError('Incomplete native Gondola logical sphere')
    for name,mesh in zip(names,parts):
        if not unreal.EditorAssetLibrary.save_loaded_asset(mesh,only_if_is_dirty=True):raise ValueError('Gondola family package save failed: '+name)
        report[name]['logical_bounds']=value
    return value


def finish_families(site,report):
    """Retain original source-LOD finishing; measure only actual final native buffers."""
    bounds = {}
    for line in site['lines']:
        names = site['rope_groups'][line['id']]
        parts = [unreal.EditorAssetLibrary.load_asset(DESTINATION+'/'+name) for name in names]
        if not parts or any(part is None or part.get_num_lods() != 3 for part in parts):
            raise ValueError('Incomplete native Gondola three-LOD rope family')
        expected = 2 if line['id'] in ('L1','L2') else 1
        if len(parts) != expected: raise ValueError('Current Gondola physical rope family changed')
        if expected == 1:
            if names != ['GD_L3_Rope_LOD0']:raise ValueError('Whole L3 rope identity changed')
            continue
        bounds[line['id']] = finish_family('GD_'+line['id']+'_Rope',names,3,report)
    access=next(row for row in site['exports'] if row['name']=='GD_floor_rim_Access')
    bounds[access['name']]=finish_family(access['name'],[row['name'] for row in access['pieces']],1,report)
    return bounds


def retire(state):
    if state.get('validated_current')!=tuple(sorted(state['current'])):
        raise ValueError('Complete current Gondola receiving validation is required before retirement')
    removed = native_membership.retire(unreal.EditorAssetLibrary,state['previous'],state['current'],DESTINATION,'GD_')
    folder = Path(unreal.Paths.project_content_dir()) / 'Gondola/World'
    real_directory(folder)
    obsolete = state['previous'] - {DESTINATION+'/'+key for key in state['current']}
    if any(list(folder.glob(package.rsplit('/',1)[-1]+'.*')) for package in obsolete):
        raise ValueError('Retired Gondola native package remains on disk')
    return removed


def native_pages(mesh,name,lod,count):
    """Validate complete current saved/source/GPU/cooked pages, retaining bounded seam positions."""
    digest=hashlib.sha256();triangles=[];initial=None
    for first in range(0,count,4096):
        text=unreal.NativeAtomicEquivalence.snapshot(mesh,name,first,min(4096,count-first),lod)
        if not text:raise ValueError('Missing actual Gondola native geometry')
        page=json.loads(text,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite native data')))
        if (page.get('schema')!=1 or page.get('source_available') is not True or page.get('source_count')!=count
                or page.get('render_count')!=count or page.get('first')!=first or page.get('lod')!=lod):
            raise ValueError('Incomplete current Gondola native LOD')
        common={key:page[key] for key in ('source_count','render_count','cooked_count','slots','settings','bounds')}
        if initial is None:initial=common
        if initial!=common:raise ValueError('Gondola native geometry changed during validation')
        expected=min(4096,count-first)
        for channel in ('source','render','cooked'):
            value=page[channel];rows=value['triangles'] if isinstance(value,dict) else value
            number=page['cooked_count'] if channel=='cooked' else count
            if not isinstance(rows,list) or len(rows)!=max(0,min(expected,number-first)):
                raise ValueError('Incomplete current Gondola native channel: '+channel)
            digest.update(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
        if lod==0:
            for triangle in page['source']['triangles']:
                corners=triangle['corners']
                if len(corners)!=3:raise ValueError('Invalid current native source triangle')
                triangles.append([tuple(corner['position']) for corner in corners])
    if initial is None:raise ValueError('Empty current Gondola native LOD')
    return dict(sha256=digest.hexdigest(),header=initial,triangles=triangles)


def validate_access_seams(parts,geometry):
    """Check both neighbors of actual cross-owned native source edges with real Pawn queries."""
    import math
    edges={}
    for name,triangles in geometry.items():
        for triangle in triangles:
            for a,b in zip(triangle,triangle[1:]+triangle[:1]):
                if a!=b:edges.setdefault(tuple(sorted((a,b))),{}).setdefault(name,triangle)
    seams=[(edge,owners) for edge,owners in edges.items() if len(owners)>1]
    if not seams:raise ValueError('Split access has no actual shared native source boundary')
    actors=[];components={};editor=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    def probe(component,value,capsule):
        raw=unreal.NativeAtomicEquivalence.probe(component,unreal.Vector(*value['start']),unreal.Vector(*value['end']),
            unreal.Quat(0.,0.,0.,1.),.1 if capsule else 0.,.2 if capsule else 0.,True)
        if not raw:raise ValueError('Missing actual access collision query')
        row=json.loads(raw)
        if 'refusal' in row or row.get('query_channel')!='Pawn' or row.get('selected_component') is not True:
            raise ValueError('Actual access selected-component query refused')
        return row
    controls=[]
    try:
        for name,mesh in parts.items():
            actor=editor.spawn_actor_from_class(unreal.StaticMeshActor,unreal.Vector(0.,0.,0.))
            if not actor:raise ValueError('Cannot create owned access receiving control')
            actors.append(actor);component=actor.static_mesh_component
            component.set_mobility(unreal.ComponentMobility.MOVABLE)
            if not component.set_static_mesh(mesh):raise ValueError('Missing owned access control mesh')
            component.set_collision_enabled(unreal.CollisionEnabled.QUERY_AND_PHYSICS)
            component.set_collision_object_type(unreal.CollisionChannel.ECC_WORLD_STATIC)
            component.set_editor_property('generate_overlap_events',False)
            components[name]=component
        for name,component in components.items():
            for capsule in (False,True):
                accepted=None
                for edge,owners in seams:
                    if name not in owners:continue
                    triangle=owners[name];a,b,c=triangle
                    u=[b[i]-a[i] for i in range(3)];v=[c[i]-a[i] for i in range(3)]
                    normal=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
                    length=math.sqrt(sum(value*value for value in normal))
                    if length==0:raise ValueError('Degenerate native access seam face')
                    normal=[value/length for value in normal]
                    center=[sum(point[i] for point in triangle)/3 for i in range(3)]
                    midpoint=[sum(point[i] for point in edge)/2 for i in range(3)]
                    for mix in (.01,.1,.5):
                        point=[midpoint[i]*(1-mix)+center[i]*mix for i in range(3)]
                        for direction in (1.,-1.):
                            value=dict(start=[p+direction*n for p,n in zip(point,normal)],
                                       end=[p-direction*n for p,n in zip(point,normal)])
                            hits={key:probe(part,value,capsule) for key,part in components.items()}
                            hit=hits[name]
                            if hit.get('blocking') is not True:continue
                            nearest=min(row['distance'] for row in hits.values() if row.get('blocking') is True)
                            if hit['distance']!=nearest:continue
                            visible={json.dumps({key:row[key] for key in ('position','normal','distance')},sort_keys=True)
                                     for row in hits.values() if row.get('blocking') is True and row['distance']==nearest}
                            if len(visible)!=1:continue
                            accepted=dict(member=name,capsule=capsule,input=value,observed=hit);break
                        if accepted is not None:break
                    if accepted is not None:break
                if accepted is None:raise ValueError('No positive current access seam neighbor collision control')
                controls.append(accepted)
        return dict(cross_owned_edges=len(seams),controls=controls)
    finally:
        for actor in actors:
            if not editor.destroy_actor(actor):raise ValueError('Owned access control cleanup failed')


def validate_receiving(site,folder,editor,state):
    """@cc [owner:fontanierh,label:correctness] current-gondola-receiving-before-retirement
    Before retirement, validate EVERY current physical member against its owned source
    file and source triangle/material/LOD inventory, actual native source/GPU/cooked
    pages and collision policy. Both access boundary neighbors MUST have positive
    actual ray/capsule controls. Missing native/query data MUST refuse. This current
    validation MUST work on a fresh clone without historic assets or private reports.
    Independent original/current native equivalence remains separate merge evidence.
    """
    folder=Path(folder);rows={piece['name']:(row,piece) for row in site['exports'] for piece in row['pieces']}
    result={};access_parts={};access_geometry={}
    for name in state['current']:
        row,piece=rows[name];mesh=unreal.EditorAssetLibrary.load_asset(DESTINATION+'/'+name)
        rope='_Rope_LOD0' in name;lods=3 if rope else 1
        if mesh is None or mesh.get_num_lods()!=lods:raise ValueError('Incomplete current Gondola receiver: '+name)
        source=folder/(name+'.fbx')
        if source.is_symlink() or not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=piece['sha256']:
            raise ValueError('Current base source bytes differ from audited assembly')
        filenames=list(mesh.get_editor_property('asset_import_data').extract_filenames())
        if not filenames or Path(filenames[0]).resolve()!=source.resolve():raise ValueError('Current base FBX binding differs')
        if editor.get_convex_collision_count(mesh)!=0:raise ValueError('Invented Gondola world collision hull')
        if not rope and mesh.get_editor_property('body_setup').get_editor_property('collision_trace_flag')!=unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE:
            raise ValueError('Current Gondola static owner lost original complex collision')
        digests=[]
        for lod in range(lods):
            key=name.replace('_LOD0',f'_LOD{lod}') if rope else name
            logical,member=rows[key];count=member['triangles']
            lod_source=folder/(key+'.fbx')
            if lod_source.is_symlink() or not lod_source.is_file() or hashlib.sha256(lod_source.read_bytes()).hexdigest()!=member['sha256']:
                raise ValueError('Current source LOD bytes differ from audited assembly')
            if lod and Path(unreal.GondolaLogicalMeshComponent.rope_lod_source(mesh,lod)).resolve()!=lod_source.resolve():
                raise ValueError('Current source LOD binding changed after finishing')
            if not 0<count<=32768 or mesh.get_num_triangles(lod)!=count:raise ValueError('Current native source triangle count differs')
            value=native_pages(mesh,name,lod,count);header=value['header'];digests.append(value['sha256'])
            if lod==0 and header['cooked_count']!=count:raise ValueError('Incomplete actual Gondola LOD0 triangle collision cook')
            slots=header['slots'];allowed=set(logical['materials'])
            if (not slots or any(slot['name'] not in allowed or slot['material']!=
                    MATERIAL_DESTINATION+'/'+slot['name']+'.'+slot['name'] for slot in slots)):
                raise ValueError('Current Gondola native material binding differs')
            if row['name']=='GD_floor_rim_Access':access_geometry[name]=value['triangles']
            unreal.log('GONDOLA NATIVE VALIDATED '+name+' LOD'+str(lod)+' '+str(count))
        result[name]=dict(geometry=digests,lod_screen_sizes=list(editor.get_lod_screen_sizes(mesh)))
        if len(result[name]['lod_screen_sizes'])!=lods:raise ValueError('Incomplete actual Gondola LOD screen-size inventory')
        if row['name']=='GD_floor_rim_Access':access_parts[name]=mesh
    for line in ('L1','L2'):
        names=site['rope_groups'][line]
        if result[names[0]]['lod_screen_sizes']!=result[names[1]]['lod_screen_sizes']:
            raise ValueError('Gondola coordinated children changed native LOD screen-size policy')
    seams=validate_access_seams(access_parts,access_geometry)
    state['validated_current']=tuple(sorted(result))
    return dict(members=result,access_seams=seams)
