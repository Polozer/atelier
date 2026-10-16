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
from .harness.compat import install as _install_harness_compat
_install_harness_compat()
del _Path, _harness_source, _install_harness_compat
