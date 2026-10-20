#!/usr/bin/env python3
# Copyright 2026 Roland Arsenault, UNH CCOM
# All rights reserved.
#
# Software License Agreement (BSD 2-Clause Simplified License)
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials provided
#    with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

"""
Self-test for the demo boats: drive them with fake joystick messages.

Needs no gamepad and no joystick driver. Run it against a launch started with
``enable_joysticks:=false``, or let it start one::

    ros2 launch marine_simulation demo_boats_launch.py enable_joysticks:=false
    ros2 run marine_simulation demo_boats_selftest.py

    ros2 run marine_simulation demo_boats_selftest.py --start-launch

With ``--start-launch`` the same ``--boats`` and ``--roster`` go to the launch, and
``--joysticks`` makes it start the real ``joy_linux`` drivers (the pads must be
plugged in) instead of ``enable_joysticks:=false``. Extra launch arguments may not
set ``boats:=``, ``roster_file:=`` or ``enable_joysticks:=`` (they would override
what the checks are derived from; the self-test refuses them). The self-test stops the launch
it started on any exit, including SIGINT and SIGTERM, and fails at once when the
launch exits early.

It publishes Xbox-shaped ``sensor_msgs/Joy`` messages (8 axes, 11 buttons) to each
boat's ``joy`` topic, so ``joy_to_helm``, ``helm_manager``, ``asv_helm`` and
``asv_sim`` are all in the loop, and checks that

- every boat has its full node set (one ``asv_sim`` for all),
- every boat's TF frames exist and no frame has two parents, no duplicate node names,
  no topic is published by the wrong boat (check_multi_boat_graph.py),
- ``/marine/platforms`` carries exactly one platform per boat with the roster's
  colour (these are the CAMP tab names and colours),
- driving one boat moves only that boat,
- all four driven at once move, on different courses,
- every boat's CUBE coverage topics deliver.

With ``--nav`` the boats run the navigation stack (``enable_nav:=true``, or ``--nav`` of the
manager with ``--demo``), and the self-test also checks that every nav2 lifecycle node of every
boat is ``active`` (nav2's own lifecycle manager brings them up), that the first boat, set to
``autonomous`` and sent a one-line ``SurveyPattern`` mission the way CAMP sends it
(``replace_task mission_plan`` on ``marine/mission_manager/command``), reports the mission's
tasks on ``marine/status/mission_tasks`` and drives to the end of the line, that the second boat,
left in ``manual``, does not move, and that the nav nodes are still active at the end.

A launch needs the geoid and VDatum grids under ``~/data/world/datum``: without
them ``chart_datum`` never publishes and this test fails on the missing frames after
the startup timeout (the launch itself refuses to start without them).

With ``--demo`` the thing started is the launch manager, ``demo_manager.py --profile headless``
(boats, target-area publisher and scorer; no CAMP and no window placement, so it runs on a
machine with no display), and one more check runs: the
``coverage_assessment`` scorer reaches the ``active`` state, and, given a target area
the self-test publishes itself (latched, like the target-area publisher does), answers
with a ``CoverageAssessment`` for it.

Exit status 0 when every check passes, 1 otherwise. The boats are reset to their
start poses at the end.
"""

import argparse
import json
import math
import os
import signal
import subprocess
import sys
import time

import check_multi_boat_graph as graph
from marine_simulation import demo_nav
import yaml

# Node names (relative to the boat's namespace) every boat must have.
BOAT_NODES = (
    'asv_helm', 'chart_datum', 'helm_manager', 'joint_state_publisher', 'joy_to_helm',
    'mbes_sim', 'mru_transform', 'platform_sender', 'robot_state_publisher',
    'sea_surface_estimator', 'sensors/mbes/cube_bathymetry',
    'sensors/mbes/detections_to_pointcloud',
)
# With navigation on, every boat also has these (relative to its namespace): mission_manager
# and the nodes of ben_project11's nav2 bring-up (see marine_simulation.demo_nav).
NAV_NODES = ('mission_manager', 'lifecycle_manager_navigation') + demo_nav.NAV2_SERVERS \
    + demo_nav.NAV2_COSTMAPS
# Frame names (under the boat's prefix) every boat must publish.
BOAT_FRAMES = (
    'base_link', 'base_link_north_up', 'odom', 'map', 'map_tide', 'chart_datum',
    'chart_datum_mhhw', 'motion_sensor', 'mbes',
)
# An Xbox-layout pad as the kernel joystick interface reports it.
AXES, BUTTONS = 8, 11
THROTTLE_AXIS, SLOW_MODE_AXIS, RUDDER_AXIS = 1, 2, 3


def fake_joy(throttle: float, rudder: float, full_speed: bool = True):
    """
    Return a Joy message as an Xbox pad would send it.

    ``joy_to_helm`` publishes helm.rudder = -axes[3]; a negative slow-mode axis
    (left trigger pulled) lifts its 35 % throttle limit.
    """
    from sensor_msgs.msg import Joy
    msg = Joy()
    msg.axes = [0.0] * AXES
    msg.axes[SLOW_MODE_AXIS] = -1.0 if full_speed else 1.0
    msg.axes[THROTTLE_AXIS] = float(throttle)
    msg.axes[RUDDER_AXIS] = float(rudder)
    msg.buttons = [0] * BUTTONS
    return msg


class LaunchExited(Exception):
    """The launch this test started has stopped on its own."""


def roster_colors(path: str) -> dict:
    """Return ``{boat name: (red, green, blue)}`` from the roster file."""
    with open(path) as f:
        boats = yaml.safe_load(f)['boats']
    return {b['name']: (b['color']['red'], b['color']['green'], b['color']['blue'])
            for b in boats}


def platform_problems(seen: dict, expected: dict, tolerance: float = 1e-4) -> list:
    """
    Compare the platforms seen on ``/marine/platforms`` with the roster.

    ``seen`` and ``expected`` map a platform name to ``(red, green, blue)``. The
    names are what CAMP shows as tabs, so a missing, extra or renamed boat is a
    problem, and so is a colour that is not the roster's.
    """
    problems = []
    for name in sorted(set(expected) - set(seen)):
        problems.append('platform %s never appeared' % name)
    for name in sorted(set(seen) - set(expected)):
        problems.append('unexpected platform %s' % name)
    for name in sorted(set(seen) & set(expected)):
        if any(abs(a - b) > tolerance for a, b in zip(seen[name], expected[name])):
            problems.append('platform %s has colour %s, the roster says %s'
                            % (name, tuple(round(c, 3) for c in seen[name]),
                               tuple(expected[name])))
    return problems


def launch_command(boats, roster, joysticks, extra, demo=False, nav=False) -> list:
    """Return the command line for ``--start-launch`` (the boats launch, or the manager)."""
    if demo:
        # No display here: CAMP and the window placement are the owner's rehearsal.
        cmd = ['ros2', 'run', 'marine_simulation', 'demo_manager.py', '--profile', 'headless']
        if not joysticks:
            cmd.append('--no-joysticks')
        if nav:
            cmd.append('--nav')
        if boats:
            cmd += ['--boats', ','.join(boats)]
        if roster:
            cmd += ['--roster', roster]
        return cmd + list(extra)
    cmd = ['ros2', 'launch', 'marine_simulation', 'demo_boats_launch.py',
           'enable_joysticks:=%s' % ('true' if joysticks else 'false')]
    if nav:
        cmd.append('enable_nav:=true')
    if boats:
        cmd.append('boats:=%s' % ','.join(boats))
    if roster:
        cmd.append('roster_file:=%s' % roster)
    return cmd + list(extra)


def roster_headings(path: str) -> dict:
    """Return ``{boat name: start heading in degrees}`` from the roster file."""
    with open(path) as f:
        return {b['name']: float(b['start']['heading']) for b in yaml.safe_load(f)['boats']}


def scorer_centre(roster_path, boats) -> tuple:
    """Return the mean start position (latitude, longitude) of ``boats`` in the roster."""
    with open(roster_path) as f:
        entries = {e['name']: e['start'] for e in yaml.safe_load(f)['boats']}
    lat = sum(entries[b]['lat'] for b in boats) / len(boats)
    lon = sum(entries[b]['lon'] for b in boats) / len(boats)
    return lat, lon


def survey_area_corners(lat: float, lon: float, half_side_degrees: float = 0.004) -> list:
    """Return the four (latitude, longitude) corners of a square around a point."""
    h = half_side_degrees
    return [(lat - h, lon - h), (lat - h, lon + h), (lat + h, lon + h), (lat + h, lon - h)]


def metres(a, b) -> float:
    """Approximate distance in metres between two (lat, lon) pairs."""
    dlat = (b[0] - a[0]) * 111320.0
    dlon = (b[1] - a[1]) * 111320.0 * math.cos(math.radians(a[0]))
    return math.hypot(dlat, dlon)


def bearing(a, b) -> float:
    """Compass bearing in degrees from (lat, lon) a to b."""
    dlat = b[0] - a[0]
    dlon = (b[1] - a[1]) * math.cos(math.radians(a[0]))
    return math.degrees(math.atan2(dlon, dlat)) % 360.0


def offset_position(origin, heading: float, distance: float) -> tuple:
    """Return the (lat, lon) ``distance`` metres from ``origin`` along compass ``heading``."""
    dlat = distance * math.cos(math.radians(heading)) / 111320.0
    dlon = distance * math.sin(math.radians(heading)) / (
        111320.0 * math.cos(math.radians(origin[0])))
    return origin[0] + dlat, origin[1] + dlon


def line_mission(label: str, start, end, speed_knots: float) -> list:
    """
    Return the mission plan CAMP would send for one survey line (a ``SurveyPattern``).

    The shape is what ``SurveyPattern::write`` produces and ``mission_manager``'s
    ``parseMission`` reads: a pattern item whose ``TrackLine`` child has ``Waypoint`` children.
    """
    def waypoint(name, point):
        return {'type': 'Waypoint', 'label': name, 'latitude': point[0], 'longitude': point[1]}

    return [{
        'type': 'SurveyPattern', 'label': label + '_set', 'speed': speed_knots, 'priority': 0,
        'children': [{
            'type': 'TrackLine', 'label': label + '_line', 'speed': speed_knots,
            'children': [waypoint('start', start), waypoint('end', end)],
        }],
    }]


def mission_command(plan: list) -> str:
    """Return the String mission_manager receives for ``plan`` (command_bridge strips the rest)."""
    return 'replace_task mission_plan ' + json.dumps(plan)


def tasks_acknowledge(task_ids, label: str) -> bool:
    """Return whether the reported task ids include the whole mission ``label`` sent."""
    return {label + '_set', label + '_set/' + label + '_line'} <= set(task_ids)


def angle_difference(a: float, b: float) -> float:
    """Smallest absolute difference between two compass angles, in degrees."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


class SelfTest:
    """The live checks."""

    def __init__(self, boats, joysticks, colors, launch=None, nav=False, starts=None):
        import rclpy
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
        from marine_interfaces.msg import (
            PlatformList, SonarVisualizationTile, TileCatalog)
        from sensor_msgs.msg import NavSatFix
        from std_msgs.msg import Bool

        self.rclpy = rclpy
        self.boats = list(boats)
        self.joysticks = joysticks
        self.nav = nav
        self.starts = starts or {}
        self.colors = colors
        self.launch = launch
        self.platforms = {}
        self.results = []
        self.node = rclpy.create_node('demo_boats_selftest')
        self.sampler = graph.GraphSampler(self.node)

        self.node.create_subscription(
            PlatformList, '/marine/platforms', self._on_platforms, 20)
        self.fix = {}
        self.joy_pub = {}
        self.reset_pub = {}
        self.catalog_entries = {b: None for b in boats}
        self.tile_count = {b: 0 for b in boats}
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                             reliability=ReliabilityPolicy.RELIABLE)
        for b in boats:
            self.node.create_subscription(
                NavSatFix, '/%s/sensors/nav/position' % b,
                lambda m, b=b: self._on_fix(b, (m.latitude, m.longitude)), 10)
            self.joy_pub[b] = self.node.create_publisher(
                self._joy_type(), '/%s/joy' % b, 10)
            self.reset_pub[b] = self.node.create_publisher(
                Bool, '/asv_sim/%s/sim_reset' % b, 10)
            self.node.create_subscription(
                TileCatalog, '/%s/sensors/mbes/cube_bathymetry/coverage_catalog' % b,
                lambda m, b=b: self.catalog_entries.__setitem__(b, len(m.entries)), latched)
            self.node.create_subscription(
                SonarVisualizationTile, '/%s/sensors/mbes/cube_bathymetry/coverage_tiles' % b,
                lambda m, b=b: self.tile_count.__setitem__(b, self.tile_count[b] + 1),
                QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT))

    def _on_fix(self, boat, fix):
        self.fix[boat] = fix

    def _on_platforms(self, msg):
        for p in msg.platforms:
            self.platforms[p.name] = (p.color.r, p.color.g, p.color.b)

    def check_launch(self):
        """Raise LaunchExited if the launch started by --start-launch has stopped."""
        if self.launch is not None and self.launch.poll() is not None:
            raise LaunchExited('the launch exited early with status %s'
                               % self.launch.returncode)

    @staticmethod
    def _joy_type():
        from sensor_msgs.msg import Joy
        return Joy

    def record(self, name, ok, detail=''):
        self.results.append((name, ok))
        print('%s %s%s' % ('PASS' if ok else 'FAIL', name, ': ' + detail if detail else ''),
              flush=True)

    def spin(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.check_launch()
            self.rclpy.spin_once(self.node, timeout_sec=0.02)

    def drive(self, commands, seconds):
        """Publish ``{boat: (throttle, rudder)}`` as fake Joy at 10 Hz."""
        deadline = time.monotonic() + seconds
        next_send = 0.0
        while time.monotonic() < deadline:
            self.check_launch()
            if time.monotonic() >= next_send:
                for b, (throttle, rudder) in commands.items():
                    self.joy_pub[b].publish(fake_joy(throttle, rudder))
                next_send = time.monotonic() + 0.1
            self.rclpy.spin_once(self.node, timeout_sec=0.01)

    def positions(self):
        self.spin(0.6)
        return dict(self.fix)

    # --- checks -----------------------------------------------------------------

    def wait_for_nodes(self, timeout):
        expected = {'/asv_sim'}
        for b in self.boats:
            expected.update('/%s/%s' % (b, n) for n in self.boat_nodes())
            if self.joysticks:
                expected.add('/%s/joy_node' % b)
        missing = expected
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.spin(0.5)
            present = {graph.fq_name(n, ns) for n, ns in self.sampler.nodes()}
            missing = expected - present
            if not missing and len(self.fix) == len(self.boats):
                break
        self.record('node set (one asv_sim, %d nodes per boat)' % (
            len(self.boat_nodes()) + (1 if self.joysticks else 0)),
            not missing, 'missing: %s' % ', '.join(sorted(missing)) if missing else '')
        self.record('every boat publishes a position', len(self.fix) == len(self.boats),
                    'have %s' % ', '.join(sorted(self.fix)))
        asv_sims = [1 for n, ns in self.sampler.nodes() if n == 'asv_sim']
        self.record('exactly one asv_sim node', len(asv_sims) == 1, 'found %d' % len(asv_sims))

    def boat_nodes(self):
        """Return the node names every boat must have (nav2's too with ``--nav``)."""
        return BOAT_NODES + (NAV_NODES if self.nav else ())

    def lifecycle_state(self, name, timeout=5.0):
        """Return the lifecycle state label of node ``name``, or None when it did not answer."""
        from lifecycle_msgs.srv import GetState
        client = self.node.create_client(GetState, name + '/get_state')
        try:
            deadline = time.monotonic() + timeout
            while not client.service_is_ready() and time.monotonic() < deadline:
                self.spin(0.1)
            if not client.service_is_ready():
                return None
            future = client.call_async(GetState.Request())
            while not future.done() and time.monotonic() < deadline:
                self.spin(0.05)
            if future.done() and future.result() is not None:
                return future.result().current_state.label
            return None
        finally:
            self.node.destroy_client(client)

    def check_nav_active(self, label, timeout=90.0):
        """Check every nav2 lifecycle node of every boat is ``active`` (wait for it first)."""
        wanted = [name for b in self.boats for name in demo_nav.nav_node_names(b).values()]
        deadline = time.monotonic() + timeout
        states = {}
        while True:
            states = {name: self.lifecycle_state(name) for name in wanted}
            bad = {n: st for n, st in states.items() if st != 'active'}
            if not bad or time.monotonic() > deadline:
                break
            self.spin(2.0)
        self.record('%s: every nav2 lifecycle node (%d) of every boat is active'
                    % (label, len(wanted)), not bad,
                    ', '.join('%s %s' % (n, st) for n, st in sorted(bad.items())))

    def check_graph(self, tf_seconds, frame_timeout=90.0):
        """Wait for every boat's frames (they start publishing late), then check the graph."""
        wanted = ['%s/%s' % (b, f) for b in self.boats for f in BOAT_FRAMES]
        deadline = time.monotonic() + frame_timeout
        while True:
            frames = {c for _, c in self.sampler.edges}
            missing = [f for f in wanted if f not in frames]
            if not missing or time.monotonic() > deadline:
                break
            self.spin(1.0)
        self.record('every boat publishes its %d frames' % len(BOAT_FRAMES), not missing,
                    'missing: %s' % ', '.join(missing) if missing else '')
        problems = graph.run_checks(self.sampler, self.boats, tf_seconds)
        self.record('graph: unique nodes, one TF parent per frame, no cross-boat topics',
                    not problems, '; '.join(problems))

    def check_platforms(self, timeout=60.0):
        """Check the CAMP tab names and colours: one platform per boat, in the roster colour."""
        deadline = time.monotonic() + timeout
        while not set(self.boats) <= set(self.platforms) and time.monotonic() < deadline:
            self.spin(0.5)
        self.spin(1.5)  # platform_sender repeats at 1 Hz; let an extra name show up
        expected = {b: self.colors[b] for b in self.boats}
        problems = platform_problems(self.platforms, expected)
        self.record('/marine/platforms: one platform per boat, in the roster colour',
                    not problems, '; '.join(problems))

    def check_solo(self, seconds):
        for b in self.boats:
            self.reset()
            before = self.positions()
            self.drive({b: (1.0, 0.0)}, seconds)
            after = self.positions()
            moved = {n: metres(before[n], after[n]) for n in self.boats}
            others = {n: d for n, d in moved.items() if n != b}
            ok = moved[b] > 3.0 and all(d < 1.0 for d in others.values())
            self.record('driving %s moves only %s' % (b, b), ok,
                        ', '.join('%s %.1f m' % (n, moved[n]) for n in self.boats))

    def check_together(self, seconds):
        """
        Drive all boats at once; every boat follows only its own pad.

        The first boat is left idle while the others run at full throttle, and every
        other boat also steers, so one boat stays put, some bend and some run straight.
        """
        throttles = {b: 0.0 if i == 0 else 1.0 for i, b in enumerate(self.boats)}
        steering = {b: 0.8 if i % 2 else 0.0 for i, b in enumerate(self.boats)}
        commands = {b: (throttles[b], steering[b]) for b in self.boats}
        self.reset()
        p0 = self.positions()
        self.drive(commands, seconds / 2.0)
        p1 = self.positions()
        self.drive(commands, seconds / 2.0)
        p2 = self.positions()
        travelled = {b: metres(p0[b], p2[b]) for b in self.boats}
        self.record('all boats driven at once: the idle boat stays, the others move',
                    all(travelled[b] < 1.0 if throttles[b] == 0.0 else travelled[b] > 3.0
                        for b in self.boats),
                    ', '.join('%s %.1f m at throttle %.1f' % (b, travelled[b], throttles[b])
                              for b in self.boats))
        bend = {b: angle_difference(bearing(p0[b], p1[b]), bearing(p1[b], p2[b]))
                for b in self.boats if throttles[b]}
        steered = [d for b, d in bend.items() if steering[b]]
        straight = [d for b, d in bend.items() if not steering[b]]
        self.record('all boats driven at once: only the boats given a rudder turn',
                    not steered or not straight or min(steered) > max(straight) + 10.0,
                    ', '.join('%s %s %.0f deg' % (b, 'steered' if steering[b] else 'straight',
                                                  d) for b, d in bend.items()))

    def check_nav_mission(self, seconds, speed_knots=4.0, line_length=160.0, lead=40.0):
        """
        Send the first boat a one-line survey mission and check it drives it; the others stay.

        The boat is set to ``autonomous`` and sent ``replace_task mission_plan <json>`` as CAMP
        sends it. It must report the mission's tasks on ``marine/status/mission_tasks`` and get
        to the end of the line (or mark the task done) within ``seconds``; every other boat, in
        ``manual`` and given nothing, must not move. The command is repeated until the tasks
        show up, because mission_manager only forwards to nav2 once nav2 is ready.
        """
        from marine_nav_interfaces.msg import TaskFeedback
        from std_msgs.msg import String

        boat = self.boats[0]
        label = 'selftest'
        self.reset()
        start = self.positions()
        heading = self.starts.get(boat, 60.0)
        first = offset_position(start[boat], heading, lead)
        last = offset_position(start[boat], heading, lead + line_length)
        command = mission_command(line_mission(label, first, last, speed_knots))
        seen = {'ids': [], 'done': set()}

        def on_tasks(msg):
            seen['ids'] = [t.id for t in msg.tasks]
            seen['done'] = {t.id for t in msg.tasks if t.done}

        self.node.create_subscription(
            TaskFeedback, '/%s/marine/status/mission_tasks' % boat, on_tasks, 10)
        mode = self.node.create_publisher(String, '/%s/piloting_mode' % boat, 10)
        mission = self.node.create_publisher(
            String, '/%s/marine/mission_manager/command' % boat, 10)
        deadline = time.monotonic() + 30.0
        while (mode.get_subscription_count() == 0 or mission.get_subscription_count() == 0) \
                and time.monotonic() < deadline:
            self.spin(0.2)
        mode.publish(String(data='autonomous'))
        accepted = False
        sent = 0
        next_send = 0.0
        # a loaded start can take minutes: the launch's guard and a respawned mission_manager
        # may each cost a restart before the first command is taken
        deadline = time.monotonic() + 240.0
        while not accepted and time.monotonic() < deadline:
            if time.monotonic() >= next_send:
                mission.publish(String(data=command))
                sent += 1
                next_send = time.monotonic() + 15.0
            self.spin(0.5)
            accepted = tasks_acknowledge(seen['ids'], label)
        self.record('%s accepts the mission (its tasks appear on mission_tasks)' % boat,
                    accepted, '%d command(s) sent, tasks %s' % (sent, sorted(seen['ids'])))
        end = time.monotonic() + seconds
        reached, distance = False, None
        travelled = 0.0
        while accepted and time.monotonic() < end:
            self.spin(1.0)
            fix = self.fix.get(boat)
            distance = metres(fix, last) if fix else None
            travelled = metres(start[boat], self.fix[boat])
            reached = travelled > 0.8 * line_length and (
                (label + '_set/' + label + '_line') in seen['done']
                or (distance is not None and distance < 20.0))
            if reached:
                break
        self.record('%s follows the mission to the end of the line' % boat, reached,
                    'travelled %.0f m, %s m from the end after %s s, done %s'
                    % (travelled, 'unknown' if distance is None else '%.0f' % distance,
                       '%.0f' % (seconds - max(0.0, end - time.monotonic())),
                       sorted(seen['done'])))
        after = dict(self.fix)
        others = {b: metres(start[b], after[b]) for b in self.boats if b != boat}
        self.record('the other boats, left in manual, do not move',
                    all(d < 1.0 for d in others.values()),
                    ', '.join('%s %.1f m' % (b, d) for b, d in others.items()) or 'none')
        mode.publish(String(data='manual'))
        mission.publish(String(data='clear_tasks'))
        self.spin(1.0)
        self.check_nav_active('after the mission', timeout=30.0)

    def check_coverage(self, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.spin(0.5)
            if all(self.catalog_entries[b] and self.tile_count[b] for b in self.boats):
                break
        for b in self.boats:
            self.record('%s CUBE coverage topics deliver' % b,
                        bool(self.catalog_entries[b]) and self.tile_count[b] > 0,
                        'catalog entries %s, coverage_tiles messages %d'
                        % (self.catalog_entries[b], self.tile_count[b]))

    def check_scorer(self, timeout, centre):
        """
        Check that the scorer is active and assesses a target area placed at ``centre``.

        Publishes what the target-area publisher does: a ``SurveyArea`` on
        ``/survey_area``, reliable and transient_local, so the check does not depend
        on that node.
        """
        from builtin_interfaces.msg import Time
        from geographic_msgs.msg import GeoPoint
        from lifecycle_msgs.srv import GetState
        from marine_interfaces.msg import CoverageAssessment, SurveyArea, SurveyStandard
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

        latched = QoSProfile(depth=100, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                             reliability=ReliabilityPolicy.RELIABLE)
        client = self.node.create_client(GetState, '/coverage_assessment/get_state')
        label = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and label != 'active':
            self.spin(0.5)
            if client.service_is_ready():
                future = client.call_async(GetState.Request())
                while not future.done() and time.monotonic() < deadline:
                    self.spin(0.1)
                if future.done() and future.result() is not None:
                    label = future.result().current_state.label
        self.record('the scorer reaches the active state', label == 'active',
                    'state %s' % label)
        if label != 'active':
            return

        assessed = []
        self.node.create_subscription(
            CoverageAssessment, '/coverage_assessment',
            lambda m: assessed.append(m) if m.area.id == 'selftest' else None, latched)
        area = SurveyArea(id='selftest', stamp=Time(sec=1, nanosec=0), priority=0,
                          standard=SurveyStandard(name='selftest', a=0.5, b=0.013))
        area.polygon.points = [GeoPoint(latitude=la, longitude=lo, altitude=0.0)
                               for la, lo in survey_area_corners(*centre)]
        publisher = self.node.create_publisher(SurveyArea, '/survey_area', latched)
        publisher.publish(area)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not assessed:
            self.spin(0.5)
        self.record('the scorer assesses the target area it is given', bool(assessed),
                    'area_total %.0f m2' % assessed[-1].area_total if assessed
                    else 'no CoverageAssessment for it')

    def reset(self):
        from std_msgs.msg import Bool
        for b in self.boats:
            self.reset_pub[b].publish(Bool(data=True))
        self.spin(1.5)

    def close(self):
        self.node.destroy_node()


def start_launch(cmd):
    """Start what the self-test runs against (a launch or the manager) in its own process group."""
    return subprocess.Popen(cmd, start_new_session=True)


def stop_launch(proc):
    """
    Stop the launch's whole process group.

    SIGINT first, so the launch shuts its nodes down; then SIGKILL on the group
    whatever happened, because the launch exiting does not mean its children have
    (and a second Ctrl-C during the wait must not skip the kill either).
    """
    try:
        try:
            os.killpg(proc.pid, signal.SIGINT)
            proc.wait(timeout=30)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def _terminate(signum, frame):
    """Turn SIGINT and SIGTERM into an exit that runs the ``finally`` blocks."""
    raise SystemExit(128 + signum)


# Launch arguments the self-test sets itself and derives its expectations from;
# a later copy on the command line would override them and make it check the
# wrong node set.
OWN_LAUNCH_ARGS = ('enable_joysticks:=', 'enable_nav:=', 'boats:=', 'roster_file:=')
# With --demo the manager is started instead, and these options are the self-test's own.
OWN_DEMO_LAUNCH_ARGS = ('--profile', '--boats', '--roster', '--no-joysticks', '--joysticks',
                        '--nav', '--no-nav')


def overridden_launch_args(extra, demo=False) -> list:
    """Return the extra launch arguments that would override the self-test's own."""
    return [a for a in extra if a.startswith(OWN_DEMO_LAUNCH_ARGS if demo else OWN_LAUNCH_ARGS)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--roster', help='demo roster file (default: the installed one)')
    parser.add_argument('--boats', help='comma separated boat names (default: the roster)')
    parser.add_argument('--start-launch', action='store_true',
                        help='start demo_boats_launch.py (joysticks off) and stop it after')
    parser.add_argument('--demo', action='store_true',
                        help='start demo_manager.py --profile headless instead (no CAMP, no '
                             'window placement) and check the coverage scorer too')
    parser.add_argument('--joysticks', action='store_true',
                        help='the launch runs joy_linux drivers: expect a joy_node per boat')
    parser.add_argument('--nav', action='store_true',
                        help='the boats run the navigation stack (the launch is started with '
                             'it): also check nav2 is active and one boat drives a mission')
    parser.add_argument('--nav-seconds', type=float, default=240.0,
                        help='how long the mission boat has to reach the end of its line')
    parser.add_argument('--startup-timeout', type=float, default=90.0)
    parser.add_argument('--drive-seconds', type=float, default=6.0)
    parser.add_argument('--tf-seconds', type=float, default=5.0)
    parser.add_argument('launch_args', nargs='*', help='extra launch arguments (--start-launch)')
    args = parser.parse_args(argv)

    roster = args.roster or graph.default_roster_path()
    boats = ([b.strip() for b in args.boats.split(',') if b.strip()] if args.boats
             else graph.boats_from_roster(roster))
    colors = roster_colors(roster)
    unknown = [b for b in boats if b not in colors]
    if unknown:
        parser.error('boat(s) not in the roster %s: %s' % (roster, ', '.join(unknown)))
    if args.demo and not args.start_launch:
        parser.error('--demo chooses the launch to start, so it needs --start-launch')
    clashes = (overridden_launch_args(args.launch_args, args.demo)
               if args.start_launch else [])
    if clashes:
        parser.error('%s would override what the self-test checks against; use '
                     '--boats, --roster or --joysticks of the self-test instead'
                     % ', '.join(clashes))

    import rclpy
    from rclpy.signals import SignalHandlerOptions
    # rclpy's own handlers shut the context down under us, and the stop-the-launch
    # code below would then never run; take the signals ourselves.
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    signal.signal(signal.SIGINT, _terminate)
    signal.signal(signal.SIGTERM, _terminate)
    test = proc = None
    try:
        try:
            # Everything that can fail sits inside these tries, and the launch (about
            # 50 processes) starts last, so a failed constructor cannot leak it.
            test = SelfTest(boats, args.joysticks, colors, nav=args.nav,
                            starts=roster_headings(roster))
            if args.start_launch:
                proc = start_launch(launch_command(
                    boats if args.boats else None, args.roster, args.joysticks,
                    args.launch_args, args.demo, args.nav))
                test.launch = proc
            try:
                test.wait_for_nodes(args.startup_timeout)
                if all(ok for _, ok in test.results):
                    test.check_graph(args.tf_seconds)
                    test.check_platforms()
                    test.check_solo(args.drive_seconds)
                    test.check_together(args.drive_seconds + 2.0)
                    if args.nav:
                        test.check_nav_active('after start')
                        test.check_nav_mission(args.nav_seconds)
                    test.check_coverage(30.0)
                    if args.demo:
                        test.check_scorer(40.0, scorer_centre(roster, boats))
                test.reset()
            except LaunchExited as error:
                test.record('the launch keeps running', False, str(error))
        finally:
            # First, before any ROS teardown that could itself raise: nothing may
            # keep the 50-process launch alive.
            if proc is not None:
                stop_launch(proc)
    finally:
        try:
            if test is not None:
                test.close()
        finally:
            rclpy.try_shutdown()
    failed = [name for name, ok in test.results if not ok]
    print('%d of %d checks passed' % (len(test.results) - len(failed), len(test.results)))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
