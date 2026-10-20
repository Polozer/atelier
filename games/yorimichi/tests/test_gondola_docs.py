"""The gondola kit's documented thresholds are its code constants (docs = code).

README.md's "Gates and thresholds" table names each constant and its value; every row must equal the code. The prose
in README.md and NOTES.md that quotes a threshold must quote the same number.
"""
import re

import pytest

from gondola_kit_fixture import KIT, gondola_modules

README = (KIT / 'README.md').read_text()
NOTES = (KIT / 'NOTES.md').read_text()
ROW = re.compile(r"^\| `(?P<mod>\w+)\.(?P<name>\w+)(?:\['(?P<key>\w+)'\])?` \| (?P<value>[0-9.]+) (?P<unit>[^|]+?) \|", re.M)


@pytest.fixture(scope='module')
def kit():
    with gondola_modules('checks', 'walk', 'params', 'stations', pure=False) as k:   # stations: mathutils stubbed
        return k


def rows():
    return [m.groupdict() for m in ROW.finditer(README)]


def test_threshold_table_lists_every_gate_constant():
    named = {(r['mod'], r['name'], r['key']) for r in rows()}
    for want in [('checks', 'ROPE_CLEARANCE', None), ('checks', 'CONTACT_TOL', None), ('checks', 'FLOOR_TILT_TOL_DEG', None),
                 ('checks', 'BUDGET', 'cabin'), ('checks', 'BUDGET', 'tower'), ('checks', 'BUDGET', 'station'),
                 ('walk', 'RADIUS', None), ('walk', 'STEP', None), ('walk', 'HEAD', None), ('walk', 'MIN_WIDTH', None),
                 ('walk', 'RISER_MAX', None), ('walk', 'TREAD_MIN', None), ('checks', 'STATION_LOOP_MARGIN', None),
                 ('walk', 'BOARDING_GAP_MIN', None), ('walk', 'BOARDING_GAP_MAX', None), ('walk', 'SILL_MIN', None),
                 ('walk', 'SILL_MAX', None)]:
        assert want in named, want


def test_threshold_table_matches_the_code(kit):
    assert rows()
    for r in rows():
        value = getattr(getattr(kit, r['mod']), r['name'])
        if r['key']:
            value = value[r['key']]
        assert float(r['value']) == pytest.approx(value), r


def test_budget_tables_in_code_are_the_build_budgets(kit):
    assert set(kit.checks.BUDGET) == {'cabin', 'tower', 'station'}


def test_prose_quotes_the_same_numbers(kit):
    c, w = kit.checks, kit.walk
    rr = kit.params.DEFAULTS['rope_radius']
    b = c.BUDGET
    quotes = {
        f'rope radius plus {c.ROPE_CLEARANCE:g} m': README,
        f'({c.required_clearance(rr):.3f} m for the {round(rr * 2000)} mm rope)': README,
        f'by more than {c.CONTACT_TOL * 1000:g} mm': README,
        f'within {c.CONTACT_TOL * 1000:g} mm either way': README,
        f'cabin {b["cabin"] // 1000}k, tower {b["tower"] // 1000}k, station {b["station"] // 1000}k': README,
        f'a {w.RADIUS:.2f} m capsule': README,
        f'{w.STEP:.2f} m step limit': README,
        f'{w.HEAD:.1f} m headroom': README,
        f'{w.MIN_WIDTH:g} m minimum clear width': README,
        f'risers at most {w.RISER_MAX:.2f} m, treads at least {w.TREAD_MIN:.2f} m, at least {w.MIN_WIDTH:g} m wide': README,
        f'at least {w.DOOR_MIN[0]:g} m wide and {w.DOOR_MIN[1]:.1f} m high': README,
        f'drops {kit.stations.ROPE_DROP:.2f} m inside the mouth': README,
        f'rope radius within {c.CONTACT_TOL * 1000:g} mm': NOTES,
        f'except the {kit.stations.ATTACH_ZONE:g} m attach zone': NOTES,
        f'`checks.STATION_LOOP_MARGIN` ({c.STATION_LOOP_MARGIN:.2f} m)': README,
        f'a boarding gap outside {w.BOARDING_GAP_MIN:.2f} to {w.BOARDING_GAP_MAX:.2f} m or a sill\noutside {w.SILL_MIN:g} to {w.SILL_MAX:.2f} m': README,
        f'each grip jaw half (tag `jaw`; {c.EXPECTED_PARTS["jaw"]} per grip)': README,
        f'each tower sheave (tag `sheave`; {c.EXPECTED_PARTS["sheave"]} per rope)': README,
        f'(tag `bullwheel groove`; {c.EXPECTED_PARTS["bullwheel groove"]} per rope)': README,
    }
    for text, doc in quotes.items():
        assert text in doc, text


def test_documented_fail_rule_is_the_code_rule(kit):
    """The README's clearance and contact rules, applied to the documented numbers, give the code's verdicts."""
    c = kit.checks; rr = kit.params.DEFAULTS['rope_radius']
    assert c.clearance_ok(0.095, rr) and not c.clearance_ok(0.094, rr)
    assert c.contact_ok(rr + 0.002, rr) and not c.contact_ok(rr + 0.003, rr)
