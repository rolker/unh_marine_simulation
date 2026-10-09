"""In-process test: several asv_sim platforms share one node.

Builds one ``AsvSim`` node with several platforms (synthetic names, not the
demo roster) from parameter files, and drives it from a second node in the
same process with bounded ``spin_once`` loops. Checks that

- every platform keeps its own start pose, ``mru_frame`` and model,
- ``set_pose``, throttle and ``sim_reset`` act on one platform only,
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


def _write_platform_file(path):
    # asv_sim defaults to a 1 m/s current; drift would swamp the isolation
    # checks, so switch it off.
    params = {'platforms': list(PLATFORMS), 'environment.current.speed': 0.0}
    for name, (lat, lon, heading) in PLATFORMS.items():
        params['platforms.%s.model' % name] = 'demo'
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

    def set_pose(self, name, lat, lon, heading):
        client = self.pose_clients[name]
        deadline = time.monotonic() + 5.0
        while not client.service_is_ready():
            assert time.monotonic() < deadline, 'set_pose not available'
            self.executor.spin_once(timeout_sec=0.05)
        request = SetPose.Request()
        request.pose.pose.position.latitude = lat
        request.pose.pose.position.longitude = lon
        yaw = math.radians(90.0 - heading)
        request.pose.pose.orientation.z = math.sin(yaw / 2.0)
        request.pose.pose.orientation.w = math.cos(yaw / 2.0)
        future = client.call_async(request)
        while not future.done():
            assert time.monotonic() < deadline, 'set_pose timed out'
            self.executor.spin_once(timeout_sec=0.05)
        assert future.result().success
        self.spin(0.5)

    def close(self):
        self.executor.shutdown()
        self.driver.destroy_node()
        self.sim.destroy_node()
        rclpy.shutdown()


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path)
    try:
        r.wait_for_fixes()
        yield r
    finally:
        r.close()


def test_each_platform_has_its_own_start_pose_and_frame(rig):
    assert [p.name for p in rig.sim.platforms] == list(PLATFORMS)
    for platform in rig.sim.platforms:
        lat, lon, _ = PLATFORMS[platform.name]
        assert platform.mru_frame == '%s/motion_sensor' % platform.name
        assert platform.model is rig.sim.models['demo']
        fix = rig.fresh_fix(platform.name)
        assert _metres((lat, lon), fix) < 1.0, platform.name


def test_set_pose_moves_only_that_platform(rig):
    before = {n: rig.fresh_fix(n) for n in PLATFORMS}
    target = (43.0800, -70.7000)
    rig.set_pose('bravo', target[0], target[1], 90.0)
    assert _metres(target, rig.fresh_fix('bravo')) < 1.0
    for name in ('alpha', 'charlie'):
        assert _metres(before[name], rig.fresh_fix(name)) < 1.0, name


def test_set_pose_heading_is_a_compass_heading(rig):
    start = (43.0800, -70.7000)
    rig.set_pose('charlie', start[0], start[1], 90.0)
    rig.drive('charlie', 1.0, 5.0)
    end = rig.fresh_fix('charlie')
    east = (end[1] - start[1]) * 111320.0 * math.cos(math.radians(start[0]))
    north = (end[0] - start[0]) * 111320.0
    assert east > 2.0
    assert abs(north) < east / 3.0


def test_throttle_moves_only_that_platform(rig):
    before = {n: rig.fresh_fix(n) for n in PLATFORMS}
    rig.drive('bravo', 1.0, 5.0)
    assert _metres(before['bravo'], rig.fresh_fix('bravo')) > 2.0
    for name in ('alpha', 'charlie'):
        assert _metres(before[name], rig.fresh_fix(name)) < 1.0, name


def test_sim_reset_returns_each_platform_to_its_own_start(rig):
    rig.drive('alpha', 1.0, 3.0)
    rig.drive('charlie', 1.0, 3.0)
    for name in PLATFORMS:
        rig.reset_pubs[name].publish(Bool(data=True))
    rig.spin(1.0)
    for name, (lat, lon, _) in PLATFORMS.items():
        assert _metres((lat, lon), rig.fresh_fix(name)) < 1.0, name


def test_demo_config_keys_are_declared_model_parameters(rig):
    config = yaml.safe_load(DEMO_CONFIG.read_text())
    keys = list(config['asv_sim']['ros__parameters'])
    assert keys
    undeclared = [k for k in keys if not rig.sim.has_parameter(k)]
    assert undeclared == []
