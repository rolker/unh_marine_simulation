"""In-process test: several asv_sim platforms share one node.

Builds one ``AsvSim`` node with several platforms (synthetic names, not the
demo roster) from parameter files, and drives it from a second node in the
same process with bounded ``spin_once`` loops. Checks that

- every platform keeps its own start pose, ``mru_frame`` and model (one
  platform uses a second model so a mix-up shows),
- ``set_pose``, throttle and ``sim_reset`` act on one platform only,
- ``set_pose`` refuses a pose that is not on Earth instead of freezing the node,
- every key in ``config/demo.yaml`` is a declared ``Model`` parameter
  (``asv_sim`` silently ignores an override it did not declare).

Runs under plain pytest (``colcon test``); no launch_test runner needed.
"""

import math
import pathlib
import time

from asv_sim.asv_sim_node import AsvSim
from asv_sim_msgs.srv import SetPose
import pytest
import rclpy
from rclpy.executors import SingleThreadedExecutor
from sensor_msgs.msg import NavSatFix
from std_msgs.msg import Bool
from std_msgs.msg import Float32
import yaml

DEMO_CONFIG = pathlib.Path(__file__).resolve().parents[1] / 'config' / 'demo.yaml'

# name -> (lat, lon, heading); deliberately not the demo boat names.
PLATFORMS = {
    'alpha': (43.0700, -70.7100, 60.0),
    'bravo': (43.0710, -70.7090, 120.0),
    'charlie': (43.0720, -70.7080, 200.0),
}


# Platform -> model. The demo model is the shipped one; the second is a copy
# with a different top speed, so a platform bound to the wrong model fails.
MODELS = {'alpha': 'demo', 'bravo': 'demo', 'charlie': 'demo_fast'}
FAST_MAX_SPEED = 4.0


def _write_platform_file(path):
    # asv_sim defaults to a 1 m/s current; drift would swamp the isolation
    # checks, so switch it off.
    params = {'platforms': list(PLATFORMS), 'environment.current.speed': 0.0}
    demo = yaml.safe_load(DEMO_CONFIG.read_text())['asv_sim']['ros__parameters']
    for key, value in demo.items():
        params[key.replace('models.demo.', 'models.demo_fast.', 1)] = value
    params['models.demo_fast.max_speed'] = FAST_MAX_SPEED
    for name, (lat, lon, heading) in PLATFORMS.items():
        params['platforms.%s.model' % name] = MODELS[name]
        params['platforms.%s.start_lat' % name] = lat
        params['platforms.%s.start_lon' % name] = lon
        params['platforms.%s.start_heading' % name] = heading
        params['platforms.%s.mru_frame' % name] = '%s/motion_sensor' % name
    path.write_text(yaml.safe_dump({'asv_sim': {'ros__parameters': params}}))


def _metres(a, b):
    """Approximate distance in metres between two (lat, lon) pairs."""
    dlat = (b[0] - a[0]) * 111320.0
    dlon = (b[1] - a[1]) * 111320.0 * math.cos(math.radians(a[0]))
    return math.hypot(dlat, dlon)


class Rig:
    """The node under test, a driver node and the spin helper."""

    def __init__(self, tmp_path):
        platform_file = tmp_path / 'platforms.yaml'
        _write_platform_file(platform_file)
        rclpy.init(args=[
            '--ros-args',
            '--params-file', str(DEMO_CONFIG),
            '--params-file', str(platform_file),
        ])
        try:
            self._build()
        except BaseException:
            # A failed constructor must not leave rclpy initialised for the
            # next test.
            rclpy.shutdown()
            raise

    def _build(self):
        self.sim = AsvSim()
        self.driver = rclpy.create_node('test_multi_platform_driver')
        self.executor = SingleThreadedExecutor()
        self.executor.add_node(self.sim)
        self.executor.add_node(self.driver)

        self.fixes = {}
        self.throttle_pubs = {}
        self.reset_pubs = {}
        self.pose_clients = {}
        for name in PLATFORMS:
            self.driver.create_subscription(
                NavSatFix, '/%s/position' % name,
                lambda msg, n=name: self.fixes.__setitem__(
                    n, (msg.latitude, msg.longitude)), 10)
            self.throttle_pubs[name] = self.driver.create_publisher(
                Float32, '/%s/throttle' % name, 10)
            self.reset_pubs[name] = self.driver.create_publisher(
                Bool, '/asv_sim/%s/sim_reset' % name, 10)
            self.pose_clients[name] = self.driver.create_client(
                SetPose, '/asv_sim/%s/set_pose' % name)

    def spin(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.executor.spin_once(timeout_sec=0.02)

    def wait_for_fixes(self, timeout=10.0):
        deadline = time.monotonic() + timeout
        while len(self.fixes) < len(PLATFORMS):
            assert time.monotonic() < deadline, 'no position from %s' % (
                set(PLATFORMS) - set(self.fixes))
            self.executor.spin_once(timeout_sec=0.05)

    def fresh_fix(self, name, settle=0.6):
        """Return the next position message for a platform."""
        self.fixes.pop(name, None)
        deadline = time.monotonic() + settle + 5.0
        while name not in self.fixes:
            assert time.monotonic() < deadline, 'no fix for %s' % name
            self.executor.spin_once(timeout_sec=0.05)
        return self.fixes[name]

    def drive(self, name, throttle, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.throttle_pubs[name].publish(Float32(data=throttle))
            self.executor.spin_once(timeout_sec=0.05)

    def call_set_pose(self, name, lat, lon, heading=0.0, quaternion=None):
        """Call set_pose and return the response (success or refusal)."""
        client = self.pose_clients[name]
        deadline = time.monotonic() + 5.0
        while not client.service_is_ready():
            assert time.monotonic() < deadline, 'set_pose not available'
            self.executor.spin_once(timeout_sec=0.05)
        request = SetPose.Request()
        request.pose.pose.position.latitude = lat
        request.pose.pose.position.longitude = lon
        if quaternion is None:
            yaw = math.radians(90.0 - heading)
            quaternion = (0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0))
        (request.pose.pose.orientation.x, request.pose.pose.orientation.y,
         request.pose.pose.orientation.z, request.pose.pose.orientation.w) = quaternion
        future = client.call_async(request)
        while not future.done():
            assert time.monotonic() < deadline, 'set_pose timed out'
            self.executor.spin_once(timeout_sec=0.05)
        return future.result()

    def set_pose(self, name, lat, lon, heading):
        assert self.call_set_pose(name, lat, lon, heading).success
        self.spin(0.5)

    def close(self):
        self.executor.shutdown()
        self.driver.destroy_node()
        self.sim.destroy_node()
        rclpy.shutdown()


@pytest.fixture
def rig(tmp_path):
    r = None
    try:
        r = Rig(tmp_path)
        r.wait_for_fixes()
        yield r
    finally:
        if r is not None:
            r.close()


def test_each_platform_has_its_own_start_pose_and_frame(rig):
    assert [p.name for p in rig.sim.platforms] == list(PLATFORMS)
    for platform in rig.sim.platforms:
        lat, lon, _ = PLATFORMS[platform.name]
        assert platform.mru_frame == '%s/motion_sensor' % platform.name
        assert platform.model is rig.sim.models[MODELS[platform.name]]
        fix = rig.fresh_fix(platform.name)
        assert _metres((lat, lon), fix) < 1.0, platform.name


def test_platforms_use_their_own_model(rig):
    assert rig.sim.models['demo'] is not rig.sim.models['demo_fast']
    assert rig.sim.models['demo'].max_speed != FAST_MAX_SPEED
    assert rig.sim.models['demo_fast'].max_speed == FAST_MAX_SPEED
    speeds = {p.name: p.model.max_speed for p in rig.sim.platforms}
    assert speeds == {'alpha': rig.sim.models['demo'].max_speed,
                      'bravo': rig.sim.models['demo'].max_speed,
                      'charlie': FAST_MAX_SPEED}


def test_set_pose_moves_only_that_platform(rig):
    before = {n: rig.fresh_fix(n) for n in PLATFORMS}
    target = (43.0800, -70.7000)
    rig.set_pose('bravo', target[0], target[1], 90.0)
    assert _metres(target, rig.fresh_fix('bravo')) < 1.0
    for name in ('alpha', 'charlie'):
        assert _metres(before[name], rig.fresh_fix(name)) < 1.0, name


def test_set_pose_heading_is_a_compass_heading(rig):
    # Heading 0 is north. A yaw sign error (heading 180) or a missing 90 degree
    # offset (heading 90, due east) both fail one of the two bounds; the
    # simulator's own noise stays far inside them.
    start = (43.0800, -70.7000)
    rig.set_pose('charlie', start[0], start[1], 0.0)
    rig.drive('charlie', 1.0, 5.0)
    end = rig.fresh_fix('charlie')
    east = (end[1] - start[1]) * 111320.0 * math.cos(math.radians(start[0]))
    north = (end[0] - start[0]) * 111320.0
    assert north > 2.0
    assert abs(east) < north / 2.0


def test_set_pose_stores_a_heading_in_zero_to_360(rig):
    platform = next(p for p in rig.sim.platforms if p.name == 'charlie')
    for heading in (200.0, 359.0, 10.0):
        request = SetPose.Request()
        yaw = math.radians(90.0 - heading)
        request.pose.pose.orientation.z = math.sin(yaw / 2.0)
        request.pose.pose.orientation.w = math.cos(yaw / 2.0)
        assert platform.set_pose(request, SetPose.Response()).success
        assert math.degrees(platform.dynamics.heading) == pytest.approx(heading)


@pytest.mark.parametrize('quaternion, heading', [
    ((0.0, 0.0, 1.0, 1.0), 0.0),            # not unit length: yaw 90 degrees = north
    ((0.0, 0.0, 1e5, 1e5), 0.0),           # large, still a direction
    ((0.0, 0.0, 1e-5, 1e-5), 0.0),          # small, still a direction
    ((0.0, 0.0, 2.0, 0.0), 270.0),          # yaw 180 degrees = west
], ids=['non-unit', 'large', 'small', 'z-only'])
def test_set_pose_normalises_the_quaternion(rig, quaternion, heading):
    platform = next(p for p in rig.sim.platforms if p.name == 'charlie')
    request = SetPose.Request()
    (request.pose.pose.orientation.x, request.pose.pose.orientation.y,
     request.pose.pose.orientation.z, request.pose.pose.orientation.w) = quaternion
    assert platform.set_pose(request, SetPose.Response()).success
    assert math.degrees(platform.dynamics.heading) == pytest.approx(heading)


NAN, INF = float('nan'), float('inf')


@pytest.mark.parametrize('lat, lon, quaternion', [
    (NAN, -70.7, None),
    (43.0, NAN, None),
    (INF, -70.7, None),
    (43.0, -INF, None),
    (91.0, -70.7, None),
    (-90.5, -70.7, None),
    (43.0, 180.5, None),
    (43.0, -70.7, (0.0, 0.0, 0.0, 0.0)),
    (43.0, -70.7, (0.0, 0.0, NAN, 1.0)),
    (43.0, -70.7, (INF, 0.0, 0.0, 1.0)),
    (43.0, -70.7, (1e308, 1e308, 1e308, -1e308)),
    (43.0, -70.7, (0.0, 0.0, 1e7, 1e7)),
], ids=['nan-lat', 'nan-lon', 'inf-lat', 'inf-lon', 'lat-high', 'lat-low',
        'lon-high', 'zero-quaternion', 'nan-quaternion', 'inf-quaternion',
        'huge-quaternion', 'implausible-quaternion'])
def test_set_pose_refuses_a_pose_that_is_not_on_earth(rig, lat, lon, quaternion):
    before = {n: rig.fresh_fix(n) for n in PLATFORMS}
    assert not rig.call_set_pose('bravo', lat, lon, quaternion=quaternion).success
    rig.spin(1.0)
    # The refusal changed nothing, and the node still runs (a NaN position
    # would hang its update timer, so no fix would arrive).
    for name in PLATFORMS:
        assert _metres(before[name], rig.fresh_fix(name)) < 1.0, name


def test_throttle_moves_only_that_platform(rig):
    before = {n: rig.fresh_fix(n) for n in PLATFORMS}
    rig.drive('bravo', 1.0, 5.0)
    assert _metres(before['bravo'], rig.fresh_fix('bravo')) > 2.0
    for name in ('alpha', 'charlie'):
        assert _metres(before[name], rig.fresh_fix(name)) < 1.0, name


def test_sim_reset_returns_each_platform_to_its_own_start(rig):
    rig.drive('alpha', 1.0, 3.0)
    rig.drive('charlie', 1.0, 3.0)
    for name in ('alpha', 'charlie'):
        lat, lon, _ = PLATFORMS[name]
        assert _metres((lat, lon), rig.fresh_fix(name)) > 1.0, (
            '%s never left its start, so the reset proves nothing' % name)
    for name in PLATFORMS:
        rig.reset_pubs[name].publish(Bool(data=True))
    rig.spin(1.0)
    for name, (lat, lon, _) in PLATFORMS.items():
        assert _metres((lat, lon), rig.fresh_fix(name)) < 1.0, name


def test_sim_reset_with_false_does_nothing(rig):
    rig.drive('alpha', 1.0, 3.0)
    rig.reset_pubs['alpha'].publish(Bool(data=False))
    rig.spin(1.0)
    lat, lon, _ = PLATFORMS['alpha']
    assert _metres((lat, lon), rig.fresh_fix('alpha')) > 1.0


def test_demo_config_keys_are_declared_model_parameters(rig):
    config = yaml.safe_load(DEMO_CONFIG.read_text())
    keys = list(config['asv_sim']['ros__parameters'])
    assert keys
    undeclared = [k for k in keys if not rig.sim.has_parameter(k)]
    assert undeclared == []
