"""Check a built distribution without an editable install or checkout import paths."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import zipfile


def main(wheel):
    with tempfile.TemporaryDirectory(prefix='atelier-wheel-') as directory:
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(directory)
        code = '''
import atelier.harness.board as board
import atelier.board as legacy
from atelier.harness.capacity import Resources
from atelier.capacity import Resources as OldResources
from atelier.harness import board_web
assert board is legacy
assert Resources is OldResources
assert board.__spec__.name == 'atelier.harness.board'
assert (board_web.ASSETS / 'app.js').is_file()
assert (board_web.ASSETS / 'index.html').is_file()
from atelier.harness.safety import memory_guard, tree_guard
assert memory_guard.__file__ and tree_guard.__file__
'''
        # -S bypasses the editable installation. The only package path is the
        # wheel's temporary extraction, including when called from the source tree.
        subprocess.run([sys.executable, '-S', '-c', code], cwd=directory,
                       env={**os.environ, 'PYTHONPATH': directory}, check=True, timeout=15)
    print('Isolated wheel imports, legacy identities and board assets passed')


if __name__ == '__main__':
    main(Path(sys.argv[1]))
