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

"""Unit tests for the pure helpers in scripts/demo_boats_selftest.py."""

import importlib.util
import pathlib
import sys

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / 'scripts'
ROSTER = pathlib.Path(__file__).resolve().parents[1] / 'config' / 'demo_roster.yaml'
sys.path.insert(0, str(SCRIPTS))  # the self-test imports check_multi_boat_graph
_spec = importlib.util.spec_from_file_location(
    'demo_boats_selftest', SCRIPTS / 'demo_boats_selftest.py')
selftest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(selftest)

EXPECTED = {'one': (1.0, 0.0, 0.0), 'two': (0.0, 0.5, 1.0)}


def test_matching_platforms_have_no_problems():
    assert selftest.platform_problems(dict(EXPECTED), EXPECTED) == []


def test_float32_rounding_of_a_colour_is_accepted():
    seen = {'one': (1.0, 0.0, 0.0), 'two': (0.0, 0.5000000149, 0.9999999404)}
    assert selftest.platform_problems(seen, EXPECTED) == []


def test_a_missing_extra_or_recoloured_platform_is_reported():
    seen = {'one': (0.0, 1.0, 0.0), 'three': (1.0, 1.0, 1.0)}
    problems = selftest.platform_problems(seen, EXPECTED)
    assert any('two never appeared' in p for p in problems)
    assert any('unexpected platform three' in p for p in problems)
    assert any('platform one has colour' in p for p in problems)
    assert len(problems) == 3


def test_roster_colors_cover_every_shipped_boat():
    colors = selftest.roster_colors(str(ROSTER))
    assert len(colors) >= 1
    assert all(len(c) == 3 and all(0.0 <= v <= 1.0 for v in c) for c in colors.values())


def test_launch_command_forwards_boats_roster_and_joysticks():
    assert selftest.launch_command(None, None, False, []) == [
        'ros2', 'launch', 'marine_simulation', 'demo_boats_launch.py',
        'enable_joysticks:=false']
    cmd = selftest.launch_command(['a', 'b'], '/tmp/r.yaml', True, ['tide_speed_factor:=1'])
    assert cmd[4:] == ['enable_joysticks:=true', 'boats:=a,b', 'roster_file:=/tmp/r.yaml',
                       'tide_speed_factor:=1']


def test_check_launch_raises_once_the_launch_has_exited():
    class Proc:
        returncode = None

        def poll(self):
            return self.returncode

    test = selftest.SelfTest.__new__(selftest.SelfTest)  # no ROS node needed
    test.launch = None
    test.check_launch()
    test.launch = Proc()
    test.check_launch()
    test.launch.returncode = 3
    with pytest.raises(selftest.LaunchExited, match='status 3'):
        test.check_launch()
