"""Test-only entry: the build-v2 Python job loop WITHOUT isolation, for portable tests of the loop.

It announces `TEST_WORKER_VERSION`, never the production worker version, so no controller keyed to
the real worker identity accepts its session. Production starts python_worker.py, which has no
unsandboxed mode.
"""
import argparse
import importlib.util
from pathlib import Path

WORKER = Path(__file__).resolve().parents[3] / 'studio/atelier/build_v2/python_worker.py'

spec = importlib.util.spec_from_file_location('build_v2_python_worker', WORKER)
python_worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(python_worker)

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument('--request-fd', type=int, required=True)
parser.add_argument('--response-fd', type=int, required=True)
args = parser.parse_args()
python_worker.serve(args.request_fd, args.response_fd, sandboxed=False)
