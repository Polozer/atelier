"""Exact two-family source/FBX proof against frozen actual successful production exports.

This never grants current final-ground fitting or Unreal/runtime acceptance.
The source profile and simplification allowances are explicit immutable inputs;
all original emitted source faces/corner attributes and FBX counters must match.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
GAME = HERE.parents[2]; WORLD = GAME / 'world'
sys.path[:0] = [str(HERE),str(WORLD),str(GAME / 'tools')]
import yori  # noqa: E402,F401
import bpy  # noqa: E402
import numpy as np  # noqa: E402
from atelier.atomic_files import atomic_json  # noqa: E402
from atelier.export_manifest import TRIANGLE_LIMIT,sha  # noqa: E402
from commands import Recorder  # noqa: E402
from regions.gondola.site_sources import site_module,cabin_data  # noqa: E402
from regions.gondola.plan_site import construct  # noqa: E402
from region_mesh_parts import plan  # noqa: E402
from regions.gondola.plan_kit import OPTIONS  # noqa: E402
from gondola.parts import component_count,names  # noqa: E402
from gondola.line import stored_groove_audit  # noqa: E402
from export_region_piece import main as export  # noqa: E402
import atomic_equivalence as eq  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profiles',type=Path,required=True)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--kit-queries',type=Path,required=True)
    parser.add_argument('--baseline',type=Path,required=True,
                        help='independent actual original FBX copies bound by the site report')
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args(argv if argv is not None else sys.argv[sys.argv.index('--')+1:])
    if args.profiles.is_symlink() or sha(args.profiles) != args.sha256: raise ValueError('Frozen profile fixture changed')
    source = json.loads(args.profiles.read_text()); S = site_module(); p = dict(S.P.DEFAULTS)
    if source.get('failures')!=[] or {row['id'] for row in source['lines']}!={'L1','L2','L3'}:
        raise ValueError('Actual successful three-line production authority required')
    if source['inputs']['code']['games/yorimichi/world/gondola/line.py']!=sha(WORLD/'gondola/line.py'):
        raise ValueError('Profile authority predates the current production curve source')
    cab = cabin_data(S,args.kit_queries)
    args.output.mkdir(parents=True,exist_ok=True)
    result = {}; native = {}
    for line in source['lines']:
        if line['id']=='L3':continue
        if line['span_audit'].get('pass') is not True or line['span_audit']['groove_max_mm']>2.:
            raise ValueError('Original production contact authority is not accepted')
        profile = np.asarray(line['profile'],float)
        first,last = line['stations']
        A,B = (np.asarray(source['stations'][key]['mouth'],float) for key in (first,last))
        direction = (B-A)/np.linalg.norm(B-A); normal = np.array([-direction[1],direction[0]])
        # This deliberately isolates geometry equivalence. Current production
        # fitting/contact stays in site_sources and the complete site audit.
        families = []
        count = component_count(line['id'])
        for lod,row in enumerate(line['rope_meshes']):
            key = row['name']; tolerance = row['axis_deviation_m']; sides = (12,8,6)[lod]
            baseline = S.solid.Mesh(key); recorder = Recorder(key)
            rings = [];reduced_axes=[]
            for side in (-1,1):
                points = np.c_[A+profile[:,0,None]*direction+side*p['gauge']/2*normal,profile[:,1]]
                reduced = S.simplify(points,tolerance); rings.append(len(reduced))
                reduced_axes.append(reduced)
                baseline.tube(reduced,p['rope_radius'],S.solid.STEEL,n=sides)
                recorder.tube(reduced,p['rope_radius'],S.solid.STEEL,n=sides)
            if baseline.tris()!=row['triangles']:raise ValueError('Current rope source differs from actual production count')
            selected = dict(schema=1,asset=key,commands=recorder.commands,
                            rope_group=dict(line=line['id'],lod=lod,components=count))
            S.solid.closed(baseline)
            obj,_ = S.solid.to_object(baseline,S.solid.make_materials({}))
            original = args.baseline / (key+'.fbx')
            if original.is_symlink() or sha(original)!=row['sha256']:
                raise ValueError('Actual original production FBX identity changed')
            reconstructed = args.output / 'reconstructed' / (key+'.fbx'); reconstructed.parent.mkdir(parents=True,exist_ok=True)
            S.solid.export_fbx([obj],reconstructed); bpy.data.objects.remove(obj,do_unlink=True)
            before,original_triangles=eq.fbx_counter(original)
            reconstructed_fields,reconstructed_triangles=eq.fbx_counter(reconstructed)
            if before!=reconstructed_fields or original_triangles!=reconstructed_triangles:
                raise ValueError(key+': current original constructor differs from actual production FBX')
            obj,query,groups = construct(selected)
            for field in ('verts','faces','mats','parts','fgrain'):
                if json.dumps(getattr(baseline,field)) != json.dumps(query['mesh'][field]):
                    raise ValueError(key+': original source geometry changed: '+field)
            root = args.output / 'plans' / key; root.mkdir(parents=True,exist_ok=True)
            manifest = plan(obj,root,options=OPTIONS,face_groups=groups,partition='explicit')
            if [piece['name'] for piece in manifest['pieces']]!=names(line['id'],lod):
                raise ValueError('Current two-piece LOD family changed')
            full = dict(render=Counter(),collision=Counter()); total = 0; paths = []
            for piece in manifest['pieces']:
                destination = args.output / 'actual' / piece['name']
                export(['--input',str(root / piece['payload']),'--output',str(destination)])
                path = destination / (piece['name']+'.fbx'); paths.append(path)
                values,triangles = eq.fbx_counter(path)
                for channel in full:full[channel].update(values[channel])
                total += triangles
            if full != before or total != original_triangles:raise ValueError(key+': full serialized FBX counters differ')
            stored_contact=None
            if lod == 0:
                # Actual imported control points from all child files retain the old
                # full rope correspondence and centimetre-storage axis calculation.
                axes,contact = S.recovered_rope_axes(baseline,paths,rings)
                if contact['matched_vertices'] != len(baseline.verts):raise ValueError('Rope child readback is incomplete')
                local=[]
                for side,axis in zip((-1,1),axes):
                    delta=axis[:,:2]-A-side*p['gauge']/2*normal
                    local.append(np.c_[delta@direction,delta@normal,axis[:,2]])
                stored_contact=stored_groove_audit(profile,local,cab['cabin'].groove,S.R.RopePath,p['rope_radius'])
                extra=max(float(np.linalg.norm(axis-reduced.astype(np.float32).astype(float),axis=1).max())
                          for axis,reduced in zip(axes,reduced_axes))
                hardware=line['span_audit']['hardware_min_m']-tolerance-extra
                if not stored_contact['pass'] or hardware<.095:
                    raise ValueError('Current split FBX violates original stored contact/hardware gate')
                stored_contact.update(hardware_bound_m=hardware,readback=contact)
            result[key] = dict(source_exact=True,serialized_fbx_exact=True,triangles=total,
                               max_piece_triangles=max(piece['triangles'] for piece in manifest['pieces']),
                               stored_contact=stored_contact,pieces=[piece['name'] for piece in manifest['pieces']])
            families.append(dict(baseline=dict(path=str(original.absolute()),sha256=sha(original)),
                actual=[dict(path=str(path.absolute()),sha256=sha(path)) for path in paths]))
            print('GONDOLA EXACT ROPE GEOMETRY',key,total,len(paths),flush=True)
        native[line['id']] = dict(lods=families)
    if sha(args.profiles) != args.sha256:raise ValueError('Frozen profile fixture changed')
    atomic_json(args.output / 'proof.json',dict(schema=1,profiles_sha256=args.sha256,
        scope='actual successful production FBX vs current source and12 bounded exports; original stored-contact/hardware gates; current full prerequisite fitting and Unreal/runtime acceptance remain separate',
        assets=result,native_fixture=native))
    print('GONDOLA EXACT PROFILE ROPE SOURCE FBX COMPLETE',len(result),flush=True)


if __name__ == '__main__':main()
