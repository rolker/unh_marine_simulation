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
import json
import os
import pathlib
import subprocess
import sys
import time

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


def test_nav_adds_the_launch_argument_or_the_manager_option():
    assert 'enable_nav:=true' in selftest.launch_command(None, None, False, [], nav=True)
    assert not any(a.startswith('enable_nav') for a in selftest.launch_command(
        None, None, False, []))
    assert '--nav' in selftest.launch_command(None, None, False, [], demo=True, nav=True)
    assert '--nav' not in selftest.launch_command(None, None, False, [], demo=True)


def test_the_mission_is_the_shape_camp_sends_and_mission_manager_reads():
    plan = selftest.line_mission('t', (43.0, -70.7), (43.001, -70.7), 4.0)
    (pattern,) = plan
    assert pattern['type'] == 'SurveyPattern' and pattern['label'] == 't_set'
    (line,) = pattern['children']
    assert line['type'] == 'TrackLine' and line['label'] == 't_line'
    assert [w['type'] for w in line['children']] == ['Waypoint', 'Waypoint']
    assert line['children'][1]['latitude'] == 43.001
    command = selftest.mission_command(plan)
    verb, kind, payload = command.split(None, 2)
    assert (verb, kind) == ('replace_task', 'mission_plan')
    assert json.loads(payload) == plan


def test_the_acknowledgement_needs_the_set_and_its_line():
    assert selftest.tasks_acknowledge(['done_hover', 't_set', 't_set/t_line'], 't')
    assert not selftest.tasks_acknowledge(['done_hover', 't_set'], 't')
    assert not selftest.tasks_acknowledge([], 't')


def test_the_watchdog_arguments_per_scenario():
    assert selftest.watchdog_arguments(False, None) == []
    assert selftest.watchdog_arguments(True, None) == ['enable_watchdog:=false']
    pad = selftest.watchdog_arguments(True, 'pad')
    assert 'idle_timeout:=6' in pad and 'missing_pad_grace:=600' in pad
    assert selftest.watchdog_arguments(True, 'attract') == ['missing_pad_grace:=8']
    cmd = selftest.launch_command(None, None, False, [], nav=True, watchdog='pad')
    assert 'enable_nav:=true' in cmd and 'idle_timeout:=6' in cmd
    assert 'enable_watchdog:=false' not in cmd
    demo = selftest.launch_command(None, None, False, [], demo=True, nav=True)
    assert 'enable_watchdog:=false' not in demo and '--no-watchdog' in demo   # the manager owns it
    demo_pad = selftest.launch_command(None, None, False, ['x:=1'], demo=True, nav=True,
                                       watchdog='pad')
    assert '--no-watchdog' not in demo_pad
    assert demo_pad.index('idle_timeout:=6') < demo_pad.index('x:=1')


def test_the_manager_watchdog_options_are_the_self_tests_own():
    assert selftest.overridden_launch_args(['--no-watchdog'], demo=True) == ['--no-watchdog']
    assert selftest.overridden_launch_args(['--watchdog'], demo=True) == ['--watchdog']


@pytest.mark.parametrize('task_id, generation, expected', [
    ('ben_s1', None, True), ('ben_s1/ben_s1_l000', 1, True), ('ben_s10', None, True),
    ('ben_s10', 1, False), ('ben_s10/ben_s10_l003', 1, False), ('ben_s10/ben_s10_l003', 10, True),
    ('ben_s1', 2, False), ('bens_s1', None, False), ('xben_s1', None, False),
    ('ben_s', None, False), ('done_hover', None, False),
    ('ben_eb382a5_s1', 1, True), ('ben_eb382a5_s1/ben_eb382a5_s1_l000', 1, True),
    ('ben_eb382a5_s10', 1, False), ('ben_eb382a5_s2', 1, False), ('ben_xyz_s1', None, False)])
def test_own_task_matches_the_generation_whole(task_id, generation, expected):
    assert selftest.own_task('ben', task_id, generation) is expected


def test_the_watchdog_arguments_are_the_self_tests_own():
    assert selftest.overridden_launch_args(['idle_timeout:=1', 'line_spacing:=60']) == [
        'idle_timeout:=1']
    assert selftest.overridden_launch_args(['enable_watchdog:=true'], True) == [
        'enable_watchdog:=true']


def test_a_pad_at_rest_is_a_message_the_watchdog_takes_for_rest():
    msg = selftest.rest_joy()
    assert list(msg.axes) == selftest.PAD_REST_AXES and not any(msg.buttons)
    assert len(msg.buttons) == selftest.BUTTONS


def test_a_failed_line_is_not_a_completed_line_even_when_it_is_marked_done():
    assert selftest.line_reached(150.0, 160.0, 12.0, '')
    assert selftest.line_reached(180.0, 160.0, 20.0, '')               # where the boat settles
    assert not selftest.line_reached(129.0, 160.0, 71.0, '')           # far from the end
    assert not selftest.line_reached(150.0, 160.0, 12.0, 'failed: survey_line_failed')
    assert not selftest.line_reached(150.0, 160.0, None, '')           # no fix
    assert not selftest.line_reached(20.0, 160.0, 10.0, '')            # barely moved


def test_offset_position_goes_the_given_way():
    lat, lon = selftest.offset_position((43.0, -70.7), 90.0, 111.0)
    assert abs(lat - 43.0) < 1e-9 and lon > -70.7
    lat, lon = selftest.offset_position((43.0, -70.7), 0.0, 111.32)
    assert abs(lat - 43.001) < 1e-6 and abs(lon + 70.7) < 1e-9


def test_extra_launch_args_may_not_override_the_ones_the_self_test_derives():
    assert selftest.overridden_launch_args(
        ['tide_speed_factor:=1', 'boats:=a', 'enable_joysticks:=true',
         'roster_file:=/x.yaml']) == ['boats:=a', 'enable_joysticks:=true',
                                      'roster_file:=/x.yaml']
    # enable_nav is the self-test's own (--nav), like the pads
    assert selftest.overridden_launch_args(['tide_speed_factor:=1', 'enable_nav:=true']) == [
        'enable_nav:=true']
    assert selftest.overridden_launch_args(['--nav', '--no-nav', '--boats', 'x'], True) == [
        '--nav', '--no-nav', '--boats']


def test_main_refuses_overriding_launch_args_before_starting_anything(capsys):
    with pytest.raises(SystemExit) as exit_info:
        selftest.main(['--roster', str(ROSTER), '--start-launch', 'boats:=a'])
    assert exit_info.value.code == 2
    assert 'boats:=a' in capsys.readouterr().err


# --- --demo: the whole display's launch, and the scorer check ---------------------------

def test_demo_command_starts_the_manager_without_a_display():
    cmd = selftest.launch_command(['a'], None, False, ['--config', '/x.yaml'], demo=True)
    assert cmd[:5] == ['ros2', 'run', 'marine_simulation', 'demo_manager.py', '--profile']
    assert cmd[5] == 'headless'
    assert '--no-joysticks' in cmd and cmd[cmd.index('--boats') + 1] == 'a'
    assert cmd[-2:] == ['--config', '/x.yaml']
    assert 'demo_launch.py' not in ' '.join(cmd) and 'camp' not in ' '.join(cmd).replace(
        'marine_simulation', '')


def test_demo_command_forwards_the_roster_and_the_pads():
    cmd = selftest.launch_command(None, '/r.yaml', True, [], demo=True)
    assert cmd[cmd.index('--roster') + 1] == '/r.yaml'
    assert '--no-joysticks' not in cmd and '--boats' not in cmd


def test_the_plain_command_is_unchanged_without_demo():
    cmd = selftest.launch_command(None, None, False, [])
    assert cmd[:4] == ['ros2', 'launch', 'marine_simulation', 'demo_boats_launch.py']
    assert 'demo_manager.py' not in cmd


def test_demo_fixes_which_manager_options_are_the_self_tests_own():
    extra = ['--profile=demo', '--boats', '--no-joysticks', '--roster=/x', '--config', 'y']
    assert selftest.overridden_launch_args(extra, demo=True) == extra[:4]
    assert selftest.overridden_launch_args(extra) == []


def test_survey_area_corners_surround_the_centre():
    corners = selftest.survey_area_corners(43.0, -70.0, 0.01)
    assert len(corners) == 4 and len(set(corners)) == 4
    assert min(c[0] for c in corners) < 43.0 < max(c[0] for c in corners)
    assert min(c[1] for c in corners) < -70.0 < max(c[1] for c in corners)


def test_scorer_centre_is_the_mean_start_of_the_chosen_boats(tmp_path):
    roster = tmp_path / 'roster.yaml'
    roster.write_text(
        'boats:\n'
        '  - {name: a, color: {red: 1, green: 1, blue: 1}, start: {lat: 43.0, lon: -70.0, '
        'heading: 0}}\n'
        '  - {name: b, color: {red: 1, green: 1, blue: 1}, start: {lat: 45.0, lon: -72.0, '
        'heading: 0}}\n'
        '  - {name: c, color: {red: 1, green: 1, blue: 1}, start: {lat: 0.0, lon: 0.0, '
        'heading: 0}}\n')
    assert selftest.scorer_centre(str(roster), ['a', 'b']) == (44.0, -71.0)


# -- Fast DDS discovery server (issue 116) -------------------------------------------------

def test_the_manager_is_started_with_the_discovery_server_only_when_asked():
    on = selftest.launch_command(None, None, False, [], demo=True, discovery_server=True)
    assert '--discovery-server' in on
    assert '--discovery-server' not in selftest.launch_command(None, None, False, [], demo=True)


def test_the_launch_the_selftest_starts_is_not_a_super_client(monkeypatch):
    seen = {}
    monkeypatch.setenv('ROS_SUPER_CLIENT', 'TRUE')
    monkeypatch.setenv('ROS_DISCOVERY_SERVER', '127.0.0.1:11853')
    monkeypatch.setattr(selftest.subprocess, 'Popen',
                        lambda cmd, **kw: seen.update(kw) or object())
    selftest.start_launch(['true'])
    assert 'ROS_SUPER_CLIENT' not in seen['env']
    assert seen['env']['ROS_DISCOVERY_SERVER'] == '127.0.0.1:11853'
    assert os.environ['ROS_SUPER_CLIENT'] == 'TRUE'        # the self-test's own participant


def test_the_server_switch_needs_the_manager_with_start_launch(capsys):
    with pytest.raises(SystemExit):
        selftest.main(['--discovery-server', '--start-launch'])
    assert '--discovery-server needs --demo' in capsys.readouterr().err


class FakePublisher:

    def __init__(self):
        self.sent = []

    def publish(self, msg):
        self.sent.append(msg)


def test_touching_the_pad_leaves_it_sending_at_rest():
    # the pad scenario's last check reads reason idle: a pad silent for longer than
    # pad_lost_timeout after the touch would be a missing pad instead
    test = object.__new__(selftest.SelfTest)
    test.pad_boat, test._next_pad = None, 0.0
    test.joy_pub = {'a': FakePublisher()}
    active = test.touch_pad('a')
    assert test.pad_boat == 'a'
    assert test.joy_pub['a'].sent == [active]
    assert active.axes[selftest.THROTTLE_AXIS] == pytest.approx(0.8)
    test._pad_tick()                                     # not yet due: no double message
    assert len(test.joy_pub['a'].sent) == 1
    test._next_pad = 0.0
    test._pad_tick()
    rest = test.joy_pub['a'].sent[-1]
    assert list(rest.axes) == list(selftest.rest_joy().axes)


def test_watchdog_without_the_manager_is_refused_early():
    with pytest.raises(SystemExit):
        selftest.main(['--watchdog', 'pad'])
    with pytest.raises(SystemExit):
        selftest.main(['--watchdog', 'attract', '--start-launch'])
