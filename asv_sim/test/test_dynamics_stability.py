"""Numerical robustness of ``asv_sim.dynamics.Dynamics`` (issue #84).

A multi-second gap between two updates (a stalled or descheduled node) used
to send the explicit-Euler drag integration through zero with a larger
speed each step, until ``speed ** 3`` overflowed and the node exited. These
tests pin that the integration is stable for any step length, that long gaps
are sub-stepped, and that a numerical excursion resets one platform instead
of ending the node.

Runs under plain pytest (``colcon test``); no launch_test runner needed.
"""

import math

from asv_sim import dynamics
from asv_sim import model
import pytest
import rclpy
import rclpy.node
from rclpy.time import Time

# Values below were measured with the explicit-Euler code that preceded the
# #84 fix: the shipped default jet model (mass 2000 kg, max_speed 2.75 m/s,
# max_power 21300 W), no noise, full throttle straight ahead from rest, one
# update every 0.05 s (the node's timer period), first update at t = 0.
OLD_SPEED_AT_1S = 0.6295958889148136
OLD_SPEED_AT_2S = 1.9724047101540798
OLD_SPEED_AT_4S = 2.7484670375208844
OLD_TERMINAL_SPEED = 2.75  # old code reached 2.749999999999999
# Same model, throttle 0 from 2.75 m/s: speed after 10 s (idle thrust only).
OLD_COAST_SPEED_AT_10S = 1.6955208155826207
# Same model, full throttle and full rudder from rest: yaw rate after 5 s.
OLD_YAW_RATE_AT_5S = 0.4363313026736959


class Recorder:
    """Stand-in for a logger: keeps (level, message) pairs."""

    def __init__(self):
        self.records = []

    def warning(self, message):
        self.records.append(('warning', message))

    def error(self, message):
        self.records.append(('error', message))

    def at(self, level):
        return [m for lv, m in self.records if lv == level]


@pytest.fixture
def log():
    return Recorder()


def ns(seconds):
    return Time(nanoseconds=int(round(seconds * 1e9)))


@pytest.fixture
def mdl():
    rclpy.init()
    node = rclpy.node.Node('dynamics_stability_test')
    try:
        yield model.Model('demo', node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


def no_thrust(m):
    """Keep the clutch out so only drag acts."""
    m.clutch_engagement_rpm = 1e12


def run(d, throttle, rudder, seconds, step, start=0.0):
    """Update every ``step`` seconds from ``start`` to ``start + seconds``."""
    d.update(throttle, rudder, ns(start), apply_noise=False)
    count = int(round(seconds / step))
    for i in range(1, count + 1):
        d.update(throttle, rudder, ns(start + i * step), apply_noise=False)


# (b) the arcade tuning is unchanged at the normal step ---------------------

def test_terminal_speed_at_normal_step_matches_the_old_value(mdl, log):
    d = dynamics.Dynamics(mdl, name='boat', logger=log)
    run(d, 1.0, 0.0, 20.0, 0.05)
    assert d.speed == pytest.approx(OLD_TERMINAL_SPEED, rel=0.01)


@pytest.mark.parametrize('seconds, expected', [
    (1.0, OLD_SPEED_AT_1S), (2.0, OLD_SPEED_AT_2S),
    (4.0, OLD_SPEED_AT_4S)])
def test_acceleration_transient_at_normal_step_matches_the_old_one(
        mdl, log, seconds, expected):
    d = dynamics.Dynamics(mdl, name='boat', logger=log)
    run(d, 1.0, 0.0, seconds, 0.05)
    assert d.speed == pytest.approx(expected, rel=0.01)


def test_coast_down_at_normal_step_matches_the_old_one(mdl, log):
    d = dynamics.Dynamics(mdl, name='boat', logger=log)
    d.speed = 2.75
    run(d, 0.0, 0.0, 10.0, 0.05)
    assert d.speed == pytest.approx(OLD_COAST_SPEED_AT_10S, rel=0.01)


def test_yaw_rate_at_normal_step_matches_the_old_one(mdl, log):
    d = dynamics.Dynamics(mdl, name='boat', logger=log)
    run(d, 1.0, 1.0, 5.0, 0.05)
    assert d.yaw_rate == pytest.approx(OLD_YAW_RATE_AT_5S, rel=0.01)


# (a), (c) a long step cannot diverge ---------------------------------------

@pytest.mark.parametrize('start_speed', [2.75, -2.75, 40.0])
def test_one_long_step_of_pure_drag_slows_without_reversing(
        mdl, log, start_speed):
    no_thrust(mdl)
    mdl.max_step = 10.0  # one integrator step: no sub-stepping help
    d = dynamics.Dynamics(mdl, name='boat', logger=log)
    d.speed = start_speed
    d.update(0.0, 0.0, ns(0.0), apply_noise=False)
    d.update(0.0, 0.0, ns(5.0), apply_noise=False)
    assert math.isfinite(d.speed)
    assert abs(d.speed) < abs(start_speed)
    assert d.speed * start_speed >= 0.0


def test_one_long_step_under_thrust_stays_between_rest_and_top_speed(
        mdl, log):
    mdl.max_step = 10.0
    d = dynamics.Dynamics(mdl, name='boat', logger=log)
    d.speed = 2.75
    d.update(1.0, 0.0, ns(0.0), apply_noise=False)
    d.update(1.0, 0.0, ns(5.0), apply_noise=False)
    assert 0.0 < d.speed <= 2.75 * 1.01


def test_a_long_gap_with_default_stepping_stays_bounded(mdl, log):
    d = dynamics.Dynamics(mdl, name='boat', logger=log)
    d.speed = 2.75
    d.update(1.0, 0.0, ns(0.0), apply_noise=False)
    d.update(1.0, 0.0, ns(5.0), apply_noise=False)
    assert 0.0 < d.speed <= 2.75 * 1.01


@pytest.mark.parametrize('start_rate', [0.4363, -0.4363])
def test_one_long_step_of_yaw_damping_does_not_reverse_the_turn(
        mdl, log, start_rate):
    no_thrust(mdl)
    mdl.max_step = 10.0
    d = dynamics.Dynamics(mdl, name='boat', logger=log)
    d.yaw_rate = start_rate
    d.update(0.0, 0.0, ns(0.0), apply_noise=False)
    d.update(0.0, 0.0, ns(5.0), apply_noise=False)
    assert math.isfinite(d.yaw_rate)
    assert abs(d.yaw_rate) < abs(start_rate)
    assert d.yaw_rate * start_rate >= 0.0


# (d), (e) sub-stepping -----------------------------------------------------

def state(d):
    return (d.speed, d.yaw_rate, d.heading, d.latitude, d.longitude, d.rpm,
            d.rudder_angle)


def test_a_one_second_gap_equals_ten_tenth_second_updates(mdl, log):
    mdl.max_step = 0.1
    gap = dynamics.Dynamics(mdl, name='gap', logger=log)
    steady = dynamics.Dynamics(mdl, name='steady', logger=log)
    for d in (gap, steady):
        d.update(1.0, 0.5, ns(0.0), apply_noise=False)
    gap.update(1.0, 0.5, ns(1.0), apply_noise=False)
    for i in range(1, 11):
        steady.update(1.0, 0.5, ns(i * 0.1), apply_noise=False)
    assert state(gap) == pytest.approx(state(steady), rel=1e-9, abs=1e-12)
    assert gap.speed > 0.0


def test_the_substep_ceiling_drops_the_rest_and_warns_once(mdl, log):
    mdl.max_step = 0.1
    mdl.max_substeps = 5
    behind = dynamics.Dynamics(mdl, name='slowpoke', logger=log)
    five = dynamics.Dynamics(mdl, name='five', logger=log)
    behind.update(1.0, 0.5, ns(0.0), apply_noise=False)
    five.update(1.0, 0.5, ns(0.0), apply_noise=False)

    behind.update(1.0, 0.5, ns(100.0), apply_noise=False)
    behind.update(1.0, 0.5, ns(300.0), apply_noise=False)
    warnings = log.at('warning')
    assert len(warnings) == 1
    assert 'slowpoke' in warnings[0]
    assert 'fell behind' in warnings[0]

    # Two ceiling-sized advances: 5 sub-steps of 0.1 s each, not 100 s.
    for i in range(1, 11):
        five.update(1.0, 0.5, ns(i * 0.1), apply_noise=False)
    assert state(behind) == pytest.approx(state(five), rel=1e-9, abs=1e-12)


# (f) a numerical excursion resets one platform, never the node -------------

def test_a_nan_speed_is_logged_reset_and_updates_continue(mdl, log):
    d = dynamics.Dynamics(mdl, name='bravo', logger=log)
    run(d, 1.0, 0.0, 2.0, 0.05)
    lat, lon = d.latitude, d.longitude
    d.speed = float('nan')
    d.update(1.0, 0.0, ns(2.05), apply_noise=False)
    errors = log.at('error')
    assert len(errors) == 1
    assert 'bravo' in errors[0] and 'speed' in errors[0]
    assert 'nan' in errors[0]
    assert d.speed == 0.0 and d.yaw_rate == 0.0
    assert (d.latitude, d.longitude) == (lat, lon)

    d.update(1.0, 0.0, ns(2.10), apply_noise=False)
    d.update(1.0, 0.0, ns(2.15), apply_noise=False)
    assert d.speed > 0.0
    assert all(math.isfinite(v) for v in state(d))


def test_a_nan_position_falls_back_to_the_last_finite_one(mdl, log):
    d = dynamics.Dynamics(mdl, name='bravo', logger=log)
    run(d, 1.0, 0.0, 2.0, 0.05)
    good = (d.latitude, d.longitude, d.heading)
    d.latitude = float('nan')
    d.heading = float('inf')
    d.update(1.0, 0.0, ns(2.05), apply_noise=False)
    assert len(log.at('error')) == 1
    assert (d.latitude, d.longitude, d.heading) == good
    d.update(1.0, 0.0, ns(2.10), apply_noise=False)
    assert all(math.isfinite(v) for v in state(d))


def test_an_excursion_inside_the_step_is_caught(mdl, log, monkeypatch):
    d = dynamics.Dynamics(mdl, name='bravo', logger=log)
    run(d, 1.0, 0.0, 2.0, 0.05)
    good = (d.latitude, d.longitude)
    monkeypatch.setattr(
        dynamics.geodesic, 'direct',
        lambda lon, lat, az, dist: (float('nan'), float('nan')))
    d.update(1.0, 0.0, ns(2.05), apply_noise=False)
    assert 'latitude' in ' '.join(log.at('error'))
    assert (d.latitude, d.longitude) == good
    assert d.speed == 0.0


def test_a_huge_speed_does_not_raise(mdl, log):
    d = dynamics.Dynamics(mdl, name='bravo', logger=log)
    d.update(1.0, 0.0, ns(0.0), apply_noise=False)
    d.speed = 1e200
    d.update(1.0, 0.0, ns(0.05), apply_noise=False)
    assert all(math.isfinite(v) for v in state(d))


# (g) noise on negative drag ------------------------------------------------

def test_negative_drag_noise_never_raises(mdl, log):
    d = dynamics.Dynamics(mdl, name='bravo', logger=log)
    d.update(0.0, 0.0, ns(0.0))
    d.speed = -2.0
    for i in range(1, 200):
        d.speed = -2.0
        diag = d.update(0.0, 0.0, ns(i * 0.05), apply_noise=True)
        assert diag['drag'] < 0.0  # sign-preserving: pushes a backward boat
        assert math.isfinite(d.speed)


def test_drag_noise_is_centred_on_the_noiseless_drag(mdl, log):
    d = dynamics.Dynamics(mdl, name='bravo', logger=log)
    d.update(0.0, 0.0, ns(0.0))
    drags = []
    for i in range(1, 2001):
        d.speed = 2.0
        drags.append(d.update(0.0, 0.0, ns(i * 0.05))['drag'])
    expected = mdl.drag_coefficient * 2.0 ** 3
    assert sum(drags) / len(drags) == pytest.approx(expected, rel=0.02)


def test_the_gap_before_a_placement_is_not_simulated(mdl, log):
    d = dynamics.Dynamics(mdl, name='bravo', logger=log)
    run(d, 1.0, 0.0, 2.0, 0.05)
    d.set(43.0, -70.0, 90.0)
    d.update(1.0, 0.0, ns(60.0), apply_noise=True)
    assert d.speed == 0.0
    assert d.yaw_rate == pytest.approx(0.0, abs=1.0)
    assert math.degrees(d.heading) == pytest.approx(90.0)
    assert not log.records
