"""Contact resolution of ``asv_sim`` (issue #111): blocking only.

Pure geometry, then ``Dynamics`` with a ``Collisions`` resolver on a
synthetic bathymetry GeoTIFF (UTM 19N, 2 m cells) built here:

- water 10 m deep west of a straight shore at 50 m east of the grid origin;
- land (depth -2 m) east of it, with a 1 m deep shelf from 30 to 50 m east
  of the origin;
- no data north of 120 m.

The grid is a few degrees off true north (UTM grid convergence, 1.2 degrees
at Portsmouth), so distances to the shore are checked to a cell and a bit.

Runs under plain pytest (``colcon test``); no launch_test runner needed.
"""

import math
import signal

from asv_sim import collision
from asv_sim import dynamics
from asv_sim import model
import pytest
import rclpy
import rclpy.node
from rclpy.parameter import Parameter
from rclpy.time import Time
import synthetic_grid

SHORE_EAST = synthetic_grid.SHORE_EAST
SHELF_EAST = synthetic_grid.SHELF_EAST
NODATA_NORTH = synthetic_grid.NODATA_NORTH
TOL = 3.0          # a cell, plus the grid's rotation over the run
DEFAULT_HULL = (4.0, 1.7, 0.4)


class Recorder:
    """Stand-in for a logger: keeps (level, message) pairs."""

    def __init__(self):
        self.records = []

    def info(self, message):
        self.records.append(('info', message))

    def warning(self, message):
        self.records.append(('warning', message))

    def error(self, message):
        self.records.append(('error', message))

    def at(self, level):
        return [m for lv, m in self.records if lv == level]


class Tide:
    """Environment stand-in: a settable tide and nothing else."""

    def __init__(self, level=0.0):
        self.level = level

    def getTide(self, timestamp):  # noqa: N802
        return self.level

    def getCurrent(self, lat, lon, apply_noise):  # noqa: N802
        return None

    def getWaves(self, timestamp):  # noqa: N802
        return {'heave': 0.0, 'roll': 0.0, 'pitch': 0.0}

    def getEllipsoidalAltitude(self, timestamp):  # noqa: N802
        return 0.0


def ns(seconds):
    return Time(nanoseconds=int(round(seconds * 1e9)))


@pytest.fixture
def mdl():
    rclpy.init()
    node = rclpy.node.Node('collision_test')
    try:
        yield model.Model('demo', node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


@pytest.fixture(scope='module')
def origin_and_grid(tmp_path_factory):
    path = str(tmp_path_factory.mktemp('grid') / 'truth.tif')
    lat, lon = synthetic_grid.write_grid(path)
    return lat, lon, path


@pytest.fixture
def world(origin_and_grid):
    from mbes_sim.bathy_grid import BathyGrid
    lat, lon, path = origin_and_grid
    return lat, lon, BathyGrid(path)


class Rig:
    """Boats on the synthetic grid, stepped by hand."""

    def __init__(self, mdl, world, boats=True, terrain=True, tide=0.0):
        self.lat0, self.lon0, grid = world
        self.mdl = mdl
        self.log = Recorder()
        self.events = []
        self.collisions = collision.Collisions(
            grid=grid if terrain else None, boats=boats,
            emit=self.events.append, logger=self.log)
        self.env = Tide(tide)
        self.boats = {}
        self.frozen = {}
        self.t = 0.0

    def add(self, name, east, north, heading, frozen=False):
        """Add a boat; a frozen one stays put (a moored target)."""
        d = dynamics.Dynamics(
            self.mdl, self.env, name=name, logger=self.log,
            contact=self.collisions)
        self.collisions.register(d)
        self.place(d, east, north, heading)
        self.boats[name] = d
        if frozen:
            self.frozen[name] = (d.latitude, d.longitude)
        return d

    def place(self, d, east, north, heading):
        lat, lon = collision.move_en(
            math.radians(self.lat0), math.radians(self.lon0), east, north)
        d.set(math.degrees(lat), math.degrees(lon), heading)
        d.last_update = None

    def en(self, d):
        return collision.offset_en(
            math.radians(self.lat0), math.radians(self.lon0),
            d.latitude, d.longitude)

    def run(self, seconds, throttles, step=0.05, watch=None):
        """Step every boat; ``throttles`` maps name to throttle.

        :param watch: Called after every step.
        """
        steps = int(round(seconds / step))
        for _ in range(steps):
            self.t += step
            for name, d in self.boats.items():
                d.update(throttles.get(name, 0.0), 0.0, ns(self.t),
                         apply_noise=False)
                if name in self.frozen:
                    d.speed = 0.0
                    d.latitude, d.longitude = self.frozen[name]
            if watch is not None:
                watch()


def overlap(a, b):
    """Return the capsule overlap in metres of two ``Dynamics`` (0: none)."""
    east, north = collision.offset_en(
        a.latitude, a.longitude, b.latitude, b.longitude)
    hit = collision.capsule_penetration(
        collision.capsule_axis((0.0, 0.0), a.heading, a.model.length,
                               a.model.beam),
        collision.capsule_axis((east, north), b.heading, b.model.length,
                               b.model.beam))
    return 0.0 if hit is None else hit[0]


# geometry ------------------------------------------------------------------

def test_capsules_side_by_side_overlap_by_the_missing_gap():
    a = collision.capsule_axis((0.0, 0.0), 0.0, 4.0, 1.7)
    b = collision.capsule_axis((1.0, 0.0), 0.0, 4.0, 1.7)
    depth, normal = collision.capsule_penetration(a, b)
    assert depth == pytest.approx(0.7)
    assert normal == pytest.approx((-1.0, 0.0))


@pytest.mark.parametrize('gap, depth', [(3.0, 1.0), (4.0, None),
                                        (5.0, None)])
def test_capsules_end_to_end_touch_at_the_length(gap, depth):
    a = collision.capsule_axis((0.0, 0.0), 0.0, 4.0, 1.7)
    b = collision.capsule_axis((0.0, gap), 0.0, 4.0, 1.7)
    hit = collision.capsule_penetration(a, b)
    if depth is None:
        assert hit is None
    else:
        assert hit[0] == pytest.approx(depth)
        assert hit[1] == pytest.approx((0.0, -1.0))


def test_capsules_with_crossing_axes_still_separate():
    a = collision.capsule_axis((0.0, 0.0), 0.0, 4.0, 1.7)
    b = collision.capsule_axis((0.0, 0.0), math.pi / 2, 4.0, 1.7)
    depth, normal = collision.capsule_penetration(a, b)
    assert depth == pytest.approx(1.7 + 1.15)
    assert math.hypot(*normal) == pytest.approx(1.0)


def test_degenerate_segments_do_not_divide_by_zero():
    point = ((1.0, 1.0), (1.0, 1.0))
    assert collision.segment_closest(
        point[0], point[1], (0.0, 0.0), (0.0, 0.0)) == (
        (1.0, 1.0), (0.0, 0.0))
    near, far = collision.segment_closest(
        (0.0, 0.0), (0.0, 0.0), (1.0, -1.0), (1.0, 1.0))
    assert near == (0.0, 0.0) and far == pytest.approx((1.0, 0.0))


# boat to boat --------------------------------------------------------------

def test_boats_driven_at_each_other_never_overlap_and_stop_touching(
        mdl, world):
    rig = Rig(mdl, world, terrain=False)
    a = rig.add('a', -15.0, 0.0, 90.0)
    b = rig.add('b', 15.0, 0.0, 270.0)
    worst = [0.0]

    def watch():
        worst[0] = max(worst[0], overlap(a, b))

    rig.run(30.0, {'a': 1.0, 'b': 1.0}, watch=watch)
    assert worst[0] < 0.05
    ea, na = rig.en(a)
    eb, nb = rig.en(b)
    # bow to bow: two lengths of hull between the centres at least
    assert math.hypot(eb - ea, nb - na) == pytest.approx(4.0, abs=0.1)
    assert abs(a.speed) < 0.2 and abs(b.speed) < 0.2


def test_a_boat_can_always_back_out_of_contact(mdl, world):
    rig = Rig(mdl, world, terrain=False)
    a = rig.add('a', -8.0, 0.0, 90.0)
    b = rig.add('b', 0.0, 0.0, 90.0, frozen=True)
    rig.run(10.0, {'a': 1.0})
    before = math.hypot(*[x - y for x, y in zip(rig.en(a), rig.en(b))])
    rig.run(10.0, {'a': -1.0})
    after = math.hypot(*[x - y for x, y in zip(rig.en(a), rig.en(b))])
    assert after > before + 3.0
    assert overlap(a, b) == 0.0


def test_the_other_boat_is_not_moved_by_a_contact(mdl, world):
    rig = Rig(mdl, world, terrain=False)
    rig.add('a', -8.0, 0.0, 90.0)
    b = rig.add('b', 0.0, 0.0, 90.0)
    rig.run(10.0, {'a': 1.0})
    # the same boat alone (idle thrust creeps it forward either way)
    twin = Rig(mdl, world, terrain=False)
    twin_b = twin.add('b', 0.0, 0.0, 90.0)
    twin.run(10.0, {})
    assert rig.en(b) == pytest.approx(twin.en(twin_b), abs=1e-6)


def test_boats_placed_on_top_of_each_other_are_pushed_apart(mdl, world):
    rig = Rig(mdl, world, terrain=False)
    a = rig.add('a', 0.0, 0.0, 0.0)
    b = rig.add('b', 0.3, 0.0, 0.0)
    rig.run(1.0, {})
    assert overlap(a, b) < 1e-6 and overlap(b, a) < 1e-6
    assert rig.events and rig.events[0]['kind'] == collision.KIND_BOAT


def test_boats_pass_through_each_other_when_boats_are_off(mdl, world):
    rig = Rig(mdl, world, boats=False, terrain=False)
    a = rig.add('a', -8.0, 0.0, 90.0)
    rig.add('b', 0.0, 0.0, 90.0)
    rig.run(10.0, {'a': 1.0})
    assert rig.en(a)[0] > 3.0
    assert not rig.events


def test_a_stalled_gap_does_not_tunnel_through_a_boat(mdl, world):
    rig = Rig(mdl, world, terrain=False)
    a = rig.add('a', -20.0, 0.0, 90.0)
    b = rig.add('b', 0.0, 0.0, 90.0, frozen=True)
    a.speed = 2.75
    a.update(1.0, 0.0, ns(0.0), apply_noise=False)
    a.update(1.0, 0.0, ns(10.0), apply_noise=False)
    assert rig.en(a)[0] < rig.en(b)[0]
    assert overlap(a, b) < 0.05


# terrain -------------------------------------------------------------------

def bow_east(rig, d):
    return rig.en(d)[0] + d.model.length / 2.0


def test_a_boat_driven_at_the_shore_stops_at_it(mdl, world):
    rig = Rig(mdl, world)
    a = rig.add('a', 0.0, 0.0, 90.0)
    rig.run(40.0, {'a': 1.0})
    assert bow_east(rig, a) <= SHORE_EAST + TOL
    assert bow_east(rig, a) >= SHELF_EAST + 10.0
    assert abs(a.speed) < 0.3


def test_a_boat_at_forty_five_degrees_slides_along_the_shore(mdl, world):
    rig = Rig(mdl, world)
    a = rig.add('a', 0.0, 0.0, 45.0)
    rig.run(30.0, {'a': 1.0})
    east, north = rig.en(a)
    assert north > 15.0
    assert east + 2.0 <= SHORE_EAST + TOL


def test_a_boat_that_hit_the_shore_can_back_off(mdl, world):
    rig = Rig(mdl, world)
    a = rig.add('a', 0.0, 0.0, 90.0)
    rig.run(40.0, {'a': 1.0})
    stuck = rig.en(a)[0]
    rig.run(10.0, {'a': -1.0})
    assert rig.en(a)[0] < stuck - 3.0


def test_no_data_is_a_wall(mdl, world):
    rig = Rig(mdl, world)
    a = rig.add('a', 0.0, 0.0, 0.0)
    rig.run(60.0, {'a': 1.0})
    assert rig.en(a)[1] + 2.0 <= NODATA_NORTH + TOL


def test_a_boat_off_the_grid_cannot_go_further_off_it(mdl, world):
    rig = Rig(mdl, world)
    a = rig.add('a', 0.0, 0.0, 270.0)
    rig.run(120.0, {'a': 1.0})
    # the grid ends 300 m west of the origin
    assert rig.en(a)[0] - 2.0 >= -300.0 - TOL


def test_a_boat_that_starts_aground_may_leave_but_not_go_shallower(
        mdl, world):
    rig = Rig(mdl, world)
    a = rig.add('a', 60.0, 0.0, 270.0)
    rig.run(40.0, {'a': 1.0})
    assert rig.en(a)[0] < SHORE_EAST - 5.0

    b = rig.add('b', 60.0, 20.0, 90.0)
    here = rig.en(b)[0]
    rig.run(10.0, {'b': 1.0})
    assert rig.en(b)[0] >= here


def test_low_tide_grounds_a_boat_on_the_shelf_and_high_tide_frees_it(
        mdl, world):
    rig = Rig(mdl, world, tide=-0.8)
    a = rig.add('a', 0.0, 0.0, 90.0)
    rig.run(40.0, {'a': 1.0})
    assert bow_east(rig, a) <= SHELF_EAST + TOL
    rig.env.level = 0.0
    rig.run(20.0, {'a': 1.0})
    assert bow_east(rig, a) > SHELF_EAST + 8.0


def test_draft_decides_where_a_boat_grounds(mdl, world):
    mdl.draft = 1.5
    rig = Rig(mdl, world)
    a = rig.add('a', 0.0, 0.0, 90.0)
    rig.run(40.0, {'a': 1.0})
    assert bow_east(rig, a) <= SHELF_EAST + TOL


def test_a_stalled_gap_does_not_tunnel_through_the_shore(mdl, world):
    rig = Rig(mdl, world)
    a = rig.add('a', 25.0, 0.0, 90.0)
    a.speed = 2.75
    a.update(1.0, 0.0, ns(0.0), apply_noise=False)
    a.update(1.0, 0.0, ns(10.0), apply_noise=False)
    assert bow_east(rig, a) <= SHORE_EAST + TOL


def test_nothing_blocks_a_boat_without_a_resolver(mdl, world):
    d = dynamics.Dynamics(mdl, Tide(), name='free', logger=Recorder())
    d.set(world[0], world[1], 90.0)
    d.speed = 2.0
    run_to = 0.0
    d.update(1.0, 0.0, ns(run_to), apply_noise=False)
    for i in range(1, 400):
        d.update(1.0, 0.0, ns(i * 0.05), apply_noise=False)
    assert d.speed > 2.0


def test_a_boat_is_never_damaged_or_reset(mdl, world):
    rig = Rig(mdl, world)
    a = rig.add('a', 0.0, 0.0, 90.0)
    rig.run(40.0, {'a': 1.0})
    stuck = rig.en(a)
    rig.run(5.0, {'a': 1.0})
    # still where it was, still able to move when told to
    assert rig.en(a) == pytest.approx(stuck, abs=0.02)
    assert abs(a.speed) < 0.2
    rig.run(5.0, {'a': -1.0})
    assert rig.en(a)[0] < stuck[0]
    assert not rig.log.at('error')


# events --------------------------------------------------------------------

def test_one_event_per_contact_not_one_per_step(mdl, world):
    rig = Rig(mdl, world)
    rig.add('a', 0.0, 0.0, 90.0)
    rig.run(40.0, {'a': 1.0})
    terrain = [e for e in rig.events if e['kind'] == collision.KIND_TERRAIN]
    assert len(terrain) == 1
    event = terrain[0]
    assert event['platform'] == 'a' and event['other'] == ''
    assert event['closing_speed'] > 0.0
    assert math.isfinite(event['latitude'])
    assert len(rig.log.at('info')) == 1


def test_a_second_contact_after_separating_is_a_second_event(mdl, world):
    rig = Rig(mdl, world)
    rig.add('a', 0.0, 0.0, 90.0)
    rig.run(40.0, {'a': 1.0})
    rig.run(8.0, {'a': -1.0})
    rig.run(20.0, {'a': 1.0})
    assert len(rig.events) == 2


def test_a_boat_contact_names_the_other_boat(mdl, world):
    rig = Rig(mdl, world, terrain=False)
    rig.add('a', -8.0, 0.0, 90.0)
    rig.add('b', 0.0, 0.0, 90.0, frozen=True)
    rig.run(10.0, {'a': 1.0})
    assert len(rig.events) == 1
    assert rig.events[0]['other'] == 'b'
    assert rig.events[0]['kind'] == collision.KIND_BOAT


# robustness ----------------------------------------------------------------

class Broken:

    def resolve(self, *args):
        raise ValueError('contact bug')


def test_a_failure_in_contact_code_is_logged_and_does_not_reset_the_boat(
        mdl):
    log = Recorder()
    d = dynamics.Dynamics(mdl, name='boat', logger=log, contact=Broken())
    d.update(1.0, 0.0, ns(0.0), apply_noise=False)
    for i in range(1, 100):
        d.update(1.0, 0.0, ns(i * 0.05), apply_noise=False)
    assert d.speed > 0.1
    errors = log.at('error')
    assert len(errors) == 1 and 'contact resolution failed' in errors[0]


def test_a_boat_with_a_non_finite_position_is_left_alone(mdl, world):
    rig = Rig(mdl, world)
    a = rig.add('a', 0.0, 0.0, 90.0)
    a.latitude = math.nan
    rig.collisions.resolve(a, 0.7, -1.2, ns(1.0), 0.05)
    assert math.isnan(a.latitude)


# parameters ----------------------------------------------------------------

def test_the_hull_defaults_are_the_cworker_4(mdl):
    assert (mdl.length, mdl.beam, mdl.draft) == DEFAULT_HULL


def test_a_hull_shorter_than_it_is_wide_is_refused():
    rclpy.init()
    node = rclpy.node.Node('collision_param_test')
    try:
        mdl = model.Model('demo', node)
        for name, value in (('length', 1.0), ('beam', 5.0),
                            ('draft', 0.0), ('beam', -1.0)):
            result = node.set_parameters(
                [Parameter('models.demo.' + name, value=value)])[0]
            assert not result.successful, (name, value)
        assert (mdl.length, mdl.beam) == DEFAULT_HULL[:2]
        assert node.set_parameters(
            [Parameter('models.demo.length', value=6.0)])[0].successful
        assert mdl.length == 6.0
    finally:
        node.destroy_node()
        rclpy.shutdown()


# review findings (round 1) -------------------------------------------------

@pytest.mark.parametrize('heading_a, heading_b, centre', [
    (0.0, math.pi / 2, (0.0, 0.0)),
    (0.0, math.pi / 2, (0.4, -0.3)),
    (0.3, 1.1, (0.0, 0.0)),
    (0.0, 0.0, (0.0, 0.0)),
    (0.0, math.pi, (0.0, 0.5)),
])
@pytest.mark.parametrize('length, beam', [(4.0, 1.7), (20.0, 1.0)])
def test_overlapping_capsules_are_separated_by_the_returned_push(
        heading_a, heading_b, centre, length, beam):
    a = collision.capsule_axis(centre, heading_a, length, beam)
    b = collision.capsule_axis((0.0, 0.0), heading_b, length, beam)
    depth, normal = collision.capsule_penetration(a, b)
    moved = collision.capsule_axis(
        (centre[0] + normal[0] * depth, centre[1] + normal[1] * depth),
        heading_a, length, beam)
    left = collision.capsule_penetration(moved, b)
    assert left is None or left[0] < 1e-6, left


def test_a_hull_may_be_as_short_as_it_is_wide():
    a = collision.capsule_axis((0.0, 0.0), 0.0, 1.7, 1.7)
    b = collision.capsule_axis((0.0, 0.0), 0.0, 1.7, 1.7)
    depth, normal = collision.capsule_penetration(a, b)
    assert depth == pytest.approx(1.7) and math.hypot(*normal) == 1.0


def test_a_turn_that_swings_the_hull_onto_land_is_put_back(mdl, world):
    rig = Rig(mdl, world)
    a = rig.add('a', 48.5, 0.0, 0.0)
    a.speed = 0.0
    lat, lon = a.latitude, a.longitude
    a.heading = math.pi / 2     # the bow would now be over land
    a.yaw_rate = 0.3
    rig.collisions.resolve(a, lat, lon, ns(1.0), 0.05, last_heading=0.0)
    assert a.heading == pytest.approx(0.0)
    assert a.yaw_rate == 0.0
    assert [e['kind'] for e in rig.events] == [collision.KIND_TERRAIN]


def test_a_turn_in_open_water_is_left_alone(mdl, world):
    rig = Rig(mdl, world)
    a = rig.add('a', 0.0, 0.0, 0.0)
    lat, lon = a.latitude, a.longitude
    a.heading = math.pi / 2
    rig.collisions.resolve(a, lat, lon, ns(1.0), 0.05, last_heading=0.0)
    assert a.heading == pytest.approx(math.pi / 2)
    assert not rig.events


def test_a_boat_off_the_grid_cannot_sail_onto_the_land_of_the_grid(
        mdl, world):
    rig = Rig(mdl, world)
    a = rig.add('a', -330.0, 0.0, 90.0)
    rig.run(160.0, {'a': 1.0})
    assert rig.en(a)[0] > -300.0, 'it did not even reach the grid'
    assert bow_east(rig, a) <= SHORE_EAST + TOL
    warnings = rig.log.at('warning')
    assert len(warnings) == 1 and "'a'" in warnings[0]


def test_a_long_step_is_checked_in_pieces_against_the_shore(mdl, world):
    mdl.max_step = 10.0
    rig = Rig(mdl, world)
    a = rig.add('a', 25.0, 0.0, 90.0)
    a.speed = 2.75
    a.update(1.0, 0.0, ns(0.0), apply_noise=False)
    a.update(1.0, 0.0, ns(10.0), apply_noise=False)
    assert bow_east(rig, a) <= SHORE_EAST + TOL


def test_a_long_step_is_checked_in_pieces_against_a_boat(mdl, world):
    mdl.max_step = 10.0
    rig = Rig(mdl, world, terrain=False)
    a = rig.add('a', -20.0, 0.0, 90.0)
    b = rig.add('b', 0.0, 0.0, 90.0, frozen=True)
    a.speed = 2.75
    a.update(1.0, 0.0, ns(0.0), apply_noise=False)
    a.update(1.0, 0.0, ns(10.0), apply_noise=False)
    assert rig.en(a)[0] < rig.en(b)[0]
    assert overlap(a, b) < 0.05


def test_a_failing_event_publisher_does_not_leave_the_boat_inside(mdl, world):
    rig = Rig(mdl, world, terrain=False)

    def broken(event):
        raise RuntimeError('publisher is gone')

    rig.collisions.emit = broken
    a = rig.add('a', -8.0, 0.0, 90.0)
    rig.add('b', 0.0, 0.0, 90.0, frozen=True)
    rig.run(10.0, {'a': 1.0})
    assert overlap(a, rig.boats['b']) < 0.05
    assert rig.log.at('warning')


def test_a_boat_on_the_other_side_of_the_world_does_not_hang_the_resolver(
        mdl, world):
    rig = Rig(mdl, world, terrain=False)
    a = rig.add('a', 0.0, 0.0, 90.0)
    b = rig.add('b', 0.0, 0.0, 90.0)
    b.latitude = math.radians(0.3)
    b.longitude = math.radians(179.9)
    a.latitude = 0.0
    a.longitude = 0.0

    def stuck(signum, frame):
        raise AssertionError('the resolver is stuck in the geodesic')

    previous = signal.signal(signal.SIGALRM, stuck)
    signal.alarm(10)
    try:
        for i in range(1, 20):
            a.update(1.0, 0.0, ns(i * 0.05), apply_noise=False)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    assert not rig.events


def test_a_boat_with_a_non_finite_position_is_not_an_obstacle(mdl, world):
    rig = Rig(mdl, world, terrain=False)
    a = rig.add('a', 0.0, 0.0, 90.0)
    b = rig.add('b', 5.0, 0.0, 90.0)
    b.latitude = math.nan
    for i in range(1, 20):
        a.update(1.0, 0.0, ns(i * 0.05), apply_noise=False)
    assert math.isfinite(a.latitude)


def test_the_tide_is_only_read_for_terrain(mdl, world):
    class Counting(Tide):
        reads = 0

        def getTide(self, timestamp):  # noqa: N802
            Counting.reads += 1
            return 0.0

    rig = Rig(mdl, world, terrain=False)
    rig.env = Counting()
    a = rig.add('a', 0.0, 0.0, 90.0)
    a.update(1.0, 0.0, ns(0.0), apply_noise=False)
    a.update(1.0, 0.0, ns(0.05), apply_noise=False)
    # Dynamics itself reads it once per update for its diagnostics
    assert Counting.reads == 2


def test_a_short_boat_can_be_declared_with_overrides():
    rclpy.init(args=['--ros-args', '-p', 'models.tiny.length:=1.2',
                     '-p', 'models.tiny.beam:=0.5'])
    node = rclpy.node.Node('collision_small_hull_test')
    try:
        tiny = model.Model('tiny', node)
        assert (tiny.length, tiny.beam) == (1.2, 0.5)
    finally:
        node.destroy_node()
        rclpy.shutdown()


def test_a_hull_declared_shorter_than_it_is_wide_is_refused_at_start():
    rclpy.init(args=['--ros-args', '-p', 'models.odd.length:=1.0'])
    node = rclpy.node.Node('collision_odd_hull_test')
    try:
        with pytest.raises(ValueError, match='shorter than beam'):
            model.Model('odd', node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


def test_between_a_boat_and_the_shore_the_shore_wins(mdl, world):
    rig = Rig(mdl, world)
    a = rig.add('a', 44.0, 0.0, 90.0)
    rig.add('b', 40.0, 0.0, 90.0, frozen=True)
    rig.run(20.0, {'a': 1.0})
    assert bow_east(rig, a) <= SHORE_EAST + TOL


def test_a_boat_sliding_along_the_shore_keeps_its_heading_and_yaw_rate(
        mdl, world):
    rig = Rig(mdl, world)
    a = rig.add('a', 48.9, 0.0, 0.0)
    prev = (a.latitude, a.longitude)
    # moved 0.3 m east, so its side is now over land, while turning through
    # north (6.28 rad to 0.01 rad)
    a.latitude, a.longitude = collision.move_en(
        prev[0], prev[1], 0.3, 0.0)
    a.heading = 0.01
    a.speed = 1.0
    a.yaw_rate = 0.2
    rig.collisions.resolve(a, prev[0], prev[1], ns(1.0), 0.05,
                           last_heading=6.28)
    assert rig.events, 'the test must make contact'
    assert a.heading == 0.01
    assert a.yaw_rate == 0.2
