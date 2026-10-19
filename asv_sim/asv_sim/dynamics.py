#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Roland Arsenault
# Center for Coastal and Ocean Mapping
# University of New Hampshire
# Copyright 2017, All rights reserved.

import logging
import math
import random
import time

import rclpy.constants

from . import environment, geodesic, model


# Minimum seconds between two log lines of the same kind. The update loop
# runs 20 times a second, so a persistent problem would otherwise flood the
# log; the first occurrence is always logged.
_LOG_INTERVAL = 5.0


class _Excursion(Exception):
    """A state value left the finite numbers (or an operation failed on it)."""

    def __init__(self, name, value):
        super().__init__('{} is {!r}'.format(name, value))
        self.name = name
        self.value = value


class Dynamics(object):
    """Simulate the dynamics of a boat.

    Using throttle and rudder inputs, calculate simplified forces acting
    on a boat changing its position, speed, and heading.
    """

    def __init__(self, mdl: model.Model,
                 env: environment.Environment = None, start=None,
                 name='', logger=None):
        """Initialize the simulation with a model and optional environment.

        :param name: Platform name, used in log messages.
        :param logger: Object with ``warning`` and ``error`` methods (an
            rclpy logger or a ``logging.Logger``). Defaults to the
            ``asv_sim.dynamics`` Python logger.
        """
        self.name = name
        self.logger = logger or logging.getLogger('asv_sim.dynamics')
        self._last_logged = {}
        # Portsmouth, New Hampshire, cod rock
        self.start_lat = 43.073397415457535
        self.start_lon = -70.71054174878898
        self.start_heading = 60.0

        if start is not None:
            if 'lat' in start:
                self.start_lat = start['lat']
            if 'lon' in start:
                self.start_lon = start['lon']
            if 'heading' in start:
                self.start_heading = start['heading']

        self.model = mdl
        self.environment = env

        self.reset()
        self.last_update = None

        # jitters are used to add gaussian noise to components of the
        # model to simulate small disturbances that would be difficult
        # to model.
        self.jitters = {
            'thrust': 0.1, 'rudder': 0.25, 'drag': 0.1,
            'current_speed': 0.1, 'current_direction': 0.25
        }

    def set(self, lat, lon, heading):  # noqa: A003
        """Set the boat to idle at the provided position and heading."""
        self.rpm = 0.0
        self.rudder_angle = 0.0
        self.bucket_position = 0.0
        self.speed = 0.0
        self.yaw_rate = 0.0
        self.longitude = math.radians(lon)
        self.latitude = math.radians(lat)

        self.heading = math.radians(heading)
        self.pitch = 0.0
        self.roll = 0.0
        self.altitude = 0.0

        self.sog = 0.0
        self.cog = 0.0
        self.a = 0.0

        self._last_good = (self.latitude, self.longitude, self.heading)
        # The time since the last update says nothing about a boat that was
        # just placed at rest: do not simulate that gap on the next update.
        self._discard_gap = True

    def reset(self):
        """Reset the simulation to starting location and idle state."""
        self.set(self.start_lat, self.start_lon, self.start_heading)

    def update(self, throttle, rudder, timestamp, apply_noise=True):
        """Update the simulation one step.

        The simulation does not impose an update rate or expect that
        updates are at regular intervals. It's the system using this
        model that is responsible for continuously calling this
        method at an adequate rate.

        A gap longer than the model's ``max_step`` since the last update
        is integrated as several equal sub-steps no longer than
        ``max_step``. At most ``max_substeps`` sub-steps are taken; the
        part of a longer gap beyond that is dropped (with a throttled
        warning) rather than simulated.

        This method does not raise on a numerical excursion: if a state
        value is not finite afterwards, the platform is logged, reset to
        rest where it is, and the simulation continues.

        :param throttle: Normalized throttle value in the -1 to 1 range.
        :param rudder: Normalized rudder value from -1 (left)  to 1
            (right).
        :param timestamp: Time in seconds for the current iteration. It
            only matters that the time reference is consistent, since
            it's only used to calculate elapsed time since the last
            update.
        :param  apply_noise: True if noise should be applied for
            simulating variability.
        """
        # collect useful debugging info
        diagnostics = {'rudder': rudder}

        # clamp throttle input
        throttle = min(1.0, max(-1.0, throttle))
        reverse = throttle < 0
        throttle = abs(throttle)
        diagnostics['throttle'] = throttle

        # Figure out the time interval since the last update
        if self.last_update is None:
            delta_t = None
        else:
            delta_t = (
                (timestamp - self.last_update).nanoseconds
                / float(rclpy.constants.S_TO_NS))
            if delta_t <= 0:
                delta_t = None
        self.last_update = timestamp
        if self._discard_gap:
            delta_t = None
            self._discard_gap = False

        try:
            # State written from outside (set_pose, a test, a bad restore)
            # must not reach the integrator unchecked.
            self._require_finite()
            for step_dt in self._substeps(delta_t):
                self._step(throttle, reverse, rudder, step_dt,
                           apply_noise, diagnostics)
            self._last_good = (self.latitude, self.longitude, self.heading)
        except _Excursion as e:
            self._recover(e.name, e.value)
        except (ArithmeticError, ValueError) as e:
            # OverflowError, ZeroDivisionError and math domain errors: the
            # state is garbage even though no value is NaN yet.
            self._recover('arithmetic failure', '{}: {}'.format(
                type(e).__name__, e))

        # Update altitude, roll, and pitch from environment
        if self.environment is not None:
            try:
                waves = self.environment.getWaves(timestamp)
                altitude = (self.environment.getEllipsoidalAltitude(
                    timestamp) + waves['heave'])
                tide = self.environment.getTide(timestamp)
            except (ArithmeticError, ValueError) as e:
                self._log(
                    'error', 'environment',
                    'asv_sim platform {!r}: environment failed ({}: {}); '
                    'keeping the last altitude, roll and pitch'.format(
                        self.name, type(e).__name__, e))
            else:
                self.altitude = altitude
                self.roll = waves['roll']
                self.pitch = waves['pitch']
                diagnostics['altitude'] = self.altitude
                diagnostics['tide'] = tide
                diagnostics['heave'] = waves['heave']
                diagnostics['wave_roll'] = math.degrees(waves['roll'])
                diagnostics['wave_pitch'] = math.degrees(waves['pitch'])

        return diagnostics

    def _log(self, level, key, message):
        """Log at most once per ``_LOG_INTERVAL`` seconds for each key."""
        now = time.monotonic()
        last = self._last_logged.get(key)
        if last is not None and now - last < _LOG_INTERVAL:
            return
        self._last_logged[key] = now
        # One call site per severity: an rclpy logger raises when a single
        # call site is used at two severities.
        try:
            if level == 'error':
                self.logger.error(message)
            else:
                self.logger.warning(message)
        except Exception:  # noqa: B902 - logging must never end the node
            pass

    def _substeps(self, delta_t):
        """Split an elapsed time into the step lengths to integrate.

        :return: List of step lengths in seconds; ``[None]`` for the first
            update (no elapsed time known).
        """
        if delta_t is None:
            return [None]
        max_step = self.model.max_step
        # The small offset keeps float noise (1.0 / 0.1 and the like) from
        # adding a sub-step.
        count = max(1, math.ceil(delta_t / max_step - 1e-9))
        if count == 1:
            return [delta_t]
        ceiling = self.model.max_substeps
        if count > ceiling:
            simulated = ceiling * max_step
            self._log(
                'warning', 'fell_behind',
                'asv_sim platform {!r} fell behind: {:.3f} s since the '
                'last update, simulating only {:.3f} s (max_step {} s x '
                'max_substeps {}) and dropping the rest'.format(
                    self.name, delta_t, simulated, max_step, ceiling))
            return [max_step] * ceiling
        return [delta_t / count] * count

    def _require_finite(self):
        """Raise _Excursion for the first state value that is not finite."""
        for name in ('speed', 'yaw_rate', 'latitude', 'longitude',
                     'heading', 'rpm', 'rudder_angle', 'a'):
            value = getattr(self, name)
            if not math.isfinite(value):
                raise _Excursion(name, value)

    def _recover(self, name, value):
        """Reset to rest after a numerical excursion, keeping the position."""
        self._log(
            'error', 'excursion',
            'asv_sim platform {!r}: {} became {!r}; resetting its motion '
            'to rest and continuing'.format(self.name, name, value))
        last_lat, last_lon, last_heading = self._last_good
        if not (math.isfinite(self.latitude)
                and math.isfinite(self.longitude)):
            self.latitude, self.longitude = last_lat, last_lon
        if not math.isfinite(self.heading):
            self.heading = last_heading
        if not math.isfinite(self.rpm):
            self.rpm = 0.0
        if not math.isfinite(self.rudder_angle):
            self.rudder_angle = 0.0
        self.speed = 0.0
        self.yaw_rate = 0.0
        self.a = 0.0
        self.sog = 0.0
        if not math.isfinite(self.cog):
            self.cog = 0.0
        self._last_good = (self.latitude, self.longitude, self.heading)

    @staticmethod
    def _implicit_drag_speed(rhs, beta):
        """Solve v + beta * v^3 = rhs for v (beta >= 0).

        Newton's method from v = |rhs|: the function is increasing and
        convex for v >= 0, so the iterates fall monotonically onto the
        root and never undershoot it. The odd symmetry gives the sign.
        """
        magnitude = abs(rhs)
        v = magnitude
        for _ in range(60):
            f = v + beta * v * v * v - magnitude
            slope = 1.0 + 3.0 * beta * v * v
            if not (math.isfinite(f) and math.isfinite(slope)):
                # Overflow: a speed this far out is garbage anyway. Shrink
                # it with the frozen-coefficient form, which is finite.
                v = magnitude / (1.0 + beta * magnitude * magnitude)
                break
            step = f / slope
            v -= step
            if step <= 1e-15 * v:
                break
        return math.copysign(v, rhs)

    def _step(self, throttle, reverse, rudder, delta_t, apply_noise,
              diagnostics):
        """Advance the simulation by delta_t seconds (None: no time passes).

        :raises _Excursion: when speed, yaw rate, heading or position stop
            being finite.
        """
        # This implements the inertia of the engine as it changes RPMs.
        target_rpm = (self.model.idle_rpm
                      + throttle
                      * (self.model.max_rpm - self.model.idle_rpm))
        diagnostics['target_rpm'] = target_rpm
        if (target_rpm != self.rpm):
            if delta_t is not None:
                rcr = (target_rpm - self.rpm) / delta_t
                max_rpm_change_rate = self.model.max_rpm_change_rate
                if abs(rcr) > max_rpm_change_rate:
                    if rcr < 0:
                        rcr = -max_rpm_change_rate
                    else:
                        rcr = max_rpm_change_rate
                self.rpm += rcr * delta_t

        diagnostics['rpm'] = self.rpm

        # Apply the gearbox and clutch.
        if self.rpm < self.model.clutch_engagement_rpm:
            prop_rpm = 0.0
        else:
            prop_rpm = self.model.gearbox_ratio * self.rpm

        diagnostics['prop_rpm'] = prop_rpm

        target_rudder_angle = rudder * self.model.max_rudder_angle
        diagnostics['target_rudder_angle'] = target_rudder_angle

        if (self.rudder_angle != target_rudder_angle
                and delta_t is not None):
            possible_rudder_change = (
                self.model.max_rudder_change_rate * delta_t)
            if (abs(target_rudder_angle - self.rudder_angle)
                    < possible_rudder_change):
                self.rudder_angle = target_rudder_angle
            else:
                if (target_rudder_angle < self.rudder_angle):
                    self.rudder_angle -= possible_rudder_change
                else:
                    self.rudder_angle += possible_rudder_change

        diagnostics['rudder_angle'] = self.rudder_angle
        rudder_rads = math.radians(self.rudder_angle)

        if self.model.propulsion_type == 'prop':
            # Calculate the speed of the water moved by the prop.
            # TODO: figure out why this seems to differ from the
            # definition of pitch as being inches of distance traveled
            # per revolution
            prop_speed = prop_rpm / self.model.prop_pitch

            # TODO: implement need to drop rpms to switch fwd and rev
            if reverse:
                prop_speed = -prop_speed
            diagnostics['propwash_speed'] = prop_speed

            # Assuming the rudder is in the prop wash, determine the
            # speed of the water flowing by the rudder.
            if prop_speed > 0:
                rudder_speed = max(math.sqrt(prop_speed), self.speed)
            else:
                rudder_speed = self.speed

            # Calculate force created by the difference of the speed of
            # the water pushed by the prop and the speed of the boat
            # through water.
            #
            # From https://wright.nasa.gov/airplane/propth.html
            #
            # F = .5 * r * A * [Ve ^2 - V0 ^2]
            #
            # Replace .5 * r * A by prop_coefficient to get the
            # following
            thrust = self.model.prop_coefficient * (
                prop_speed**2 - self.speed**2)
            diagnostics['prop_coefficient'] = (
                self.model.prop_coefficient)

        if self.model.propulsion_type == 'jet':

            # https://www.engineeringtoolbox.com/affinity-laws-d_408.html
            # flow is directly proportional to rpm

            # jet_speed = self.max_jet_speed*prop_rpm/self.max_prop_rpm
            # diagnostics['jet_speed'] = jet_speed

            # F = rho q (v2 - v1)
            # thrust = max(0.0,self.rho_q*(jet_speed-self.speed))

            thrust = (self.model.max_force * prop_rpm
                      / self.model.max_prop_rpm)

            # todo: model bucket movement
            if reverse:
                thrust = -thrust * self.model.bucket_efficiency

        if apply_noise:
            thrust = random.gauss(thrust, thrust * self.model.thrust_noise)
        diagnostics['thrust'] = thrust

        diagnostics['max_force'] = self.model.max_force

        # decompose the thrust into vectors that push the boat
        # forward and that rotates the boat
        thrust_fwd = thrust * math.cos(rudder_rads)
        diagnostics['thrust_fwd'] = thrust_fwd

        if self.model.propulsion_type == 'prop':
            rudder_speed_yaw = rudder_speed * math.sin(rudder_rads)
            # The distance between the center of mass and the rudder
            # affect how quickly the boat can turn.
            self.yaw_rate = (self.model.rudder_coefficient
                             * rudder_speed_yaw
                             / self.model.rudder_distance)

        if self.model.propulsion_type == 'jet':
            yaw_thrust = thrust * math.sin(rudder_rads)

            yaw_drag = (-(self.yaw_rate**1)
                        * self.model.go_straight_coefficient)

            diagnostics['yaw_thrust'] = yaw_thrust
            diagnostics['yaw_drag'] = yaw_drag

            # https://en.wikipedia.org/wiki/Moment_of_inertia
            # torque = I * angular acceleration

            # let's oversimplify the asv to a thin disc
            # I = 1/2 * m * r^2
            # The yaw_inertia_coefficient (default 1.0) scales this so
            # the rotational response can be tuned independently of the
            # forward mass; values below 1.0 shorten the yaw time
            # constant (faster, less laggy turning).

            moment_of_inertia = (
                self.model.yaw_inertia_coefficient
                * self.model.mass
                * pow(self.model.rudder_distance, 2) / 2.0)

            if delta_t is not None:
                # The damping torque is linear in the yaw rate, so it is
                # integrated implicitly (backward Euler):
                #   w' = w + dt * (T_thrust - k * w') / I
                # An explicit step overshoots through zero, and grows each
                # step, once dt * k / I exceeds 2 (a stalled update). The
                # implicit form can at most bring the yaw rate to the value
                # the thrust alone drives it to, never reverse it, and
                # matches the explicit step to O(dt^2) at normal step
                # lengths.
                thrust_torque = yaw_thrust * self.model.rudder_distance
                damping = (self.model.go_straight_coefficient
                           * self.model.rudder_distance)
                self.yaw_rate = (
                    (self.yaw_rate
                     + delta_t * thrust_torque / moment_of_inertia)
                    / (1.0 + delta_t * damping / moment_of_inertia))

        if apply_noise:
            self.yaw_rate += random.gauss(
                0.0, self.model.yaw_rate_noise)

        diagnostics['yaw_rate'] = self.yaw_rate

        if delta_t is not None:
            self.heading += self.yaw_rate * delta_t
            self.heading = math.fmod(self.heading, math.radians(360))
            if self.heading < 0:
                self.heading += math.radians(360)

        # Drag increases with the cube of the speed, and keeps the sign of
        # the speed (a boat moving backwards is pushed forwards).
        #
        # The drag is integrated implicitly (backward Euler) so a step of
        # any length is stable:
        #   v1 = v0 + dt * (F_thrust - c * v1^3) / m
        # which is solved for v1 below. The left side is strictly
        # increasing in v1, so there is exactly one root, and the drag can
        # at most bring the speed to what the thrust alone gives, never
        # past it. An explicit step overshoots through zero, and each
        # overshoot is larger than the last, once dt * c * v0^2 / m exceeds
        # 2 (always after a multi-second stall; issue #84). The steady
        # state (thrust == c * v^3) is identical to the explicit scheme,
        # and at the normal 0.05 s step the transient differs by well under
        # 1 %.
        #
        # The noise multiplies the coefficient. That is the distribution
        # gauss(drag, abs(drag) * noise) without a sign problem, and it is
        # kept from going negative (drag must not push the boat along).
        speed0 = self.speed
        drag_scale = 1.0
        if apply_noise:
            drag_scale = max(0.0, random.gauss(
                1.0, abs(self.model.drag_noise)))
        drag_coefficient = self.model.drag_coefficient * drag_scale
        drag = drag_coefficient * speed0 * speed0 * speed0

        diagnostics['drag'] = drag
        diagnostics['net_force'] = thrust_fwd - drag

        if delta_t is None:
            # calculate acceleration from f=ma.
            self.a = (thrust_fwd - drag) / self.model.mass
        else:
            self.speed = self._implicit_drag_speed(
                speed0 + delta_t * thrust_fwd / self.model.mass,
                delta_t * drag_coefficient / self.model.mass)
            self.a = (self.speed - speed0) / delta_t

        self._require_finite()

        # update position based on speed
        if delta_t is not None:
            last_lat = self.latitude
            last_long = self.longitude
            delta = self.speed * delta_t
            self.longitude, self.latitude = geodesic.direct(
                self.longitude, self.latitude, self.heading, delta)
            # apply currents if applicable
            if self.environment is not None:
                c = self.environment.getCurrent(
                    self.latitude, self.longitude, apply_noise)
                if c is not None:
                    diagnostics['current_speed'] = c['speed']
                    diagnostics['current_direction'] = c['direction']
                    current_speed = c['speed']
                    current_direction = math.radians(c['direction'])
                    # geodesic.direct() never returns for a NaN input.
                    for name, value in (('current speed', current_speed),
                                        ('current direction',
                                         current_direction)):
                        if not math.isfinite(value):
                            raise _Excursion(name, value)

                    self.longitude, self.latitude = geodesic.direct(
                        self.longitude, self.latitude,
                        current_direction, current_speed * delta_t)
            self._require_finite()
            self.cog, self.sog = geodesic.inverse(
                last_long, last_lat, self.longitude, self.latitude)
            self.sog /= delta_t
