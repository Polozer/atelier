"""Bootstrap for one build-v2 Blender job, run by a fresh factory-startup Blender as `--python-expr`.

The Blender job loop (`blender_worker.py`) starts a new background Blender per job, in the staged job
folder, with this source plus a final `_main(<python_job.py source>)` call as its expression. The
job's configuration arrives on stdin. This prelude empties the factory scene, then runs the same
bootstrap as a Python job (`python_job.py`: `JobContext`, declared-code imports, fixed clock and
seed, path guard), so a Blender op is `def run(context)` with `bpy` importable. One difference:
`uuid.uuid4()` returns seeded UUIDs rather than raising (see `_with_seeded_uuid4`). The op sees only its
staged view; the job ID, folder and any source locator are not in the context.

Only the standard library and `bpy` are used, and nothing is read from the checkout.
"""
import json
import os
import sys


def _main(job_source):
    config = json.loads(sys.stdin.buffer.read())
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)
    os.close(null)
    import bpy

    # A factory scene without its default objects: every job starts from the same empty file.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    namespace = {'__name__': 'atelier_build_v2_python_job'}
    exec(compile(job_source, '<build-v2 python_job>', 'exec'), namespace)
    namespace['fix_clock_and_entropy'] = _with_seeded_uuid4(namespace['fix_clock_and_entropy'])
    namespace['undeclared_modules'] = _after_startup(namespace['undeclared_modules'], dict(sys.modules))
    namespace['main'](config, namespace['_report_to'](config['result_fd']))


def _after_startup(undeclared_modules, startup):
    """Blender's own startup loads modules before any job code runs (`__main__`, add-on and extension
    namespace packages, some named after user folders that do not exist). They are platform, not
    project code, so the undeclared-module check skips exactly those module objects."""
    def check(finder):
        return [name for name in undeclared_modules(finder) if startup.get(name) is not sys.modules.get(name)]
    return check


def _with_seeded_uuid4(fix_clock_and_entropy):
    """Blender's bundled glTF exporter keys its node tree with `uuid.uuid4()`, so in a Blender job
    uuid4 returns UUIDs drawn from the declared seed (its own generator, so `random` is unchanged)
    instead of raising. Every other entropy source stays refused."""
    def fix(seed):
        fix_clock_and_entropy(seed)
        import random
        import uuid

        generator = random.Random(f'atelier-build-v2-uuid4:{seed}')
        uuid.uuid4 = lambda: uuid.UUID(int=generator.getrandbits(128), version=4)
    return fix
