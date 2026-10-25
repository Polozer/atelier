"""An isolated import editor loads only the game modules its script declares, so every game class it calls is declared."""
import re
from pathlib import Path
from types import SimpleNamespace

GAME = Path(__file__).resolve().parents[1]
SCRIPTS = GAME / 'unreal/Scripts'
SOURCE = GAME / 'unreal/Source'


def game_classes():
    """{Python name of a UCLASS: owning game module} for every game module's public headers."""
    owner = {}
    for header in SOURCE.glob('*/*.h'):
        for name in re.findall(r'^class\s+\w+_API\s+U(\w+)\s*:', header.read_text(errors='ignore'), re.M):
            owner[name] = header.parent.name
    return owner


def reachable(script):
    """The script and the local Scripts modules it imports, transitively."""
    seen, pending = set(), [Path(script)]
    while pending:
        path = pending.pop()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        for name in re.findall(r'^\s*(?:from|import)\s+(\w+)', path.read_text(), re.M):
            pending.append(SCRIPTS / f'{name}.py')
    return seen


def called(text):
    """Attribute names read from the unreal module, under its own name or an `import unreal as X` alias."""
    names = {'unreal', *re.findall(r'\bimport\s+unreal\s+as\s+(\w+)', text)}
    return set(re.findall(r'\b(?:' + '|'.join(sorted(names)) + r')\.(\w+)\b', text))


def test_isolated_import_scripts_declare_every_game_module_they_call():
    from atelier import build
    recipe = build.load_recipe('yorimichi')
    owner = game_classes()
    assert owner.get('CitySurfaceValidation') == 'Yorimichi'
    missing = []
    for step in recipe.steps(SimpleNamespace(out=Path('/build'), uproject=None)):
        for action in step.commands:
            if not isinstance(action, build.UnrealScript) or not action.modules:
                continue  # an undeclared script runs on the whole project
            used = {owner[name] for path in reachable(action.script) for name in called(path.read_text()) if name in owner}
            if not used <= set(action.modules):
                missing.append((step.name, sorted(used - set(action.modules))))
    assert not missing, missing
