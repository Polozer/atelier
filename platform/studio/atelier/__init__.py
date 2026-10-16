"""Atelier studio: the tools behind the `atelier` command.

The modules at this level (`paths`, `env`, `conventions`, `manifest`) use only the standard library, so they can be
imported from the command line, from Blender's Python and from Unreal's. Host-specific code lives in
`atelier.blender` and is only imported inside Blender.
"""
__version__ = '0.1.0'

# Embedded Blender/Unreal interpreters add only platform/studio to sys.path. Installed
# wheels already contain atelier/harness; source checkouts mount its dedicated tree.
from pathlib import Path as _Path
_harness_source = _Path(__file__).resolve().parents[2] / 'harness'
if (_harness_source / 'harness' / '__init__.py').is_file():
    __path__.append(str(_harness_source))

# Load the legacy adapter only when a legacy Harness name is requested. Ordinary
# authoring imports (paths, Blender helpers, etc.) never load coordination code.
import sys as _sys


class _HarnessImports:
    _atelier_harness_bootstrap = True

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith('atelier.'):
            return None
        family = fullname.split('.', 2)[1]
        if family not in {'board', 'capacity', 'safety'} and not family.startswith(('board_', 'capacity_')):
            return None
        from importlib import import_module
        return import_module('atelier.harness.compat').install().find_spec(fullname, path, target)


if not any(getattr(finder, '_atelier_harness_bootstrap', False) for finder in _sys.meta_path):
    _sys.meta_path.insert(0, _HarnessImports())
del _Path, _harness_source, _sys
