"""Nox's export step beyond the shared ones (pipeline/export.py): his seat corrective shapes, checked against the
contract in source-manifest.json and recorded as export.json `seat_corrective` and `contact_morphs` (Scripts/import_character.py
captures their skin contacts).
"""


def seat_corrective(nox):
    """Verify the committed corrective targets before exporting their native names."""
    contract = nox.record.get('seat_corrective')
    if contract is None:
        return None
    grid = contract['grid_degrees']
    assert grid == [-25, 0, 35, 70, 105], 'Unexpected Nox hip-flexion grid'
    assert contract['gate_degrees'] == [35, 60], 'Unexpected Nox corrective gate'
    assert contract['interpolation'] == 'bilinear', 'Nox requires bounded bilinear interpolation'
    body = next(o for o in nox.meshes if o.name == 'Nox_Body')
    head = next(o for o in nox.meshes if o.name == 'Nox_Head')
    assert not head.data.shape_keys, 'The seat correction must not change the head'
    assert body.data.shape_keys, 'Missing Nox seat targets'
    keys = body.data.shape_keys.key_blocks
    basis = keys['Basis']
    angle = lambda value: 'm' + str(-value) if value < 0 else str(value)
    names = [f'NoxSeat_L{angle(left)}_R{angle(right)}' for left in grid for right in grid]
    assert set(keys.keys()) == {'Basis', *names}, 'Unexpected Nox body shape targets'
    targets = {}
    for name, (left, right) in zip(names, ((left, right) for left in grid for right in grid)):
        key = keys[name]
        assert key.value == 0, ('Nonzero neutral shape value', name)
        changed = sum((vertex.co - base.co).length_squared > 1e-16 for vertex, base in zip(key.data, basis.data))
        required = max(left, right) > 35
        assert changed == (contract['changed_vertices_per_target'] if required else 0), ('Nox shape footprint changed', name, changed)
        targets[name] = dict(left_degrees=left, right_degrees=right, nonzero_vertices=changed)
    return dict(grid_degrees=grid, gate_degrees=contract['gate_degrees'], interpolation='bilinear', targets=targets)


def body(prepared, report):
    """The checked seat targets as `seat_corrective`; those that move vertices are `contact_morphs`, whose deltas the
    import keeps for the skin readers."""
    corrective = report['seat_corrective'] = seat_corrective(prepared)
    if corrective:
        report['contact_morphs'] = [name for name, target in corrective['targets'].items() if target['nonzero_vertices']]
