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
import os
import pathlib
import subprocess
import sys
import time

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / 'scripts'
ROSTER = pathlib.Path(__file__).resolve().parents[1] / 'config' / 'demo_roster.yaml'
PARAMS = pathlib.Path(__file__).resolve().parents[1] / 'config' / 'demo_params.yaml'
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


def test_fake_joy_axes_match_the_joy_to_helm_config():
    # The self-test drives joy_to_helm with fake pad messages, so its axis numbers
    # must be the ones demo_params.yaml configures, or it drives the wrong control.
    import yaml
    params = yaml.safe_load(PARAMS.read_text())['/**/joy_to_helm']['ros__parameters']
    assert (selftest.THROTTLE_AXIS, selftest.SLOW_MODE_AXIS, selftest.RUDDER_AXIS) == (
        params['throttle_axis'], params['slow_mode_axis'], params['rudder_axis'])
    for button in ('manual_button', 'standby_button', 'autonomous_button'):
        assert params[button] < selftest.BUTTONS


def test_fake_joy_is_shaped_so_joy_to_helm_reads_it():
    # joy_to_helm reads buttons[9] and buttons[10] on every message and drops a
    # message with fewer buttons.
    msg = selftest.fake_joy(0.5, -0.25, full_speed=True)
    assert len(msg.axes) == selftest.AXES and len(msg.buttons) == selftest.BUTTONS
    assert selftest.BUTTONS >= 11
    assert msg.axes[selftest.THROTTLE_AXIS] == 0.5
    assert msg.axes[selftest.RUDDER_AXIS] == -0.25
    assert msg.axes[selftest.SLOW_MODE_AXIS] < 0
    assert selftest.fake_joy(0.5, 0.0, full_speed=False).axes[selftest.SLOW_MODE_AXIS] > 0


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


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    with open('/proc/%d/stat' % pid) as f:
        return f.read().rsplit(')', 1)[1].split()[0] != 'Z'  # a zombie is dead


def test_stop_launch_kills_children_that_outlive_the_leader():
    # The leader exits on SIGINT; its child ignores SIGINT and would be left behind.
    proc = subprocess.Popen(
        ['sh', '-c', 'sleep 60 & echo $!; trap "exit 0" INT; wait'],
        stdout=subprocess.PIPE, text=True, start_new_session=True)
    child = int(proc.stdout.readline())
    try:
        assert _alive(child)
        selftest.stop_launch(proc)
        deadline = time.monotonic() + 5.0
        while _alive(child) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _alive(child), 'a child of the launch survived stop_launch'
        assert proc.poll() is not None
    finally:
        if _alive(child):
            os.kill(child, 9)
        proc.stdout.close()


def test_stop_launch_on_an_already_exited_launch_is_quiet():
    proc = subprocess.Popen(['true'], start_new_session=True)
    proc.wait()
    selftest.stop_launch(proc)


def test_extra_launch_args_may_not_override_the_ones_the_self_test_derives():
    assert selftest.overridden_launch_args(
        ['tide_speed_factor:=1', 'boats:=a', 'enable_joysticks:=true',
         'roster_file:=/x.yaml']) == ['boats:=a', 'enable_joysticks:=true',
                                      'roster_file:=/x.yaml']
    assert selftest.overridden_launch_args(['tide_speed_factor:=1', 'enable_nav:=true']) == []


def test_main_refuses_overriding_launch_args_before_starting_anything(capsys):
    with pytest.raises(SystemExit) as exit_info:
        selftest.main(['--roster', str(ROSTER), '--start-launch', 'boats:=a'])
    assert exit_info.value.code == 2
    assert 'boats:=a' in capsys.readouterr().err
