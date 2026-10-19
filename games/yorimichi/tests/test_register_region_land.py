"""The signed donor registration only fills missing land inside its rectangle."""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image


MAP = Path(__file__).resolve().parents[1] / 'world' / 'map'
sys.path.insert(0, str(MAP))


def module():
    spec = importlib.util.spec_from_file_location('register_region_land', MAP / 'register_region_land.py')
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def frames():
    """A 64x64 target whose east half is signed land, and a fully painted donor."""
    size = (64, 64)
    bounds = [-32., -32., 32., 32.]
    target = np.zeros((64, 64, 3), dtype='uint8')
    target[:] = [30, 70, 210]                             # blue sea
    target[10:54, 10:22] = [210, 190, 140]                # existing beach, kept as-is
    donor = np.zeros((64, 64, 3), dtype='uint8')
    donor[:] = [30, 70, 210]
    donor[:, 32:] = [190, 150, 90]                        # painted land in the east half
    target_mask = np.zeros((64, 64), dtype='uint8')
    target_mask[:, 32:] = 255
    donor_mask = np.zeros((64, 64), dtype='uint8')
    donor_mask[:, 32:] = 255
    return (Image.fromarray(target), Image.fromarray(target_mask), Image.fromarray(donor),
            Image.fromarray(donor_mask), bounds)


def test_registration_fills_missing_land_and_preserves_everything_else():
    tool = module()
    target, target_mask, donor, donor_mask, bounds = frames()
    result, box, changed, alpha = tool.register(
        target, target_mask, donor, donor_mask, bounds, bounds, [0., -32., 32., 32.], 2, True)
    original = np.asarray(target).copy()
    final = np.asarray(result)
    assert box == (32, 0, 64, 64)
    assert changed == int((final != original).any(axis=2).sum()) > 0
    assert alpha >= changed
    outside = np.zeros(64, dtype=bool)
    outside[32:] = True
    assert not (final[:, ~outside] != original[:, ~outside]).any()
    assert (final[:, 40:60][..., 0] > 150).all()          # donor land, not latent sea
    assert (final[20:40, 10:22] == original[20:40, 10:22]).all()   # existing beach untouched


def test_registration_refuses_an_empty_overlap():
    tool = module()
    target, target_mask, donor, donor_mask, bounds = frames()
    with pytest.raises(ValueError, match='no land shared'):
        tool.register(target, target_mask, donor, donor_mask, bounds, bounds, [-32., -32., 0., 32.], 2, False)


def test_fill_missing_refuses_when_nothing_is_missing():
    tool = module()
    target, target_mask, donor, donor_mask, bounds = frames()
    painted = np.asarray(target).copy()
    painted[:, 32:] = [200, 170, 120]                      # the target already painted that land
    with pytest.raises(ValueError, match='no land shared'):
        tool.register(Image.fromarray(painted), target_mask, donor, donor_mask, bounds, bounds,
                      [0., -32., 32., 32.], 2, True)
