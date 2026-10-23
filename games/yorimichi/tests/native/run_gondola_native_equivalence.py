"""Host-only guarded GDX finalization; no source generation, compile or native launch on import."""
import json
import os
from pathlib import Path
import subprocess
import sys

from atelier import build
from atelier.atomic_files import atomic_json
from atelier.export_manifest import real_directory
from atelier.harness.safety import guarded

GAME=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(GAME/'tools'),str(Path(__file__).parent)]
import atomic_equivalence as eq
from track_native_equivalence import check_private_launch,startup_ddc,sha
from run_track_native_equivalence import strict_cleanup
from gondola_native_equivalence import unchanged,allowed_packages

PARENTS=('GD_L1_Rope_LOD0','GD_L2_Rope_LOD0','GD_floor_rim_Access')


def head(root):
    eq.require(not subprocess.check_output(['git','status','--porcelain'],cwd=root),'Native source checkout must remain clean')
    return subprocess.check_output(['git','rev-parse','HEAD'],cwd=root).decode().strip()


def binding(path):
    row=dict(path=str(Path(path).absolute()),sha256=sha(path));eq.artifact(row);return row


def compare(before,after,parent):
    eq.require(before.get('policy_scope')==after.get('policy_scope')=='fixture','Gondola receiving policy must remain fixture-scoped')
    original=eq.native_raw_set(before,parent);actual=eq.native_raw_set(after,parent)
    levels=set(range(3 if '_Rope_' in parent else 1))
    eq.require(set(original['source_lods'])==set(actual['source_lods'])==set(original['render_lods'])==set(actual['render_lods'])==levels,
        'Incomplete authored Gondola source/GPU LOD census')
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



def compare_bounds(rows,parent):
    eq.require(isinstance(rows,list) and len(rows)==(2 if parent=='GD_floor_rim_Access' else 1),'Missing actual logical bounds poses')
    for row in rows:
        eq.require(set(row)=={'original','actual'} and len(row['actual'])==2,'Missing complete child logical bounds observations')
        before=row['original'];old,_=eq.component_bounds(before)
        eq.require(eq.finite(before.get('matrix')) and before.get('matrix'),'Missing actual bounds pose matrix')
        for actual in row['actual']:
            current,_=eq.component_bounds(actual)
            eq.require(current==old and actual['matrix']==before['matrix'],'Original logical box/true sphere/placement differs: '+parent)
    if len(rows)==2:eq.require(rows[0]['original']['matrix']!=rows[1]['original']['matrix'],'Access station frame pose is missing')
    return rows


def finalize(spec_path,payload,evidence,native,validate_native):
    """@cc [owner:fontanierh,label:correctness;safety] host-only-gondola-full-proof
    Generic geometry verification MUST run only on the host after actual whole0,
    positive empty cleanup and fresh spec/source/module bindings. Retirement MUST
    use only the recorded exact current fixture package/file roster. This proof
    MUST NOT claim normal fitting/runtime, task reuse or package-cook acceptance.
    """
    spec=json.loads(payload);output=Path(spec['output'])
    eq.guard_binding(evidence)
    eq.require(native==spec['native'],'Prepared/actual native modules differ')
    validate_native()
    eq.require(Path(spec_path).read_bytes()==payload,'Prepared Gondola spec changed')
    unchanged(spec['source_files']);unchanged(spec['frozen_files'])
    launch=check_private_launch(spec);engine_log=binding(launch['startup_log'])
    observed=startup_ddc(launch,eq.artifact(engine_log).decode(errors='replace'))
    receiving=json.loads((output/'startup-ddc.json').read_bytes())
    eq.require(receiving['launch']==launch and all(receiving[key]==value for key,value in observed.items()),'Actual Gondola startup/private DDC differs')
    records=json.loads((output/'native.json').read_bytes())
    eq.require(set(records)==set(PARENTS),'Incomplete actual Gondola owner census')
    owners={}
    for parent in PARENTS:
        row=records[parent];eq.require(set(row)=={'before','after','bounds_observations'},'Foreign Gondola capture record')
        expected_before={spec['namespace']+'/Before/World/'+parent+'.'+parent}
        expected_after={spec['namespace']+'/After/World/'+parent+f'_Piece{i:02d}.'+parent+f'_Piece{i:02d}' for i in range(2)}
        eq.require(set(row['before']['meshes'])==expected_before and set(row['after']['meshes'])==expected_after,
            'Actual Gondola mesh capture escaped finite owner roster')
        owners[parent]=compare(row['before'],row['after'],parent)
        owners[parent]['logical_bounds_exact']=compare_bounds(row['bounds_observations'],parent)
    manifest=json.loads((Path(spec['out'])/'gondola/manifest.json').read_bytes())
    cleanup=json.loads((output/'cleanup.json').read_bytes())
    eq.require(set(cleanup['allowed_packages'])==allowed_packages(spec,manifest),'Fixture cleanup package authority differs')
    strict_cleanup(dict(content=spec['content'],package=spec['namespace']),cleanup)
    unchanged(spec['source_files']);unchanged(spec['frozen_files']);validate_native()
    result=dict(schema=1,native_geometry_complete=True,complete=False,native_complete=False,
        production_runtime_complete=False,whole_exit=0,guard_empty=True,fixture_absent=True,owners=owners,
        native=native,guard=evidence,spec_sha256=sha(spec_path),engine_log=engine_log,startup_ddc=observed,
        scope=spec['scope'])
    atomic_json(output/'host-result.json',result)
    return result


def run(workspace):
    from network_review_common import current_native_build
    root=real_directory(Path(workspace).absolute());spec_path=root/'spec.json';payload=eq.artifact(binding(spec_path));spec=json.loads(payload)
    eq.require(spec.get('schema')==2 and spec.get('region')=='gondola-native','Fresh Gondola native schema required')
    eq.require(Path.cwd().resolve()==Path(spec['game']).parents[1],'Run in the prepared actual receiving environment')
    source_head=head(Path(spec['game']).parents[1]);unchanged(spec['source_files']);unchanged(spec['frozen_files'])
    ctx=build.Context('yorimichi');eq.require(ctx.game_dir==Path(spec['game']),'Wrong native receiving game')
    eq.require(real_directory(ctx.uproject.parent/'Content').resolve()==Path(spec['content']),'Prepared Content differs from actual receiving project')
    native=current_native_build(ctx);eq.require(native==spec['native'],'Actual compiled module differs from fresh prepared native identity')
    launch=check_private_launch(spec);output=Path(spec['output']);guard=root/'guard'
    for path in (guard,output/'native.json',output/'cleanup.json',output/'host-result.json',Path(launch['startup_log']),root/'whole-result.json'):
        eq.require(not os.path.lexists(path),'Fresh exclusive Gondola invocation required')
    fixture=Path(spec['content'])/spec['namespace'].removeprefix('/Game/')
    eq.require(not os.path.lexists(fixture),'Previous Gondola fixture namespace remains')
    driver=Path(__file__).with_name('gondola_native_equivalence.py').absolute()
    eq.require(str(driver) in spec['source_files'] and sha(driver)==spec['source_files'][str(driver)]['sha256'],'Unbound actual native Gondola driver')
    marker='GONDOLA THREE LARGE OWNER NATIVE CAPTURE COMPLETE '+sha(spec_path)
    command=build.UnrealScript(Path(__file__).with_name('gondola_native_equivalence.py'),marker,
        null_rhi=True,modules=('Yorimichi',),args=('-nosound','-noshaderworker',*launch['args']))
    with command.prepared(ctx) as (argv,overrides):
        eq.require([v for v in argv if v in launch['args']]==launch['args'],'Prepared Gondola private argv changed')
        env=dict(ctx.env(),**dict(overrides),ATELIER_GONDOLA_NATIVE_SPEC=str(spec_path),
            ATELIER_GONDOLA_NATIVE_SPEC_SHA256=sha(spec_path),ATELIER_BUILD_ROOT=str(root/'native-build'))
        code=guarded.run(argv,guard,timeout=1200,queue_seconds=1800,limit_gib=10.,kind='job',
            purpose='Gondola three-owner actual imported native fixture',env=env,progress=25.,track_tree=True)
    atomic_json(root/'whole-result.json',dict(exit_code=code,head=source_head,native=native,argv=argv,launch=launch))
    if code:raise SystemExit(code)
    evidence=dict(receipt=binding(guard/'memory-health-tree.json'),stdout=binding(guard/'stdout.log'),
        marker=marker,whole_result=binding(root/'whole-result.json'))
    eq.guard_binding(evidence)
    eq.require(current_native_build(ctx)==native and head(Path(spec['game']).parents[1])==source_head,'Native/source receiving identity changed')
    def validate_native():
        eq.require(current_native_build(ctx)==native and head(Path(spec['game']).parents[1])==source_head,'Native/source receiving identity changed during host verification')
    finalize(spec_path,payload,evidence,native,validate_native)
    print('GONDOLA ACTUAL NATIVE HOST PROOF WHOLE0/EMPTY COMPLETE; fixture scope only',flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--workspace',type=Path,required=True)
    run(parser.parse_args().workspace)
