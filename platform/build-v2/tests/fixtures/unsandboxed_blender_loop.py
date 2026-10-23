"""Test-only entry: the build-v2 Blender job loop WITHOUT isolation, for portable tests of the loop.

It announces the Blender loop's test version, never the production one, so no controller keyed to
the real worker identity accepts its session. `--blender` names the Blender (or a stand-in) that
runs each job. Production starts blender_worker.py inside Blender, which has no unsandboxed mode.
"""
import argparse
import importlib.util
from pathlib import Path

WORKER = Path(__file__).resolve().parents[3] / 'studio/atelier/build_v2/blender_worker.py'

spec = importlib.util.spec_from_file_location('build_v2_blender_worker', WORKER)
blender_worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(blender_worker)

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument('--blender', required=True)
parser.add_argument('--request-fd', type=int, required=True)
parser.add_argument('--response-fd', type=int, required=True)
args = parser.parse_args()
blender_worker.serve(args.request_fd, args.response_fd, sandboxed=False, blender=args.blender)
