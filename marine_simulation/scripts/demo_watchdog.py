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
The joystick watchdog of one demo boat: a plain node that decides who drives the boat.

It runs in the boat's namespace. While somebody touches the boat's pad it leaves the boat in
``manual``; when nobody has for ``idle_timeout`` seconds, or there is no pad, it publishes
``autonomous`` on ``piloting_mode`` and sends the boat's section of the target area to
``mission_manager`` as a CAMP ``SurveyPattern``; the first touch of the pad hands the boat back
at once and clears the mission. The decisions are ``marine_simulation.watchdog_core``, the
section and the plan are ``marine_simulation.survey_sections``; this file only connects them to
topics.

Topics (relative to the boat's namespace unless they start with a slash):

- in:  ``joy`` (``sensor_msgs/Joy``), ``marine/heartbeat`` (``marine_interfaces/Heartbeat``, key
  ``piloting_mode``), ``marine/status/mission_tasks`` (``marine_nav_interfaces/TaskFeedback``),
  ``/survey_area`` (``marine_interfaces/SurveyArea``, reliable and transient local, the first
  area by id), and TF ``earth`` to the boat's map frame.
- out: ``piloting_mode`` and ``marine/mission_manager/command`` (``std_msgs/String``), and
  ``demo_watchdog/state`` (``std_msgs/String``, latched JSON: state, reason, mission state, lines
  done and failed, pad and helm mode).

Parameters: ``boat`` (the name used in task labels), ``section_index`` and ``section_count``
(this boat's place among the boats that run), ``map_frame``, the timing ones of
``watchdog_core.Params`` and ``line_spacing``, ``edge_margin``, ``min_line_length``,
``survey_speed_knots`` and ``line_heading_deg`` (NaN: the long side of the area).
"""

import dataclasses
import math
import time

from marine_simulation import survey_sections
from marine_simulation import watchdog_core
import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from std_msgs.msg import String

TICK_SECONDS = 0.1
STATE_SECONDS = 1.0

SECTION_DEFAULTS = {
    'line_spacing': 80.0,
    'edge_margin': 15.0,
    'min_line_length': 30.0,
    'survey_speed_knots': 4.0,
    'line_heading_deg': float('nan'),
}


class DemoWatchdog(Node):
    """Connect the watchdog's state machine to the boat's topics."""

    def __init__(self):
        super().__init__('demo_watchdog')
        from marine_interfaces.msg import Heartbeat, SurveyArea
        from marine_nav_interfaces.msg import TaskFeedback
        from sensor_msgs.msg import Joy
        from tf2_ros import Buffer, TransformListener

        self.declare_parameter('boat', '')
        self.declare_parameter('map_frame', '')
        self.declare_parameter('section_index', 0)
        self.declare_parameter('section_count', 1)
        defaults = watchdog_core.Params()
        for field in dataclasses.fields(defaults):
            self.declare_parameter(field.name, getattr(defaults, field.name))
        for name, value in SECTION_DEFAULTS.items():
            self.declare_parameter(name, value)

        self.boat = self.get_parameter('boat').value
        self.map_frame = self.get_parameter('map_frame').value
        if not self.boat or not self.map_frame:
            raise ValueError("the 'boat' and 'map_frame' parameters are required")
        self.section_index = int(self.get_parameter('section_index').value)
        self.section_count = int(self.get_parameter('section_count').value)
        params = watchdog_core.Params(**{
            f.name: type(getattr(defaults, f.name))(self.get_parameter(f.name).value)
            for f in dataclasses.fields(defaults)})
        self.section_settings = {name: float(self.get_parameter(name).value)
                                 for name in SECTION_DEFAULTS}
        self.areas = {}
        self.core = watchdog_core.WatchdogCore(
            params, time.monotonic(), self.make_mission,
            lambda text: self.get_logger().info(text))

        latched = QoSProfile(depth=100, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                             reliability=ReliabilityPolicy.RELIABLE)
        self.mode_pub = self.create_publisher(String, 'piloting_mode', 10)
        self.command_pub = self.create_publisher(String, 'marine/mission_manager/command', 10)
        self.state_pub = self.create_publisher(
            String, 'demo_watchdog/state',
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                       reliability=ReliabilityPolicy.RELIABLE))
        self.create_subscription(Joy, 'joy', self.on_joy, 10)
        self.create_subscription(Heartbeat, 'marine/heartbeat', self.on_heartbeat, 10)
        self.create_subscription(TaskFeedback, 'marine/status/mission_tasks', self.on_tasks, 10)
        self.create_subscription(SurveyArea, '/survey_area', self.on_area, latched)
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.create_timer(TICK_SECONDS, self.tick)
        self.create_timer(STATE_SECONDS, self.publish_state)
        self._published_changes = -1
        self.get_logger().info(
            'watchdog for %s: section %d of %d, idle %g s, missing-pad grace %g s'
            % (self.boat, self.section_index + 1, self.section_count, params.idle_timeout,
               params.missing_pad_grace))

    # -- the mission ---------------------------------------------------------------------------

    def make_mission(self, generation):
        """Return ``(command, set task id, [line task ids])`` for this boat's section."""
        if not self.areas:
            raise ValueError('no target area has arrived')
        area_id = sorted(self.areas)[0]
        s = self.section_settings
        heading = None if math.isnan(s['line_heading_deg']) else s['line_heading_deg']
        try:
            section = survey_sections.plan_section(
                self.areas[area_id], self.section_index, self.section_count, s['line_spacing'],
                s['edge_margin'], s['min_line_length'], heading)
        except survey_sections.SectionError as error:
            raise ValueError(str(error)) from None
        prefix = '%s_s%d' % (self.boat, generation)
        plan = survey_sections.mission_plan(section, prefix, s['survey_speed_knots'])
        set_id, line_ids = survey_sections.task_ids(prefix, len(plan[0]['children']))
        return survey_sections.mission_command(plan), set_id, line_ids

    # -- topics in -----------------------------------------------------------------------------

    def on_joy(self, msg):
        self.perform(self.core.on_joy(time.monotonic(), msg.axes, msg.buttons))

    def on_heartbeat(self, msg):
        for item in msg.values:
            if item.key == 'piloting_mode':
                self.perform(self.core.on_heartbeat(time.monotonic(), item.value))

    def on_tasks(self, msg):
        self.perform(self.core.on_tasks(
            time.monotonic(), [(t.id, t.done, t.status) for t in msg.tasks]))

    def on_area(self, msg):
        points = [(p.latitude, p.longitude) for p in msg.polygon.points]
        before = self.areas.get(msg.id)
        self.areas[msg.id] = points
        if before != points:
            self.get_logger().info('target area %r: %d vertices' % (msg.id, len(points)))
            if sorted(self.areas)[0] == msg.id:
                self.perform(self.core.on_area(time.monotonic()))

    # -- the clock and topics out --------------------------------------------------------------

    def tick(self):
        now = time.monotonic()
        try:
            ready = self.tf_buffer.can_transform('earth', self.map_frame, Time(),
                                                 Duration(seconds=0.0))
        except Exception:                      # an unknown frame is simply "not yet"
            ready = False
        self.core.on_tf(now, ready)
        self.perform(self.core.tick(now))
        if self.core.changes != self._published_changes:
            self.publish_state()

    def publish_state(self):
        self._published_changes = self.core.changes
        self.state_pub.publish(String(data=self.core.snapshot_json(time.monotonic())))

    def perform(self, actions):
        for kind, text in actions:
            if kind == 'mode':
                self.mode_pub.publish(String(data=text))
                self.get_logger().info('piloting_mode %s' % text)
            elif kind == 'command':
                self.command_pub.publish(String(data=text))
                self.get_logger().info('mission_manager command: %s' % text[:60])


def main(args=None):
    rclpy.init(args=args)
    node = DemoWatchdog()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
