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

"""Tests for scripts/run_demo.sh with a fake ``ros2`` and a fake manager recording their input."""

import os
import pathlib
import stat
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / 'scripts' / 'run_demo.sh'


@pytest.fixture
def machine(tmp_path):
    """Return a fake home with fake ros2, pgrep, place_windows and demo_manager in reach."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    _script(bin_dir / 'ros2',
            '#!/bin/sh\nif [ "$1" = pkg ]; then echo "$FAKE_PREFIX"; exit 0; fi\n'
            'echo "ros2 must not be the launcher: $*" >&2; exit 9\n')
    _script(bin_dir / 'pgrep', '#!/bin/sh\nexit "${FAKE_PGREP_STATUS:-1}"\n')
    _script(tmp_path / 'place_windows.py',
            '#!/bin/sh\nprintf "%s\\n" "$@" > "$RECORD.check"\n'
            'if [ -n "$FAKE_CHECK_FAILS" ]; then echo "place_windows: $FAKE_CHECK_FAILS" >&2;'
            ' exit 2; fi\n')
    _script(tmp_path / 'demo_manager.py',
            '#!/bin/sh\nprintf "%s\\n" "$ROS_DOMAIN_ID" "$@" > "$RECORD"\n'
            'exit "${FAKE_MANAGER_STATUS:-0}"\n')
    config = tmp_path / 'config'
    config.mkdir()
    return tmp_path


def _script(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run(machine, *args, path=True, domain=None, **extra_env):
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(machine), 'RECORD': str(machine / 'record'),
           'DEMO_CONFIG_DIR': str(machine / 'config'),
           'DEMO_PLACE_WINDOWS': str(machine / 'place_windows.py'),
           'DEMO_MANAGER': str(machine / 'demo_manager.py')}
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


def test_it_starts_the_manager_with_this_machines_files_on_a_private_domain(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml')
    result = _run(machine)
    assert result.returncode == 0, result.stderr
    domain, *args = _record(machine)
    assert domain == '42'
    assert args == ['--joysticks', '%s/config/joysticks.yaml' % machine,
                    '--layout', '%s/config/layout.yaml' % machine]
    assert 'close the map window' in result.stdout


def test_it_does_not_launch_through_ros2_or_the_old_launch_file(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml')
    result = _run(machine)
    assert result.returncode == 0, result.stderr
    text = SCRIPT.read_text()
    assert 'demo_launch' not in text and 'ros2 launch' not in text
    assert 'must not be the launcher' not in result.stderr


def test_the_managers_exit_status_is_the_scripts(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml')
    assert _run(machine, FAKE_MANAGER_STATUS='2').returncode == 2


def test_an_exported_domain_is_not_used_but_the_demo_override_is(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml')
    _run(machine, domain='7')
    assert _record(machine)[0] == '42'
    _run(machine, domain='7', DEMO_ROS_DOMAIN_ID='55')
    assert _record(machine)[0] == '55'


def test_the_demo_domain_override_is_checked_and_a_leading_zero_is_not_octal(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml')
    _run(machine, DEMO_ROS_DOMAIN_ID='08')
    assert _record(machine)[0] == '8'
    _run(machine, DEMO_ROS_DOMAIN_ID='101')
    assert _record(machine)[0] == '101'
    (machine / 'record').unlink()
    for bad in ('102', 'abc', '-1', '4 2', '1' * 30):
        result = _run(machine, DEMO_ROS_DOMAIN_ID=bad)
        assert result.returncode == 1, bad
        assert 'DID NOT START' in result.stderr and 'DEMO_ROS_DOMAIN_ID' in result.stderr
        assert not (machine / 'record').exists()
    assert _run(machine, DEMO_ROS_DOMAIN_ID='').returncode == 0  # empty means the default
    assert _record(machine)[0] == '42'


def test_extra_options_and_the_target_file_are_passed_on(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml', 'target.json')
    _run(machine, '--boats', 'a,b')
    args = _record(machine)
    assert ['--target', '%s/config/target.json' % machine] == args[-4:-2]
    assert args[-2:] == ['--boats', 'a,b']


def test_without_a_target_file_the_manager_uses_its_installed_polygon(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml')
    _run(machine)
    assert '--target' not in _record(machine)


def test_a_missing_joystick_file_stops_with_a_plain_message(machine):
    _files(machine, 'layout.yaml')
    result = _run(machine)
    assert result.returncode == 1
    assert 'DID NOT START' in result.stderr and 'joysticks.yaml' in result.stderr
    assert not (machine / 'record').exists()


def test_a_missing_layout_file_means_nothing_to_place_not_an_error(machine):
    _files(machine, 'joysticks.yaml')
    result = _run(machine)
    assert result.returncode == 0, result.stderr
    assert '--layout' not in _record(machine)
    assert not (machine / 'record.check').exists()          # nothing to check either


def test_a_machine_file_is_not_needed_when_its_part_is_switched_off(machine):
    result = _run(machine, '--no-joysticks', '--no-layout')
    assert result.returncode == 0, result.stderr
    args = _record(machine)[1:]
    assert args == ['--no-joysticks', '--no-layout']
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
    # a profile without the map window does not mind one that is open
    assert _run(machine, '--profile', 'headless', FAKE_PGREP_STATUS='0').returncode == 0


def test_the_headless_profile_needs_no_layout_file_and_passes_nothing_for_it(machine):
    _files(machine, 'joysticks.yaml')
    result = _run(machine, '--profile', 'headless')
    assert result.returncode == 0, result.stderr
    args = _record(machine)[1:]
    assert args == ['--joysticks', '%s/config/joysticks.yaml' % machine,
                    '--profile', 'headless']
    assert not (machine / 'record.check').exists()


def test_the_demo_profile_named_out_loud_is_the_default_demo(machine):
    result = _run(machine, '--profile=demo')
    assert result.returncode == 1 and 'joysticks.yaml' in result.stderr
    _files(machine, 'joysticks.yaml')
    result = _run(machine, '--profile', 'demo')
    assert result.returncode == 0 and '--layout' not in _record(machine)


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


def test_a_copy_of_the_script_finds_the_tools_in_the_installed_package(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml')
    lib = machine / 'prefix' / 'lib' / 'marine_simulation'
    lib.mkdir(parents=True)
    for name in ('place_windows.py', 'demo_manager.py'):
        _script(lib / name, (machine / name).read_text())
    copy = machine / 'home_bin' / 'run_demo.sh'
    copy.parent.mkdir()
    copy.write_text(SCRIPT.read_text())
    env = {'PATH': str(machine / 'bin') + ':/usr/bin:/bin', 'HOME': str(machine),
           'RECORD': str(machine / 'record'), 'DEMO_CONFIG_DIR': str(machine / 'config'),
           'FAKE_PREFIX': str(machine / 'prefix')}
    result = subprocess.run(['bash', str(copy)], env=env, capture_output=True, text=True,
                            timeout=30)
    assert result.returncode == 0, result.stderr
    assert (machine / 'record.check').read_text().split()[0] == '--check'
    assert _record(machine)[0] == '42'


def test_files_given_on_the_command_line_replace_the_default_ones(machine):
    other = machine / 'other.yaml'
    other.write_text('x: 1\n')
    result = _run(machine, '--layout', str(other), '--joysticks=%s' % other)
    assert result.returncode == 0, result.stderr  # no default files exist at all
    assert (machine / 'record.check').read_text().split() == ['--check', '--layout', str(other)]
    args = _record(machine)[1:]
    assert args == ['--layout', str(other), '--joysticks', str(other)]


def test_a_layout_or_joystick_file_given_on_the_command_line_must_exist(machine):
    result = _run(machine, '--layout', '%s/nope.yaml' % machine, '--no-joysticks')
    assert result.returncode == 1 and 'nope.yaml' in result.stderr
    result = _run(machine, '--joysticks', '%s/nope.yaml' % machine, '--no-layout')
    assert result.returncode == 1 and 'nope.yaml' in result.stderr


def test_an_option_that_needs_a_value_says_so(machine):
    result = _run(machine, '--layout')
    assert result.returncode == 1 and '--layout needs a value' in result.stderr


def test_a_tilde_in_a_file_option_is_expanded_before_the_manager_sees_it(machine):
    (machine / 'mine.yaml').write_text('x: 1\n')
    result = _run(machine, '--no-joysticks', '--layout', '~/mine.yaml')
    assert result.returncode == 0, result.stderr
    assert ['--layout', '%s/mine.yaml' % machine] == _record(machine)[-2:]


def test_a_path_with_spaces_stays_one_argument(machine):
    spaced = machine / 'my files'
    spaced.mkdir()
    (spaced / 'l.yaml').write_text('x: 1\n')
    result = _run(machine, '--no-joysticks', '--layout', str(spaced / 'l.yaml'))
    assert result.returncode == 0, result.stderr
    assert (machine / 'record').read_text().splitlines()[-1] == str(spaced / 'l.yaml')


def test_help_needs_no_machine_files(machine):
    result = _run(machine, '--help')
    assert result.returncode == 0, result.stderr
    assert _record(machine)[1:] == ['--help']


@pytest.mark.parametrize('option', ['--layout=', '--joysticks=', '--target=', '--profile='])
def test_an_empty_option_value_is_refused_not_replaced_by_a_default(machine, option):
    _files(machine, 'joysticks.yaml', 'layout.yaml')
    result = _run(machine, option)
    assert result.returncode == 1 and 'non-empty value' in result.stderr
    assert not (machine / 'record').exists()


def test_equals_forms_of_the_options_are_read_like_the_separate_forms(machine):
    _files(machine, 'joysticks.yaml')
    result = _run(machine, '--profile=headless', '--target=%s/t.json' % machine)
    assert result.returncode == 0, result.stderr   # no layout needed, no CAMP check
    assert _record(machine)[1:] == ['--joysticks', '%s/config/joysticks.yaml' % machine,
                                    '--profile', 'headless', '--target', '%s/t.json' % machine]


def test_extra_boats_launch_arguments_are_forwarded_to_the_manager_untouched(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml')
    result = _run(machine, 'tide_speed_factor:=1', '--boats', 'a,b', 'cell_size:=2 5')
    assert result.returncode == 0, result.stderr
    lines = (machine / 'record').read_text().splitlines()
    assert lines[-4:] == ['tide_speed_factor:=1', '--boats', 'a,b', 'cell_size:=2 5']


def test_a_domain_of_only_zeros_means_domain_zero(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml')
    assert _run(machine, DEMO_ROS_DOMAIN_ID='0000').returncode == 0
    assert _record(machine)[0] == '0'


# --- GNOME auto-maximize warning --------------------------------------------------------

def _gsettings(machine, answer, status=0):
    _script(machine / 'bin' / 'gsettings',
            '#!/bin/sh\nprintf "%%s\\n" "$*" > "$RECORD.gsettings"\n'
            'echo %s\nexit %d\n' % (answer, status))


def test_auto_maximize_true_warns_in_one_line_naming_the_command_and_still_starts(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml')
    _gsettings(machine, 'true')
    result = _run(machine)
    assert result.returncode == 0, result.stderr
    warnings = [line for line in result.stderr.splitlines() if 'auto-maximize' in line]
    assert len(warnings) == 1 and warnings[0].startswith('WARNING')
    assert 'gsettings set org.gnome.mutter auto-maximize false' in warnings[0]
    # it only reads the setting, never changes it
    assert (machine / 'record.gsettings').read_text().split() == [
        'get', 'org.gnome.mutter', 'auto-maximize']
    assert (machine / 'record').exists()


def test_auto_maximize_false_or_unreadable_or_missing_says_nothing(machine):
    _files(machine, 'joysticks.yaml', 'layout.yaml')
    _gsettings(machine, 'false')
    assert 'auto-maximize' not in _run(machine).stderr
    _gsettings(machine, 'true', status=1)                      # gsettings cannot answer
    assert 'auto-maximize' not in _run(machine).stderr
    result = _run(machine, DEMO_GSETTINGS=str(machine / 'no-such-gsettings'))   # not installed
    assert result.returncode == 0 and 'auto-maximize' not in result.stderr


def test_no_warning_without_the_display(machine):
    _files(machine, 'joysticks.yaml')
    _gsettings(machine, 'true')
    result = _run(machine, '--profile', 'headless')
    assert result.returncode == 0 and 'auto-maximize' not in result.stderr
