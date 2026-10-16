"""The shared transfer hands its exact floor boundary to the finishing bowl."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world' / 'regions'))
from craterpark.v2 import bowl_entry, finish, junctions as J, solids, dsl  # noqa: E402


@pytest.fixture(scope='module')
def cut_receiver():
    return bowl_entry.build(include_runout=False).mesh


def test_floor_port_is_cut_into_bowl_and_keeps_the_receiving_row_level(cut_receiver):
    port = finish.floor_port(cut_receiver)
    plan = finish.FinishPlan(port)
    np.testing.assert_allclose(plan.shape(port.row[:, [0, 2]]), 0., atol=1e-8)
    np.testing.assert_allclose(plan.floor(port.row[:, [0, 2]]), port.y, atol=1e-8)
    q = port.row[:, [0, 2]]
    assert (plan.shape(q + port.heading) < 0.).all()
    assert (plan.shape(q - port.heading) > 0.).all()
    assert plan.wall(plan.rim - plan.deep)[0] >= 15.


def test_receiver_has_no_faces_in_the_bowl_owned_runout(cut_receiver):
    entry = bowl_entry.definition()
    mesh = cut_receiver
    port = finish.floor_port(mesh)
    receiver = mesh.triangles()
    assert ((receiver[:, :, [0, 2]] - port.point) @ port.heading).max() < 1e-7
    assert np.linalg.norm(entry.path.point([entry.path.length])[0] - port.point) > 24.99
    assert len(solids.check_open(mesh.subset(mesh.role != dsl.ROLE[dsl.BASE]))) == 2
    row = J.boundary_row(mesh, port.point, port.heading)
    np.testing.assert_allclose(row, port.row)


def test_actual_bowl_and_receiver_have_no_extra_open_join(cut_receiver):
    bowl = finish.build(cut_receiver).mesh
    assert solids.check_closed(bowl) > 0.
    joined = dsl.Mesh.concat([cut_receiver, bowl])
    exposed = joined.subset(joined.role != dsl.ROLE[dsl.BASE])
    loops = solids.check_open(exposed)
    assert len(loops) == 2  # kicker inlet and the bowl's buried outer base
    flat = [loop for loop in loops if np.ptp(loop[:, 1]) < 1e-7]
    assert len(flat) == 1
    port = finish.floor_port(cut_receiver)
    np.testing.assert_allclose(flat[0][:, 1], port.y - 1.5, atol=1e-7)
