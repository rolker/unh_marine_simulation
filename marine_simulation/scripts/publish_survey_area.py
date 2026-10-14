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
Publish the target survey area(s) of a saved CAMP project file to the coverage scorer.

CAMP saves a project (File > Save) as JSON: a tree of items, where a ``SurveyArea`` item
has ``Waypoint`` children carrying ``latitude`` and ``longitude``. This node reads such
a file once, builds one ``marine_interfaces/SurveyArea`` per ``SurveyArea`` item and
publishes them latched (reliable, transient_local, depth 100), which is what
``coverage_assessment`` requires: a volatile publisher never reaches it.

    ros2 run marine_simulation publish_survey_area.py --ros-args -p file:=/path/to/file.json

The node keeps spinning after publishing so the latched samples outlive it for a scorer
that starts later. To pick up an edited file, restart the node: the scorer replaces an
area when the same id arrives again with a newer stamp.

The file parsing and message data are plain functions with no ROS import, so they are
tested without a ROS graph (``test/test_publish_survey_area.py`` loads this script by
path). ``rclpy`` and the message packages are imported inside ``main``.
"""

import json
import math
import os
import sys
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

DEFAULT_FILE_NAME = 'demo_target_polygon_camp.json'
# IHO S-44 Order 1a: allowed(depth) = sqrt(a^2 + (b * depth)^2), 95 % confidence.
DEFAULT_STANDARD_NAME = 'demo'
DEFAULT_STANDARD_A = 0.5
DEFAULT_STANDARD_B = 0.013
# The scorer's survey_area subscription (coverage_assessment README): reliable,
# transient_local, depth 100.
QOS_DEPTH = 100


class SurveyAreaFileError(Exception):
    """The CAMP file, or a parameter derived from it, cannot be published."""


Area = Tuple[str, List[Tuple[float, float]]]


def _items(node: Any) -> Iterator[Dict[str, Any]]:
    """Yield every dict item of a CAMP tree, depth first, the node itself first."""
    if isinstance(node, dict):
        yield node
        for child in node.get('children') or []:
            yield from _items(child)


def _coordinate(value: Any, low: float, high: float, what: str, where: str) -> float:
    # bool is an int in Python; a JSON true is not a coordinate.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SurveyAreaFileError('%s: %s is %r, not a number' % (where, what, value))
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise SurveyAreaFileError(
            '%s: %s %r is outside [%g, %g]' % (where, what, value, low, high))
    return value


def parse_survey_areas(project: Any) -> List[Area]:
    """
    Return ``(label, [(lat, lon), ...])`` for every ``SurveyArea`` item of a CAMP project.

    ``project`` is the decoded JSON. A ``SurveyArea`` may sit inside nested groups; only
    its direct ``Waypoint`` children are its vertices, in order. Raises
    ``SurveyAreaFileError`` when there is no ``SurveyArea``, when one has fewer than
    three vertices or a vertex without a finite latitude in [-90, 90] and longitude in
    [-180, 180], or when two areas have the same label.
    """
    areas: List[Area] = []
    seen = set()
    for index, item in enumerate(i for i in _items(project) if i.get('type') == 'SurveyArea'):
        label = item.get('label')
        if not isinstance(label, str) or not label:
            label = 'area%04d' % index
        where = 'SurveyArea %r' % label
        if label in seen:
            raise SurveyAreaFileError('%s: the label appears more than once' % where)
        seen.add(label)
        vertices = []
        for child in item.get('children') or []:
            if not isinstance(child, dict) or child.get('type') != 'Waypoint':
                continue
            here = '%s waypoint %d (%r)' % (where, len(vertices), child.get('label'))
            for key in ('latitude', 'longitude'):
                if key not in child:
                    raise SurveyAreaFileError('%s has no %s' % (here, key))
            vertices.append((
                _coordinate(child['latitude'], -90.0, 90.0, 'latitude', here),
                _coordinate(child['longitude'], -180.0, 180.0, 'longitude', here)))
        if len(vertices) < 3:
            raise SurveyAreaFileError(
                '%s has %d vertices; a polygon needs at least 3' % (where, len(vertices)))
        areas.append((label, vertices))
    if not areas:
        raise SurveyAreaFileError('no SurveyArea item in the file')
    return areas


def load_survey_areas(path: str) -> List[Area]:
    """Read a CAMP project file and return its areas (see ``parse_survey_areas``)."""
    if not path:
        raise SurveyAreaFileError("the 'file' parameter is empty")
    try:
        with open(path, encoding='utf-8') as stream:
            project = json.load(stream)
    except FileNotFoundError:
        raise SurveyAreaFileError('file not found: %s' % path)
    except (OSError, UnicodeDecodeError) as error:
        raise SurveyAreaFileError('cannot read %s: %s' % (path, error))
    except ValueError as error:
        raise SurveyAreaFileError('%s is not valid JSON: %s' % (path, error))
    try:
        return parse_survey_areas(project)
    except SurveyAreaFileError as error:
        raise SurveyAreaFileError('%s: %s' % (path, error))


def validate_standard(a: float, b: float) -> None:
    """
    Refuse a standard the scorer would read as "not set".

    ``SurveyStandard`` treats ``a = b = 0``, or a NaN, negative or infinite value, as not
    set, and nothing meets it: the scoreboard would sit at 0 % without saying why.
    """
    for name, value in (('standard_a', a), ('standard_b', b)):
        if not math.isfinite(value) or value < 0.0:
            raise SurveyAreaFileError('%s must be finite and >= 0, got %r' % (name, value))
    if a == 0.0 and b == 0.0:
        raise SurveyAreaFileError(
            'standard_a and standard_b are both 0: the scorer reads that as "not set" '
            'and nothing would meet it')


def area_ids(areas: Sequence[Area], area_id: str = '') -> List[str]:
    """
    Return the id of each area: its CAMP label, or ``area_id`` for a single-area file.

    An explicit ``area_id`` with several areas would give them all one id, so the scorer
    would keep only the last: refused.
    """
    if not area_id:
        return [label for label, _ in areas]
    if len(areas) != 1:
        raise SurveyAreaFileError(
            "'area_id' is %r but the file holds %d areas; leave it empty to use the "
            'CAMP labels' % (area_id, len(areas)))
    return [area_id]


def default_file() -> str:
    """Return the installed demo polygon, or '' when the package is not installed."""
    try:
        from ament_index_python.packages import get_package_share_directory
        return os.path.join(
            get_package_share_directory('marine_simulation'), 'config', DEFAULT_FILE_NAME)
    except Exception:  # noqa: B902 (package not found: the parameter is then required)
        return ''


def build_survey_areas(
        areas: Sequence[Area], ids: Sequence[str], stamp: Any, standard_name: str,
        standard_a: float, standard_b: float, priority: int) -> List[Any]:
    """Build one ``marine_interfaces/SurveyArea`` per area; ``stamp`` is a builtin Time."""
    from geographic_msgs.msg import GeoPoint
    from marine_interfaces.msg import GeoPolygon, SurveyArea, SurveyStandard

    messages = []
    for (_, vertices), area_id in zip(areas, ids):
        message = SurveyArea()
        message.id = area_id
        message.stamp = stamp
        message.polygon = GeoPolygon(
            points=[GeoPoint(latitude=lat, longitude=lon, altitude=0.0)
                    for lat, lon in vertices])
        message.standard = SurveyStandard(name=standard_name, a=standard_a, b=standard_b)
        message.priority = priority
        messages.append(message)
    return messages


def latched_qos() -> Any:
    """Return the QoS the scorer's ``survey_area`` subscription needs."""
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST, depth=QOS_DEPTH,
        reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)


def make_node(args: Optional[Sequence[str]] = None) -> Any:
    """
    Create the node, read its parameters and publish the areas.

    Raises ``SurveyAreaFileError`` for anything that makes publishing wrong; the node is
    destroyed first. Returns the node, which the caller spins.
    """
    from marine_interfaces.msg import SurveyArea
    import rclpy
    from rclpy.clock import Clock, ClockType
    from rclpy.node import Node

    if not rclpy.ok():
        rclpy.init(args=args)
    node = Node('survey_area_publisher')
    try:
        file_path = node.declare_parameter('file', default_file()).value
        topic = node.declare_parameter('topic', 'survey_area').value
        area_id = node.declare_parameter('area_id', '').value
        priority = node.declare_parameter('priority', 0).value
        standard_name = node.declare_parameter('standard_name', DEFAULT_STANDARD_NAME).value
        standard_a = node.declare_parameter('standard_a', DEFAULT_STANDARD_A).value
        standard_b = node.declare_parameter('standard_b', DEFAULT_STANDARD_B).value
        if not -32768 <= priority <= 32767:
            raise SurveyAreaFileError('priority %r does not fit an int16' % priority)
        validate_standard(standard_a, standard_b)
        areas = load_survey_areas(file_path)
        ids = area_ids(areas, area_id)
        publisher = node.create_publisher(SurveyArea, topic, latched_qos())
        # Wall-clock time, not the node clock: under use_sim_time the node clock reads 0
        # until /clock arrives, and a restart after an edit would then carry a stamp the
        # scorer ignores as not newer than the one it holds for the same id.
        stamp = Clock(clock_type=ClockType.SYSTEM_TIME).now().to_msg()
        for message in build_survey_areas(
                areas, ids, stamp, standard_name, standard_a, standard_b, priority):
            publisher.publish(message)
        node.get_logger().info(
            'published %d survey area(s) %s from %s on %s' % (
                len(ids), ids, file_path, publisher.topic_name))
        # Keep a reference: a destroyed publisher takes its latched samples with it.
        node.publisher_ = publisher
    except BaseException:
        node.destroy_node()
        raise
    return node


def main(args: Optional[Sequence[str]] = None) -> int:
    """Run the node; return a non-zero exit status when the inputs are refused."""
    import rclpy

    try:
        node = make_node(args)
    except SurveyAreaFileError as error:
        print('publish_survey_area: refused: %s' % error, file=sys.stderr)
        if rclpy.ok():
            rclpy.shutdown()
        return 1
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
