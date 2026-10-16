"""Lazy aliases for pre-Harness Python imports and ``python -m`` entry points.

Implementations and class identities belong to atelier.harness. No native observer,
service or configuration is loaded merely by importing atelier.
"""
import importlib
import importlib.abc
import importlib.util
import sys


def canonical(name):
    if not name.startswith('atelier.'):
        return None
    family = name.split('.', 2)[1]
    if family == 'safety' or family in {'board', 'capacity'} or family.startswith(('board_', 'capacity_')):
        return 'atelier.harness.' + name.removeprefix('atelier.')
    return None


class _AliasLoader(importlib.abc.Loader):
    def __init__(self, target, origin):
        self.target, self.origin = target, origin

    def create_module(self, spec):
        # Import initializes this placeholder, never the canonical module's spec.
        return None

    def exec_module(self, module):
        sys.modules[module.__name__] = importlib.import_module(self.target)

    def get_code(self, fullname):
        # Preserve legacy -m commands without executing a second copy under the
        # legacy import name (and therefore creating incompatible class objects).
        return compile(f'import runpy; runpy.run_module({self.target!r}, run_name="__main__")',
                       self.origin or fullname, 'exec')

    def get_filename(self, fullname):
        return self.origin or fullname


class _LegacyHarness(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        name = canonical(fullname)
        if name is None:
            return None
        spec = importlib.util.find_spec(name)
        if spec is None:
            return None
        return importlib.util.spec_from_loader(fullname, _AliasLoader(name, spec.origin),
                                               origin=spec.origin,
                                               is_package=spec.submodule_search_locations is not None)


def install():
    # Replace Studio's deferred adapter once Harness is actually used. Keeping it
    # out of ordinary imports also avoids unrelated world-input dependencies.
    sys.meta_path[:] = [finder for finder in sys.meta_path
                        if not getattr(finder, '_atelier_harness_bootstrap', False)]
    finder = next((finder for finder in sys.meta_path if isinstance(finder, _LegacyHarness)), None)
    if finder is None:
        finder = _LegacyHarness()
        sys.meta_path.insert(0, finder)
    return finder
