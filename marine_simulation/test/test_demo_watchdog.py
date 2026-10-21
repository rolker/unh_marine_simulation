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


"""In-process tests of the watchdog node (scripts/demo_watchdog.py): the area topic and its retry."""

import importlib.util
import os
import pathlib

import pytest

try:
    import rclpy
    from marine_interfaces.msg import SurveyArea
    from geographic_msgs.msg import GeoPoint
    HAVE_ROS = True
except ImportError:             # pragma: no cover - the tests are skipped without ROS
    HAVE_ROS = False

pytestmark = pytest.mark.skipif(not HAVE_ROS, reason='ROS 2 is not sourced')

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / 'scripts' / 'demo_watchdog.py'
RING = [(43.0, -70.7), (43.0, -70.6), (43.1, -70.6)]
BIGGER = [(43.0, -70.7), (43.0, -70.5), (43.2, -70.5)]


@pytest.fixture
def node(monkeypatch):
    monkeypatch.setenv('ROS_DOMAIN_ID', str(1 + os.getpid() % 100))
    monkeypatch.setenv('ROS_LOCALHOST_ONLY', '1')
    monkeypatch.setenv('ROS_AUTOMATIC_DISCOVERY_RANGE', 'LOCALHOST')
    spec = importlib.util.spec_from_file_location('demo_watchdog', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rclpy.init(args=['--ros-args', '-p', 'boat:=testboat', '-p', 'map_frame:=testboat/map'])
    watchdog = module.DemoWatchdog()
    watchdog.module = module
    yield watchdog
    watchdog.destroy_node()
    rclpy.try_shutdown()


def area(area_id, ring, sec, nanosec=0):
    msg = SurveyArea()
    msg.id = area_id
    msg.stamp.sec, msg.stamp.nanosec = sec, nanosec
    msg.polygon.points = [GeoPoint(latitude=lat, longitude=lon, altitude=0.0)
                          for lat, lon in ring]
    return msg


def test_an_area_reaches_the_core_and_a_stale_copy_does_not_replace_it(node):
    assert node.core.has_area is False
    node.on_area(area('a', RING, 100))
    assert node.core.has_area is True
    node.on_area(area('a', BIGGER, 99, 999))             # older stamp: ignored
    assert node.areas.first() == ('a', RING)
    node.on_area(area('a', BIGGER, 101))                 # newer: replaces
    assert node.areas.first() == ('a', BIGGER)


def test_a_boat_with_no_area_subscribes_again_every_thirty_seconds(node):
    limit = node.module.AREA_RETRY_SECONDS
    first = node.area_sub
    start = node._area_asked
    assert node.check_area_subscription(start + limit - 1.0) is False
    assert node.area_sub is first
    assert node.check_area_subscription(start + limit + 0.1) is True
    assert node.area_sub is not first
    assert node.check_area_subscription(start + limit + 1.0) is False    # not again at once
    assert node.check_area_subscription(start + 2 * limit + 0.2) is True


def test_a_boat_with_an_area_does_not_subscribe_again(node):
    node.on_area(area('a', RING, 100))
    first = node.area_sub
    assert node.check_area_subscription(node._area_asked + 1000.0) is False
    assert node.area_sub is first
