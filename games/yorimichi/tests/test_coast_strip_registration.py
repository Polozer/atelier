"""A coastline correction must keep the actual route/pier and its source receipt."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw
import pytest

MAP = Path(__file__).resolve().parents[1] / 'world/map'


@pytest.fixture
def tool(monkeypatch):
    monkeypatch.syspath_prepend(str(MAP))
    spec = importlib.util.spec_from_file_location('coast_strip', MAP / 'register_coast_strip.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_images():
    source = Image.new('RGB', (1536, 1024), (110, 140, 60))
    ImageDraw.Draw(source).rectangle((0, 760, 1535, 1023), fill=(25, 100, 150))
    ImageDraw.Draw(source).rectangle((645, 735, 934, 979), fill=(170, 160, 135))
    ImageDraw.Draw(source).rectangle((500, 640, 1535, 660), fill=(80, 75, 65))
    mask = Image.new('L', source.size, 255)
    ImageDraw.Draw(mask).rectangle((0, 776, 1535, 1023), fill=0)
    ImageDraw.Draw(mask).rectangle((645, 735, 934, 979), fill=255)
    return source, mask


def test_corrected_coast_retains_pier_road_and_distant_rgb(tool):
    source, mask = fixture_images()
    image, receipt = tool.register(source, mask)
    before, after = np.asarray(source), np.asarray(image)
    assert np.array_equal(after[735:980, 645:935], before[735:980, 645:935])
    assert np.array_equal(after[:700, 500:], before[:700, 500:])
    assert np.array_equal(after[:400], before[:400])
    assert image.getpixel((200, 770)) == source.getpixel((200, 750))
    assert image.getpixel((200, 790)) == source.getpixel((200, 800))
    assert receipt['changed_fraction'] < .08
    assert receipt['coast_error'] < .0035


def test_invalid_frame_or_missing_ocean_is_rejected(tool):
    source, mask = fixture_images()
    with pytest.raises(ValueError, match='exact 1536x1024'):
        tool.register(source.resize((1024, 1024)), mask)
    with pytest.raises(ValueError, match='connected ocean'):
        tool.register(Image.new('RGB', source.size, (110, 140, 60)), mask)
    ImageDraw.Draw(source).rectangle((100, 400, 110, 1023), fill=(110, 140, 60))
    with pytest.raises(ValueError, match='complete ocean profile'):
        tool.register(source, mask)


def test_publication_is_complete_and_never_overwrites(tool, tmp_path):
    path = tmp_path / 'receipt.json'
    tool.publish(path, b'{"complete":true}')
    assert json.loads(path.read_text()) == {'complete': True}
    with pytest.raises(FileExistsError):
        tool.publish(path, b'changed')
    assert path.read_bytes() == b'{"complete":true}'
    assert list(tmp_path.iterdir()) == [path]


def test_bad_source_receipt_cannot_publish(tool, tmp_path, monkeypatch):
    source_path, record = prepare_cli(tool, tmp_path, monkeypatch)
    data = json.loads(record.read_text())
    data['output_sha256'] = '0'*64
    record.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='Source bytes/geography'):
        tool.main()
    assert not (tmp_path/'out.png').exists() and not (tmp_path/'out.json').exists()
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() != '0'*64


def prepare_cli(tool, tmp_path, monkeypatch):
    source, mask = fixture_images()
    source_path = tmp_path / 'source.png'
    source.save(source_path)
    assets = tmp_path / 'assets'
    (assets / 'coasts').mkdir(parents=True)
    mask_path = assets / 'coasts/momiji_coast.png'
    mask.save(mask_path)
    geography = tool.atlas.geography_signature()
    mask_sha = hashlib.sha256(mask_path.read_bytes()).hexdigest()
    (assets / 'coasts/source.json').write_text(json.dumps(dict(geography=geography, frames=dict(momiji_coast=dict(
        bounds=[-650., -350., 400., 350.], sha256=mask_sha, reference_sha256='a'*64)))))
    record = tmp_path / 'source.json'
    record.write_text(json.dumps(dict(bounds=[-650., -350., 400., 350.], labels_baked=False, geography=geography,
        output_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(), inputs=[
            dict(role='exact geography', sha256='a'*64), dict(role='exact coast mask', sha256=mask_sha)])))
    monkeypatch.setattr(tool.atlas, 'ASSETS', assets)
    monkeypatch.setattr(sys, 'argv', ['register', '--source', str(source_path), '--record', str(record),
                                      '--mask', str(mask_path), '--out', str(tmp_path/'out.png'),
                                      '--out-record', str(tmp_path/'out.json')])
    return source_path, record


@pytest.mark.parametrize('role,missing', [('exact geography', False), ('exact coast mask', False),
                                        ('exact geography', True), ('exact coast mask', True)])
def test_wrong_or_missing_generation_binding_cannot_publish(tool, tmp_path, monkeypatch, role, missing):
    _, path = prepare_cli(tool, tmp_path, monkeypatch)
    record = json.loads(path.read_text())
    if missing:
        record['inputs'] = [item for item in record['inputs'] if item['role'] != role]
    else:
        next(item for item in record['inputs'] if item['role'] == role)['sha256'] = '0'*64
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='Generation input plan/mask bindings'):
        tool.main()
    assert not (tmp_path/'out.png').exists() and not (tmp_path/'out.json').exists()


@pytest.mark.parametrize('which', ['source', 'receipt', 'mask', 'manifest', 'geography'])
def test_input_drift_after_decode_cannot_publish(tool, tmp_path, monkeypatch, which):
    source_path, receipt = prepare_cli(tool, tmp_path, monkeypatch)
    register = tool.register
    def drift(image, mask):
        result = register(image, mask)
        if which == 'geography':
            geography = tool.atlas.geography_signature()
            monkeypatch.setattr(tool.atlas, 'geography_signature', lambda: {**geography, 'drift': 'changed'})
        else:
            paths = dict(source=source_path, receipt=receipt, mask=tool.atlas.ASSETS/'coasts/momiji_coast.png',
                         manifest=tool.atlas.ASSETS/'coasts/source.json')
            paths[which].write_bytes(b'changed after snapshot')
        return result
    monkeypatch.setattr(tool, 'register', drift)
    with pytest.raises(ValueError, match='drifted during registration'):
        tool.main()
    assert not (tmp_path/'out.png').exists() and not (tmp_path/'out.json').exists()
