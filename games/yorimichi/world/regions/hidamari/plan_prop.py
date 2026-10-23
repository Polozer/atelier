"""Construct one fitted street prop or one conifer LOD, then publish a bounded payload."""
import argparse
from pathlib import Path
import sys
sys.path[:0]=[str(Path(__file__).resolve().parents[2]),str(Path(__file__).resolve().parents[1])]
from atelier.atomic_files import atomic_json
from atelier.export_manifest import real_directory
from atelier.model_files import regular_files
from region_mesh_parts import plan,capture_collision
from treehouse.prop_geometry import fit
from hidamari.prop_parameters import load
from hidamari.prop_lod_geometry import make_lod

OPTIONS=dict(apply_unit_scale=True,apply_scale_options='FBX_SCALE_ALL',axis_forward='-Y',axis_up='Z',
             mesh_smooth_type='FACE',use_custom_props=False,path_mode='STRIP',colors_type='SRGB')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('parameters','source','data','output'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args(argv if argv is not None else sys.argv[sys.argv.index('--')+1:])
    value=load(args.parameters);name=value['name'];parent=value['parent']
    real_directory(args.source.parent)
    if args.source.is_symlink() or not args.source.is_file():raise ValueError('Missing/linked committed prop model')
    root=real_directory(args.data)
    if root.exists() and regular_files(root)-{parent+'.png','record.json'}:raise ValueError('Foreign selected prop data')
    captured={}
    def capture(obj,hulls):captured.update(obj=obj,hulls=hulls)
    _,info=fit(value['slug'],args.source,parent,value['size'],value['turn'],value['target'],value['solid'],root,
        upright=value['upright'],publisher=capture,diagnostic_views=False)
    if value['upright'] and info['crown']>value['crown']*1.02:raise ValueError('Conifer crown exceeds planting clearance')
    obj=captured['obj'];level=[info['triangles'],1.]
    if value['lod']:obj,level=make_lod(obj,info,parent,value['lod'],value['settings'])
    collisions=[capture_collision(hull) for hull in captured['hulls']]
    result=plan(obj,args.output,collisions=collisions,partition='whole',options=OPTIONS)
    if [row['name'] for row in result['pieces']]!=[name]:raise ValueError('Logical prop export changed native membership')
    atomic_json(root/'record.json',dict(schema=1,name=name,parent=parent,lod=value['lod'],level=level,
        info=info,hulls=collisions))
    print('HIDAMARI SELECTED PROP COMPLETE',name,level[0],flush=True)


if __name__=='__main__':main()
