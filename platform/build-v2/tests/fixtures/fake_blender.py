"""A stand-in for background Blender in portable tests: no Blender, the same job command line.

It accepts only the exact flags the build-v2 Blender job loop uses for a job, installs a minimal
`bpy` (`app.version_string`, `app.binary_path`, `ops.wm.read_factory_settings`) and, as Blender's
startup does, a module whose file lies in a missing user folder inside the job folder, then runs the
`--python-expr` text as `__main__`. An exception exits 1, as `--python-exit-code 1` makes Blender do.
Real Blender behaviour (scenes, exporters, its own startup reads) is covered only by the T1b session.
"""
import os
import sys
import types

EXPECTED = ['--factory-startup', '-b', '--threads', '3', '--python-exit-code', '1', '--disable-autoexec', '--python-use-system-env',
            '--python-expr']


def main():
    args = sys.argv[1:]
    if args[:len(EXPECTED)] != EXPECTED or len(args) != len(EXPECTED) + 1:
        print(f'fake blender: unexpected command line {args[:len(EXPECTED)]!r}', file=sys.stderr)
        raise SystemExit(2)
    resets = []
    bpy = types.ModuleType('bpy')
    bpy.app = types.SimpleNamespace(version_string='fake-blender', binary_path=sys.argv[0])
    wm = types.SimpleNamespace(read_factory_settings=lambda use_empty=False: resets.append(use_empty))
    bpy.ops = types.SimpleNamespace(wm=wm)
    bpy.factory_resets = resets
    sys.modules['bpy'] = bpy
    # Like Blender, startup leaves a namespace package named after a user folder that does not exist.
    extensions = types.ModuleType('bl_ext')
    extensions.__file__ = os.path.join(os.getcwd(), '.no-user-folder', 'extensions', '__init__.py')
    sys.modules['bl_ext'] = extensions
    try:
        exec(compile(args[-1], '<python-expr>', 'exec'), {'__name__': '__main__'})
    except SystemExit:
        raise
    except BaseException:
        import traceback
        traceback.print_exc()
        raise SystemExit(1)


main()
