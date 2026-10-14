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

"""Tests for scripts/run_demo.sh with a fake ``ros2`` that records its arguments."""

import os
import pathlib
import stat
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / 'scripts' / 'run_demo.sh'


@pytest.fixture
def machine(tmp_path):
    """Return a fake home with fake ros2, pgrep and place_windows on PATH / in reach."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    _script(bin_dir / 'ros2', '#!/bin/sh\nprintf "%s\\n" "$ROS_DOMAIN_ID" "$@" > "$RECORD"\n')
    _script(bin_dir / 'pgrep', '#!/bin/sh\nexit "${FAKE_PGREP_STATUS:-1}"\n')
    _script(tmp_path / 'place_windows.py',
            '#!/bin/sh\nprintf "%s\\n" "$@" > "$RECORD.check"\n'
            'if [ -n "$FAKE_CHECK_FAILS" ]; then echo "place_windows: $FAKE_CHECK_FAILS" >&2;'
            ' exit 2; fi\n')
    config = tmp_path / 'config'
    config.mkdir()
    return tmp_path


def _script(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run(machine, *args, path=True, domain=None, **extra_env):
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(machine), 'RECORD': str(machine / 'record'),
           'DEMO_CONFIG_DIR': str(machine / 'config'),
           'DEMO_PLACE_WINDOWS': str(machine / 'place_windows.py')}
    if path:
        env['PATH'] = str(machine / 'bin') + ':' + env['PATH']
    if domain:
        env['ROS_DOMAIN_ID'] = domain
    env.update(extra_env)
    return subprocess.run(['bash', str(SCRIPT), *args], env=env, capture_output=True,
                          text=True, timeout=30)


def _files(machine, *names):
    for name in names:
        (machine / 'config' / name).write_text('x: 1\n')


def _record(machine):
    return (machine / 'record').read_text().split()


def test_it_launches_the_demo_with_this_machines_files_on_a_private_domain(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml')
    result = _run(machine)
    assert result.returncode == 0, result.stderr
    domain, *args = _record(machine)
    assert domain == '42'
    assert args == ['launch', 'marine_simulation', 'demo_launch.py',
                    'joystick_config:=%s/config/joysticks.yaml' % machine,
                    'layout_config:=%s/config/layout.yaml' % machine]
    assert 'close the map window' in result.stdout


def test_an_exported_domain_is_not_used_but_the_demo_override_is(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml')
    _run(machine, domain='7')
    assert _record(machine)[0] == '42'
    _run(machine, domain='7', DEMO_ROS_DOMAIN_ID='55')
    assert _record(machine)[0] == '55'


def test_extra_arguments_and_the_target_file_are_passed_on(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml', 'target.json')
    _run(machine, 'boats:=a,b')
    args = _record(machine)
    assert 'target_area_file:=%s/config/target.json' % machine in args
    assert args[-1] == 'boats:=a,b'


@pytest.mark.parametrize('missing', ['joysticks.yaml', 'layout.yaml'])
def test_a_missing_machine_file_stops_with_a_plain_message(machine, missing):
    _files(machine, *({'joysticks.yaml', 'layout.yaml'} - {missing}))
    result = _run(machine)
    assert result.returncode == 1
    assert 'DID NOT START' in result.stderr and missing in result.stderr
    assert not (machine / 'record').exists()


def test_a_machine_file_is_not_needed_when_its_part_is_switched_off(machine):
    result = _run(machine, 'enable_joysticks:=false', 'enable_window_layout:=false')
    assert result.returncode == 0, result.stderr
    args = _record(machine)
    assert not any(a.startswith(('joystick_config', 'layout_config')) for a in args)
    assert not (machine / 'record.check').exists()  # nothing to check without a layout


def test_the_layout_is_checked_before_anything_starts(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml')
    _run(machine)
    check = (machine / 'record.check').read_text().split()
    assert check == ['--check', '--layout', '%s/config/layout.yaml' % machine]


def test_a_layout_that_cannot_be_used_stops_with_the_reason_not_a_traceback(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml')
    result = _run(machine, FAKE_CHECK_FAILS='window placement needs an X11 session')
    assert result.returncode == 1
    assert 'DID NOT START' in result.stderr and 'X11 session' in result.stderr
    assert 'Traceback' not in result.stderr and not (machine / 'record').exists()


def test_a_map_window_that_is_already_open_stops_the_demo(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml')
    result = _run(machine, FAKE_PGREP_STATUS='0')
    assert result.returncode == 1 and 'already open' in result.stderr
    assert not (machine / 'record').exists()
    assert _run(machine, 'enable_camp:=false', FAKE_PGREP_STATUS='0').returncode == 0


def test_no_ros_says_how_to_set_it_up(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml')
    result = _run(machine, path=False)
    assert result.returncode == 1 and 'env.bash' in result.stderr


def test_env_bash_is_sourced_first(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml')
    (machine / 'config' / 'env.bash').write_text('export PATH=%s/bin:$PATH\n' % machine)
    result = _run(machine, path=False)
    assert result.returncode == 0, result.stderr


def test_a_failing_env_bash_stops_the_demo(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml')
    (machine / 'config' / 'env.bash').write_text('return 3\n')
    result = _run(machine)
    assert result.returncode == 1 and 'env.bash failed' in result.stderr


def test_no_home_is_refused(machine):
    env = {'PATH': str(machine / 'bin') + ':/usr/bin:/bin'}
    result = subprocess.run(['bash', str(SCRIPT)], env=env, capture_output=True, text=True,
                            timeout=30)
    assert result.returncode == 1 and 'HOME' in result.stderr


def test_the_script_is_executable():
    assert os.access(SCRIPT, os.X_OK)
