"""Exact fitted Gondola receiving membership and native three-LOD logical bounds."""
import json
import hashlib
from pathlib import Path
import re

import unreal
from atelier import native_membership
from atelier.export_manifest import real_directory

DESTINATION = '/Game/Gondola/World'
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
    removed = native_membership.retire(unreal.EditorAssetLibrary,state['previous'],state['current'],DESTINATION,'GD_')
    folder = Path(unreal.Paths.project_content_dir()) / 'Gondola/World'
    real_directory(folder)
    obsolete = state['previous'] - {DESTINATION+'/'+key for key in state['current']}
    if any(list(folder.glob(package.rsplit('/',1)[-1]+'.*')) for package in obsolete):
        raise ValueError('Retired Gondola native package remains on disk')
    return removed
