"""Production train import refuses invalid inputs before touching Unreal assets."""
import json
import runpy
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from test_belmonte_train_service import S, write_fixture


class ImportStarted(Exception):
    pass


@pytest.mark.parametrize('change', ['valid', 'raw-furniture', 'missing-summary', 'stale-summary', 'corrupt-lod',
                                    'missing-vehicle', 'stale-service'])
def test_import_preflight_precedes_unreal_mutations(tmp_path, monkeypatch, change):
    root = tmp_path / 'belmonte-train'
    write_fixture(root)
    data = S.build(root)
    raw = root / 'furniture/lod/canteen-mug_LOD0.glb'
    for vehicle in data['consist']['vehicles']:
        for name in vehicle['levels']:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(raw, target)
    (root / 'service').mkdir(exist_ok=True)
    if change == 'raw-furniture':
        data['furniture']['canteen-mug']['levels'][0]['glb'] = 'canteen-mug.glb'
    elif change == 'missing-summary':
        (root / 'furniture/lod/summary.json').unlink()
    elif change == 'stale-summary':
        (root / 'furniture/canteen-mug.glb').write_bytes(b'different source')
    elif change == 'corrupt-lod':
        raw.write_bytes(b'broken')
    elif change == 'missing-vehicle':
        (root / data['consist']['vehicles'][0]['levels'][0]).unlink()
    elif change == 'stale-service':
        data['sources']['furniture_bake'] = '0' * 64
    (root / 'service/service.json').write_text(json.dumps(data))
    editor = MagicMock()
    system = MagicMock()
    system.execute_console_command.side_effect = ImportStarted
    fake = SimpleNamespace(EditorAssetLibrary=editor, SystemLibrary=system,
                           AssetToolsHelpers=MagicMock(), AssetRegistryHelpers=MagicMock())
    monkeypatch.setitem(sys.modules, 'unreal', fake)
    monkeypatch.setattr(S.yori, 'OUT', tmp_path)
    script = Path(__file__).resolve().parents[1] / 'unreal/Scripts/import_belmonte_train.py'
    if change == 'valid':
        with pytest.raises(ImportStarted):
            runpy.run_path(str(script))
        system.execute_console_command.assert_called_once()
    else:
        with pytest.raises((ValueError, FileNotFoundError)):
            runpy.run_path(str(script))
        assert not system.mock_calls
    assert not editor.mock_calls
