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
    """Return a fake home with a ``ros2`` on PATH that records its arguments."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    ros2 = bin_dir / 'ros2'
    ros2.write_text('#!/bin/sh\nprintf "%s\\n" "$ROS_DOMAIN_ID" "$@" > "$RECORD"\n')
    ros2.chmod(ros2.stat().st_mode | stat.S_IXUSR)
    config = tmp_path / 'config'
    config.mkdir()
    return tmp_path


def _run(machine, *args, path=True, domain=None):
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(machine), 'RECORD': str(machine / 'record'),
           'DEMO_CONFIG_DIR': str(machine / 'config')}
    if path:
        env['PATH'] = str(machine / 'bin') + ':' + env['PATH']
    if domain:
        env['ROS_DOMAIN_ID'] = domain
    return subprocess.run(['bash', str(SCRIPT), *args], env=env, capture_output=True,
                          text=True, timeout=30)


def _files(machine, *names):
    for name in names:
        (machine / 'config' / name).write_text('x: 1\n')


def test_it_launches_the_demo_with_this_machines_files_on_a_private_domain(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml')
    result = _run(machine)
    assert result.returncode == 0, result.stderr
    domain, *args = (machine / 'record').read_text().split()
    assert domain == '42'
    assert args == ['launch', 'marine_simulation', 'demo_launch.py',
                    'joystick_config:=%s/config/joysticks.yaml' % machine,
                    'layout_config:=%s/config/layout.yaml' % machine]


def test_a_domain_that_is_already_set_is_kept(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml')
    _run(machine, domain='7')
    assert (machine / 'record').read_text().split()[0] == '7'


def test_extra_arguments_and_the_target_file_are_passed_on(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml', 'target.json')
    _run(machine, 'boats:=a,b')
    args = (machine / 'record').read_text().split()
    assert 'target_area_file:=%s/config/target.json' % machine in args
    assert args[-1] == 'boats:=a,b'


@pytest.mark.parametrize('missing', ['joysticks.yaml', 'layout.yaml'])
def test_a_missing_machine_file_stops_with_a_plain_message(machine, missing):
    _files(machine, *({'joysticks.yaml', 'layout.yaml'} - {missing}))
    result = _run(machine)
    assert result.returncode == 1
    assert 'DID NOT START' in result.stderr and missing in result.stderr
    assert not (machine / 'record').exists()


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


def test_the_script_is_executable():
    assert os.access(SCRIPT, os.X_OK)
