"""Charted objects as obstacles (issue #113).

The primitive builder is tested on a hand-made feature list, the obstacle
source on primitives in metres around the synthetic test origin, and the
reader on the two real NOAA cells installed with the package.

Runs under plain pytest (``colcon test``); no launch_test runner needed.
"""

import math
import os
import pathlib

from asv_sim import charts
from asv_sim import collision
import pytest
from test_collision import ns
from test_collision import Rig

ENC_DIR = pathlib.Path(__file__).resolve().parents[1] / 'enc'


def linear(lon, lat):
    """Project flatly for the builder tests: 1 degree is 1000 m."""
    return lon * 1000.0, lat * 1000.0


def source_for(rig, primitives):
    """Return an obstacle source whose frame is centred on the rig origin."""
    project = charts.make_projection(rig.lon0, rig.lat0)
    return collision.ChartedObjectSource(primitives, project)


def solid(klass, x0, y0, x1, y1, radius, depth=None):
    return charts.Primitive(klass, x0, y0, x1, y1, radius, depth)


# the builder ---------------------------------------------------------------

def test_a_line_becomes_one_segment_per_leg_with_the_class_half_width():
    features = [charts.Feature(
        'SLCONS', 'line', [[(0.0, 0.0), (0.01, 0.0), (0.01, 0.01)]], None)]
    prims, counts = charts.build_primitives(
        features, charts.DEFAULT_FOOTPRINTS, linear)
    assert counts == {'SLCONS': 2}
    assert [(p.x0, p.y0, p.x1, p.y1) for p in prims] == [
        (0.0, 0.0, 10.0, 0.0), (10.0, 0.0, 10.0, 10.0)]
    assert all(p.radius == charts.DEFAULT_FOOTPRINTS['SLCONS'] for p in prims)


def test_a_point_becomes_a_circle_with_the_class_radius():
    features = [charts.Feature('BOYLAT', 'point', [[(0.002, 0.003)]], None)]
    prims, counts = charts.build_primitives(
        features, charts.DEFAULT_FOOTPRINTS, linear)
    assert counts == {'BOYLAT': 1}
    p = prims[0]
    assert (p.x0, p.y0, p.x1, p.y1) == (2.0, 3.0, 2.0, 3.0)
    assert p.radius == charts.DEFAULT_FOOTPRINTS['BOYLAT']


def test_an_area_contributes_all_its_rings_as_segments():
    outer = [(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01), (0, 0)]
    hole = [(0.002, 0.002), (0.004, 0.002), (0.004, 0.004), (0.002, 0.002)]
    features = [charts.Feature('PONTON', 'area', [outer, hole], None)]
    prims, counts = charts.build_primitives(
        features, charts.DEFAULT_FOOTPRINTS, linear)
    assert counts == {'PONTON': 4 + 3}


def test_the_charted_depth_is_carried_and_a_class_of_size_zero_is_left_out():
    features = [
        charts.Feature('UWTROC', 'point', [[(0.0, 0.0)]], 0.3),
        charts.Feature('BOYLAT', 'point', [[(0.0, 0.0)]], None)]
    table = charts.parse_footprints(['BOYLAT=0'])
    prims, counts = charts.build_primitives(features, table, linear)
    assert counts == {'UWTROC': 1}
    assert prims[0].depth == 0.3


def test_footprint_overrides_replace_the_defaults():
    table = charts.parse_footprints(['boylat=2.5', 'SLCONS = 0.1'])
    assert table['BOYLAT'] == 2.5 and table['SLCONS'] == 0.1
    assert table['PILPNT'] == charts.DEFAULT_FOOTPRINTS['PILPNT']


@pytest.mark.parametrize('entry', ['BOYLAT', 'BOYLAT=big', 'BOYLAT=-1',
                                   'BOYLAT=nan', 'LNDARE=1', '=2'])
def test_a_bad_footprint_override_is_refused(entry):
    with pytest.raises(ValueError, match='collision.enc_footprints'):
        charts.parse_footprints([entry])


def test_a_path_that_is_not_there_or_holds_no_cell_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError):
        charts.find_cells(str(tmp_path / 'absent'))
    with pytest.raises(FileNotFoundError, match='no .000'):
        charts.find_cells(str(tmp_path))


# the obstacle source -------------------------------------------------------

def bow_east(rig, d):
    return rig.en(d)[0] + d.model.length / 2.0


def test_a_boat_driven_at_a_pier_stops_at_it_and_backs_off(mdl, world):
    rig = Rig(mdl, world, terrain=False)
    # a north-south pier 2 m wide, 30 m east of the origin
    rig.collisions.sources.append(source_for(rig, [
        solid('SLCONS', 30.0, -60.0, 30.0, 60.0, 1.0)]))
    a = rig.add('a', 0.0, 0.0, 90.0)
    rig.run(25.0, {'a': 1.0})
    assert bow_east(rig, a) == pytest.approx(29.0, abs=0.1)
    assert abs(a.speed) < 0.2
    assert [(e['kind'], e['other']) for e in rig.events] == [
        (collision.KIND_OBJECT, 'SLCONS')]
    rig.run(8.0, {'a': -1.0})
    assert bow_east(rig, a) < 25.0


def test_a_buoy_blocks_head_on_and_lets_a_boat_slide_past(mdl, world):
    rig = Rig(mdl, world, terrain=False)
    rig.collisions.sources.append(source_for(rig, [
        solid('BOYLAT', 30.0, 0.0, 30.0, 0.0, 1.0),
        solid('BOYLAT', 30.0, 40.0, 30.0, 40.0, 1.0)]))
    head_on = rig.add('head_on', 0.0, 0.0, 90.0)
    glancing = rig.add('glancing', 0.0, 38.4, 90.0)
    rig.run(25.0, {'head_on': 1.0, 'glancing': 1.0})
    assert bow_east(rig, head_on) < 30.0
    assert abs(head_on.speed) < 0.3
    assert rig.en(glancing)[0] > 33.0, 'it slid around the buoy'
    objects = {(e['platform'], e['other']) for e in rig.events}
    assert ('head_on', 'BOYLAT') in objects


def test_a_charted_depth_blocks_only_while_the_water_over_it_is_too_shallow(
        mdl, world):
    # a rock with 0.2 m over it and a boat that draws 0.4 m
    for tide, blocked in ((0.0, True), (0.1, True), (1.0, False)):
        rig = Rig(mdl, world, terrain=False, tide=tide)
        rig.collisions.sources.append(source_for(rig, [
            solid('UWTROC', 20.0, 0.0, 20.0, 0.0, 1.0, depth=0.2)]))
        a = rig.add('a', 0.0, 0.0, 90.0)
        rig.run(20.0, {'a': 1.0})
        assert (rig.en(a)[0] < 20.0) == blocked, tide


def test_an_object_without_a_charted_depth_blocks_at_every_tide(mdl, world):
    rig = Rig(mdl, world, terrain=False, tide=5.0)
    rig.collisions.sources.append(source_for(rig, [
        solid('WRECKS', 20.0, 0.0, 20.0, 0.0, 1.5)]))
    a = rig.add('a', 0.0, 0.0, 90.0)
    rig.run(20.0, {'a': 1.0})
    assert bow_east(rig, a) < 20.0


def test_objects_far_from_the_boat_do_not_matter(mdl, world):
    rig = Rig(mdl, world, terrain=False)
    rig.collisions.sources.append(source_for(rig, [
        solid('SLCONS', 5000.0, -60.0, 5000.0, 60.0, 1.0),
        solid('BOYLAT', 0.0, -500.0, 0.0, -500.0, 1.0)]))
    a = rig.add('a', 0.0, 0.0, 90.0)
    rig.run(20.0, {'a': 1.0})
    assert rig.en(a)[0] > 30.0
    assert not rig.events


def test_a_long_step_is_checked_in_pieces_against_a_pier(mdl, world):
    mdl.max_step = 10.0
    rig = Rig(mdl, world, terrain=False)
    rig.collisions.sources.append(source_for(rig, [
        solid('SLCONS', 30.0, -60.0, 30.0, 60.0, 1.0)]))
    a = rig.add('a', 5.0, 0.0, 90.0)
    a.speed = 2.75
    a.update(1.0, 0.0, ns(0.0), apply_noise=False)
    a.update(1.0, 0.0, ns(10.0), apply_noise=False)
    assert bow_east(rig, a) < 30.0


def test_a_boat_lying_across_a_pier_is_pushed_clear(mdl, world):
    rig = Rig(mdl, world, terrain=False)
    rig.collisions.sources.append(source_for(rig, [
        solid('SLCONS', 0.0, -60.0, 0.0, 60.0, 1.0)]))
    a = rig.add('a', 0.0, 0.0, 90.0)   # its hull runs across the pier
    rig.run(1.0, {})
    east, _ = rig.en(a)
    assert abs(east) > 2.0 + 1.0 - 0.1, 'bow to stern clear of the pier'


# the real cells ------------------------------------------------------------

def test_the_installed_cells_give_every_expected_class():
    primitives, project, counts = charts.load(str(ENC_DIR))
    for klass in ('SLCONS', 'PONTON', 'PILPNT', 'BOYLAT', 'BOYSPP', 'BCNLAT',
                  'UWTROC', 'WRECKS', 'OBSTRN'):
        assert counts.get(klass, 0) > 0, klass
    assert len(primitives) == sum(counts.values()) > 5000
    # Cod Rock Lighted Buoy 5, 28 m north of the demo's first start
    x, y = project(math.radians(43.074547), math.radians(-70.711249))
    near = [p for p in primitives
            if p.klass == 'BOYLAT' and math.hypot(p.x0 - x, p.y0 - y) < 1.0]
    assert near, 'the buoy is in the primitives'


def test_the_cells_cover_the_demo_area_and_nothing_is_far_away():
    primitives, project, counts = charts.load(str(ENC_DIR))
    x0, y0 = project(math.radians(43.0537), math.radians(-70.7405))
    x1, y1 = project(math.radians(43.0937), math.radians(-70.6695))
    inside = [p for p in primitives
              if min(x0, x1) <= p.x0 <= max(x0, x1)
              and min(y0, y1) <= p.y0 <= max(y0, y1)]
    assert len(inside) > 0.5 * len(primitives)


def _clear_approach(primitives):
    """Return ``(pier, sign)``: a long charted pier and the side to come from.

    The corridor from 25 m out to the pier's middle must hold no other
    primitive within 4 m, so the only thing the boat can meet is the pier.
    """
    piers = sorted(
        (p for p in primitives if p.klass == 'SLCONS'
         and math.hypot(p.x1 - p.x0, p.y1 - p.y0) > 15.0),
        key=lambda p: -math.hypot(p.x1 - p.x0, p.y1 - p.y0))
    for pier in piers:
        length = math.hypot(pier.x1 - pier.x0, pier.y1 - pier.y0)
        mx, my = (pier.x0 + pier.x1) / 2.0, (pier.y0 + pier.y1) / 2.0
        nx, ny = -(pier.y1 - pier.y0) / length, (pier.x1 - pier.x0) / length
        for sign in (1.0, -1.0):
            start = (mx + sign * nx * 28.0, my + sign * ny * 28.0)
            end = (mx + sign * nx * (pier.radius + 0.5),
                   my + sign * ny * (pier.radius + 0.5))
            if all(p is pier or _distance_to_segment(p, start, end) > 4.0
                   for p in primitives):
                return pier, sign
    raise AssertionError('no charted pier with a clear approach')


def _distance_to_segment(p, a, b):
    """Distance in metres from a primitive's nearest point to segment a-b."""
    near, far = collision.segment_closest(
        (p.x0, p.y0), (p.x1, p.y1), a, b)
    return math.hypot(near[0] - far[0], near[1] - far[1]) - p.radius


def test_a_boat_driven_at_a_charted_pier_of_the_real_cells_stops(mdl, world):
    primitives, project, _ = charts.load(str(ENC_DIR))
    pier, sign = _clear_approach(primitives)
    length = math.hypot(pier.x1 - pier.x0, pier.y1 - pier.y0)
    mx, my = (pier.x0 + pier.x1) / 2.0, (pier.y0 + pier.y1) / 2.0
    nx, ny = -(pier.y1 - pier.y0) / length, (pier.x1 - pier.x0) / length
    start_x, start_y = mx + sign * nx * 25.0, my + sign * ny * 25.0
    heading = math.degrees(math.atan2(-sign * nx, -sign * ny)) % 360.0

    rig = Rig(mdl, world, terrain=False)
    rig.collisions.sources.append(
        collision.ChartedObjectSource(primitives, project))
    d = rig.add('a', 0.0, 0.0, heading)
    # the cells use their own frame: put the boat at its projected start
    lat, lon = _unproject(project, start_x, start_y)
    d.set(math.degrees(lat), math.degrees(lon), heading)
    d.last_update = None

    rig.run(30.0, {'a': 1.0})
    x, y = project(d.latitude, d.longitude)
    gap = abs((x - mx) * nx + (y - my) * ny)
    # bow to centre: half the hull axis (1.15) plus its radius (0.85) plus
    # the pier's half width
    assert gap == pytest.approx(2.0 + pier.radius, abs=0.6)
    assert [e['other'] for e in rig.events][:1] == ['SLCONS']
    rig.run(8.0, {'a': -1.0})
    x2, y2 = project(d.latitude, d.longitude)
    assert abs((x2 - mx) * nx + (y2 - my) * ny) > gap + 3.0


def _unproject(project, x, y):
    """Find the (lat, lon) radians that project to (x, y) by iteration."""
    lat, lon = math.radians(43.07), math.radians(-70.71)
    for _ in range(20):
        px, py = project(lat, lon)
        east, north = x - px, y - py
        lat, lon = collision.move_en(lat, lon, east, north)
    return lat, lon


def test_the_package_ships_the_cells_it_documents():
    names = sorted(os.listdir(ENC_DIR))
    for needed in ('US5PSMCC.000', 'US5PSMCD.000', 'US5PSMCD.001',
                   'README.md', 'NOAA_USERAGREEMENT.TXT'):
        assert needed in names


# review findings ------------------------------------------------------------

def test_two_walls_of_one_class_both_reach_the_speed_rule(mdl, world):
    rig = Rig(mdl, world, terrain=False)
    # a corner: a north-south wall ahead and an east-west one beside it, same class
    rig.collisions.sources.append(source_for(rig, [
        solid('SLCONS', 20.0, -60.0, 20.0, 60.0, 1.0),
        solid('SLCONS', -60.0, 1.8, 60.0, 1.8, 1.0)]))
    a = rig.add('a', 10.0, 0.0, 90.0)
    rig.run(15.0, {'a': 1.0})
    assert abs(a.speed) < 0.3, 'the wall ahead must stop it, whatever the other wall did'
    assert bow_east(rig, a) < 20.0


def test_the_charted_depth_boundary_does_not_block_exactly_at_the_draft(mdl, world):
    # depth + tide - draft == 0: the keel just clears
    rig = Rig(mdl, world, terrain=False, tide=0.25)
    mdl.draft = 0.5
    rig.collisions.sources.append(source_for(rig, [
        solid('UWTROC', 20.0, 0.0, 20.0, 0.0, 1.0, depth=0.25)]))
    a = rig.add('a', 0.0, 0.0, 90.0)
    rig.run(20.0, {'a': 1.0})
    assert rig.en(a)[0] > 20.0


def test_charted_soundings_reach_the_primitives():
    primitives, _, _ = charts.load(str(ENC_DIR))
    sounded = [p for p in primitives if p.klass == 'UWTROC' and p.depth is not None]
    assert sounded, 'some charted rocks carry a depth'
    assert all(p.depth is not None for p in sounded)
    assert any(p.klass == 'UWTROC' and p.depth is None for p in primitives)


def test_an_unreadable_cell_is_named_in_the_error(tmp_path):
    bad = tmp_path / 'US9BAD01.000'
    bad.write_bytes(b'this is not an S-57 cell')
    with pytest.raises(Exception, match='US9BAD01'):
        charts.load(str(bad))


def test_cells_too_far_apart_are_refused_naming_the_outermost(monkeypatch):
    monkeypatch.setattr(charts, 'MAX_SPAN_DEGREES', 0.01)
    with pytest.raises(ValueError, match='US5PSMC'):
        charts.load(str(ENC_DIR))


def test_no_charted_objects_found_is_an_empty_result_not_a_crash():
    primitives, project, counts = charts.load(
        str(ENC_DIR), ['%s=0' % k for k in charts.DEFAULT_FOOTPRINTS])
    assert primitives == [] and counts == {}
