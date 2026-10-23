"""Freeze the three proved Gondola owners for an isolated actual native comparison.

Host only: local immutable Git extraction, independent copies and SHA/stat checks.
No constructor, Blender, Unreal, stamp transfer or mutable project sharing runs here.
"""
import argparse
import ast
import copy
import hashlib
import json
import os
import sys
from pathlib import Path
import subprocess
import uuid
from collections import Counter

from atelier.atomic_files import atomic_json
from atelier.file_copy import copy_file
from atelier.export_manifest import real_directory,validate

GAME=Path(__file__).resolve().parents[2]
REPO=GAME.parents[1]
ORIGINAL='90d7a918f922d2e79910d8b79289443b53168f5b'
PARENTS=('GD_L1_Rope_LOD0','GD_L2_Rope_LOD0','GD_floor_rim_Access')


def identity(path):
    real_directory(path.parent)
    if path.is_symlink() or not path.is_file():raise ValueError('Regular immutable fixture input required')
    stat=path.stat()
    return dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),stat=[stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns])


def archived(relative):
    return subprocess.check_output(['git','show',ORIGINAL+':'+relative],cwd=REPO)


def finishing(source,function):
    tree=ast.parse(source)
    loop=next(node for node in tree.body if isinstance(node,ast.For) and isinstance(node.target,ast.Tuple)
              and [item.id for item in node.target.elts]==['folder','dest','names'])
    wrapper=ast.parse('def '+function+'(folder,dest,names):\n    pass\n').body[0]
    wrapper.body=copy.deepcopy(loop.body)
    return ast.unparse(ast.fix_missing_locations(wrapper))+'\n'



def material_namespace(source,prefix):
    """Map only the four package literals; reversing MUST restore the immutable AST."""
    expected=Counter({'/Game/Gondola/Materials/':1,'/Game/Gondola/Materials':1,'/Game/Gondola/Textures':2})
    tree=ast.parse(source);seen=Counter();reverse={}
    for node in ast.walk(tree):
        if isinstance(node,ast.Constant) and isinstance(node.value,str) and node.value in expected:
            old=node.value;seen[old]+=1;node.value=prefix+old.removeprefix('/Game/Gondola');reverse[node.value]=old
    if seen!=expected:raise ValueError('Original material namespace literals changed')
    rendered=ast.unparse(tree)+'\n';restored=ast.parse(rendered)
    for node in ast.walk(restored):
        if isinstance(node,ast.Constant) and isinstance(node.value,str) and node.value in reverse:node.value=reverse[node.value]
    if ast.dump(restored,include_attributes=False)!=ast.dump(ast.parse(source),include_attributes=False):
        raise ValueError('Material namespace mapping changed the original graph body')
    return rendered


def run(output):
    """Use a current normal compiled module and ordinary full guard; never build or repair it here."""
    from atelier import build
    from atelier.harness.safety import guarded
    output=real_directory(output.absolute());specfile=output/'spec.json';payload=specfile.read_bytes();spec=json.loads(payload)
    def bindings():
        for field in ('source_files','frozen_files'):
            for name,row in spec[field].items():
                if identity(Path(name))!=row:raise ValueError('Prepared native input changed')
    if subprocess.check_output(['git','status','--porcelain'],cwd=REPO):raise ValueError('Freeze the source checkout before native execution')
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO).decode().strip();bindings()
    ctx=build.Context('yorimichi')
    if ctx.game_dir!=Path(spec['game']):raise ValueError('Run from the prepared receiving checkout environment')
    sys.path.insert(0,str(ctx.game_dir/'tools'))
    from network_review_common import current_native_build
    native=current_native_build(ctx)
    command=build.UnrealScript(Path(__file__).with_name('gondola_native_equivalence.py'),
        'GONDOLA THREE LARGE OWNER NATIVE FIXTURE COMPLETE',null_rhi=True,modules=('Yorimichi',),args=('-nosound','-noshaderworker'))
    with command.prepared(ctx) as (argv,overrides):
        env=dict(ctx.env(),**dict(overrides),ATELIER_GONDOLA_NATIVE_SPEC=str(specfile),
                 ATELIER_GONDOLA_NATIVE_SPEC_SHA256=hashlib.sha256(payload).hexdigest(),ATELIER_BUILD_ROOT=str(output/'native-build'))
        code=guarded.run(argv,output/'guard',timeout=1200,queue_seconds=1800,limit_gib=10.,kind='job',
            purpose='Gondola three large owner exact native fixture',env=env,progress=25.,track_tree=True)
    atomic_json(output/'whole-result.json',dict(exit_code=code,head=head,native=native))
    if code:raise SystemExit(code)
    guard=json.loads((output/'guard/memory-health-tree.json').read_text())
    if (guard.get('state')!='child_exited' or guard.get('cleanup_complete') is not True or guard.get('processes')!=[] or guard.get('footprint_bytes')!=0
            or guard.get('late_reporters',{}).get('unresolved')):raise ValueError('Native fixture cleanup is not positively empty')
    if command.marker not in (output/'guard/stdout.log').read_text():raise ValueError('Native fixture completion marker is absent')
    bindings()
    if (specfile.read_bytes()!=payload or subprocess.check_output(['git','status','--porcelain'],cwd=REPO)
            or subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO).decode().strip()!=head or current_native_build(ctx)!=native):
        raise ValueError('Native source/spec/module changed during execution')
    print('GONDOLA ACTUAL NATIVE FIXTURE WHOLE/EMPTY COMPLETE; normal fitting/runtime/package cook remain separate',flush=True)

def main(argv=None):
    """@cc [owner:fontanierh,label:correctness] frozen-three-owner-gondola-native-inputs
    Native fixture inputs MUST be independent copies bound to actual successful
    source/export whole/empty proofs and immutable original native finishing code.
    Extract only selected-owner loop bodies without changing their native actions.
    This host preparation MUST NOT execute a constructor or import a native tool.
    """
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--proofs',type=Path)
    parser.add_argument('--kit',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--content',type=Path)
    args=parser.parse_args(argv)
    if args.run:return run(args.output)
    if any(value is None for value in (args.proofs,args.kit,args.content)):parser.error('Preparation requires proofs, kit and explicit receiving Content')
    if args.output.exists() or args.output.is_symlink():raise ValueError('Fresh exclusive fixture output required')
    args.output.mkdir(parents=True);output=args.output.resolve();stage=output/'out/gondola';archive=output/'archive'
    archive.mkdir();frozen={};sources={}
    namespace='/Game/AtelierValidation/GondolaAtomicNative_'+uuid.uuid4().hex[:12]
    def retain(path,target,expected=None):
        real_directory(path.absolute().parent)
        if path.is_symlink():raise ValueError('Linked fixture input')
        path=path.resolve();before=identity(path)
        if expected is not None and before['sha256']!=expected:raise ValueError('Input differs from actual proof authority')
        copy_file(path,target)
        if identity(path)!=before or identity(target)['sha256']!=before['sha256']:raise ValueError('Fixture copy input changed')
        sources[str(path)]=before;frozen[str(target)]=identity(target)
        return str(target)
    proofs=args.proofs.resolve();profile=proofs/'current-production-baseline/site.json';site=json.loads(profile.read_text())
    profile_sha=identity(profile)['sha256']
    if profile_sha!='9fd42d53c8317356166e5a0f48b49da5e46d372cab40eb9a3ea8ec5fc2c38242' or site.get('failures')!=[]:
        raise ValueError('Actual successful current production authority required')
    fixtures={};expected_actual=set()
    for kind in ('current-rope','current-access-rim'):
        root=proofs/kind;whole=json.loads((root/'whole-result.json').read_text());guard=json.loads((root/'guard/memory-health-tree.json').read_text())
        if (whole.get('exit_code')!=0 or whole.get('source_and_fixture_unchanged') is not True or
                guard.get('state')!='child_exited' or guard.get('cleanup_complete') is not True or guard.get('processes')!=[] or guard.get('footprint_bytes')!=0):
            raise ValueError('Source/export proof lacks successful whole and empty guard')
        report=json.loads((root/'results/proof.json').read_text())
        for name in ('whole-result.json','inputs.json','guard/memory-health-tree.json','results/proof.json'):
            retain(root/name,output/'source-evidence'/kind/name)
        if kind=='current-rope':
            if report.get('profiles_sha256')!=profile_sha or len(report.get('assets',{}))!=6:raise ValueError('Incomplete two-family source proof')
            for line in ('L1','L2'):
                family=report['native_fixture'][line];parent='GD_'+line+'_Rope_LOD0';fixtures[parent]=family
                for lod,pair in enumerate(family['lods']):
                    row=report['assets'][parent.replace('_LOD0',f'_LOD{lod}')]
                    if not row['source_exact'] or not row['serialized_fbx_exact'] or row['max_piece_triangles']>32768:raise ValueError('Unproved bounded rope export')
                    if lod==0 and row['stored_contact'].get('pass') is not True:raise ValueError('Original contact gate failed')
        else:
            if not report.get('source_exact') or not report.get('actual_serialized_fbx_exact') or report['max_piece_triangles']>32768 or len(report['seams'])!=8:
                raise ValueError('Unproved bounded access source boundary')
            fixtures['GD_floor_rim_Access']=dict(lods=[report['native_fixture']],station_frame=report['station_frame'])
    originals={row['name']:row for line in site['lines'] for row in line['rope_meshes']}
    originals['GD_floor_rim_Access']=site['stations']['floor_rim']['access_mesh']
    exports=[]
    for parent,family in fixtures.items():
        for lod,pair in enumerate(family['lods']):
            key=parent.replace('_LOD0',f'_LOD{lod}')
            original=Path(pair['baseline']['path']);retain(original,stage/'world/assets'/(key+'.fbx'),pair['baseline']['sha256'])
            pieces=[]
            for index,row in enumerate(pair['actual']):
                path=Path(row['path']);name=key+f'_Piece{index:02d}'
                if path.stem!=name:raise ValueError('Current physical family identity changed')
                receipt=validate(path.parent,key=name)
                if receipt['sha256']!=row['sha256']:raise ValueError('Actual export receipt differs from proof')
                pieces.append(dict(name=name,sha256=row['sha256'],triangles=receipt['triangles']))
                retain(path,stage/'world/atomic-assets'/(name+'.fbx'),row['sha256']);expected_actual.add(name)
            if sum(row['triangles'] for row in pieces)!=originals[key]['triangles']:raise ValueError('Original/current source triangle roster differs')
            exports.append(dict(name=key,materials=originals[key]['materials'],pieces=pieces))
    kit_manifest=args.kit/'manifest.json'
    retain(kit_manifest,stage/'manifest.json',site['inputs']['kit']['manifest.json'])
    for name,digest in site['inputs']['kit'].items():
        if name.startswith('textures/'):retain(args.kit/name,stage/name,digest)
    retain(profile,output/'site.json',profile_sha)
    scripts=GAME/'unreal/Scripts';old=archived('games/yorimichi/unreal/Scripts/import_gondola.py').decode()
    current=(scripts/'import_gondola.py').read_text()
    material=lambda source:next(node for node in ast.parse(source).body if isinstance(node,ast.FunctionDef) and node.name=='material')
    if ast.dump(material(old),include_attributes=False)!=ast.dump(material(current),include_attributes=False):raise ValueError('Original/current shader constructor differs')
    for name in ('mesh_import.py','import_gondola.py'):
        path=archive/name;data=archived('games/yorimichi/unreal/Scripts/'+name)
        if hashlib.sha256(data).hexdigest()!=site['inputs']['code']['games/yorimichi/unreal/Scripts/'+name]:
            raise ValueError('Archived native source differs from actual successful authority')
        path.write_bytes(data);frozen[str(path)]=identity(path)
    for name,value in (('material.py',material_namespace(ast.unparse(material(old))+'\n',namespace)),('finish_before.py',finishing(old,'finish_before')),
                       ('finish_after.py',finishing(current,'finish_after'))):
        path=archive/name;path.write_text(value);frozen[str(path)]=identity(path)
    for directory in (GAME/'world/gondola',GAME/'world/regions/gondola',GAME/'assets/vehicles/gondola'):
        for path in directory.glob('*.py'):sources[str(path)]=identity(path)
    for name in ('gondola_native.py','import_gondola.py','mesh_import.py','mesh_materials.py','material_assets.py','atomic_equivalence_capture.py'):
        sources[str(scripts/name)]=identity(scripts/name)
    for name in ('GondolaService.h','GondolaService.cpp','NativeAtomicEquivalence.h','NativeAtomicEquivalence.cpp'):
        path=GAME/'unreal/Source/Yorimichi'/name;sources[str(path)]=identity(path)
    fixture=Path(__file__).with_name('gondola_native_equivalence.py')
    from atelier.build_inputs import local_imports
    roots=(GAME,GAME/'world',scripts,REPO/'platform/studio',REPO/'platform/harness')
    for path in {*local_imports(fixture,roots),Path(__file__),fixture,GAME/'tools/atomic_equivalence.py'}:
        sources[str(path)]=identity(path)
    spec=dict(schema=1,region='gondola-native',namespace=namespace,original_revision=ORIGINAL,game=str(GAME),out=str(output/'out'),archive=str(archive),
        output=str(output/'native'),content=str(real_directory(args.content.absolute()).resolve()),profiles=str(output/'site.json'),
        exports=exports,current_names=sorted(name for name in expected_actual if not any(token in name for token in ('_Rope_LOD1','_Rope_LOD2'))),
        original_names=list(PARENTS),source_files=sources,frozen_files=frozen,
        scope='three large owners only; native imported source/GPU/cooked/material/LOD/bounds and actual fixture queries; full normal fitting, production runtime and package cook remain separate')
    atomic_json(output/'spec.json',spec)
    if any(identity(Path(name))!=row for name,row in sources.items()):raise ValueError('Host preparation source changed')
    print('GONDOLA NATIVE SPEC',output/'spec.json',identity(output/'spec.json')['sha256'])


if __name__=='__main__':main()
