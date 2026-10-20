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

"""Tests for scripts/install_demo_shortcut.sh on a fake desktop."""

import os
import pathlib
import shutil
import stat
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / 'scripts' / 'install_demo_shortcut.sh'
RUN_DEMO = SCRIPT.parent / 'run_demo.sh'


def _script(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def home(tmp_path):
    """Return a fake home: a Desktop, a config dir whose env.bash gives a fake ros2, a fake gio."""
    (tmp_path / 'Desktop').mkdir()
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    _script(bin_dir / 'gio', '#!/bin/sh\nprintf "%s\\n" "$@" > "$HOME/gio.record"\n'
                             'exit "${FAKE_GIO_STATUS:-0}"\n')
    _script(bin_dir / 'xdg-user-dir',
            '#!/bin/sh\n[ -n "$FAKE_DESKTOP" ] && echo "$FAKE_DESKTOP" || exit 1\n')
    ros_bin = tmp_path / 'ros' / 'bin'
    ros_bin.mkdir(parents=True)
    _script(ros_bin / 'ros2', '#!/bin/sh\nexit 0\n')
    config = tmp_path / '.config' / 'marine_simulation_demo'
    config.mkdir(parents=True)
    (config / 'env.bash').write_text('export PATH=%s:$PATH\n' % ros_bin)
    _script(tmp_path / 'run_demo.sh', '#!/bin/sh\nexit 0\n')
    return tmp_path


def _run(home, *args, run_demo=None, **extra_env):
    env = {'PATH': str(home / 'bin') + ':/usr/bin:/bin', 'HOME': str(home),
           'DEMO_RUN_DEMO': str(run_demo or home / 'run_demo.sh')}
    env.update(extra_env)
    return subprocess.run(['bash', str(SCRIPT), *args], env=env, capture_output=True,
                          text=True, timeout=30)


def _entry(home, desktop='Desktop'):
    return (home / desktop / 'marine_simulation_demo.desktop').read_text()


def _fields(text):
    return dict(line.split('=', 1) for line in text.splitlines() if '=' in line)


def test_it_puts_a_trusted_executable_launcher_on_the_desktop(home):
    result = _run(home)
    assert result.returncode == 0, result.stderr
    path = home / 'Desktop' / 'marine_simulation_demo.desktop'
    assert os.access(path, os.X_OK)
    fields = _fields(_entry(home))
    assert fields['Type'] == 'Application'
    assert fields['Name'] == 'Ocean Discovery Day Demo'
    assert fields['Terminal'] == 'true'
    assert fields['Exec'] == '"%s" "--hold"' % (home / 'run_demo.sh')
    assert fields['Path'] == str(home)
    assert (home / 'gio.record').read_text().split() == [
        'set', str(path), 'metadata::trusted', 'true']
    assert str(path) in result.stdout and 'marked trusted' in result.stdout


@pytest.mark.skipif(shutil.which('desktop-file-validate') is None,
                    reason='desktop-file-validate is not installed')
def test_the_entry_passes_the_desktop_file_validator(home):
    assert _run(home).returncode == 0
    result = subprocess.run(
        ['desktop-file-validate', str(home / 'Desktop' / 'marine_simulation_demo.desktop')],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_options_are_baked_in_after_hold_and_hold_is_never_doubled(home):
    result = _run(home, '--hold', '--joysticks', '/x/j.yaml', 'tide_speed_factor:=1')
    assert result.returncode == 0, result.stderr
    exec_line = _fields(_entry(home))['Exec']
    assert exec_line == '"%s" "--hold" "--joysticks" "/x/j.yaml" "tide_speed_factor:=1"' % (
        home / 'run_demo.sh')
    assert '--joysticks /x/j.yaml' in result.stdout


def test_the_name_can_be_chosen_in_both_option_forms(home):
    assert _run(home, '--name', 'Boats').returncode == 0
    assert _fields(_entry(home))['Name'] == 'Boats'
    assert _run(home, '--name=Harbour demo').returncode == 0
    assert _fields(_entry(home))['Name'] == 'Harbour demo'
    result = _run(home, '--name', '')
    assert result.returncode == 1 and 'NOT INSTALLED' in result.stderr


def _exec_arguments(exec_value):
    """Decode an Exec value the way the Desktop Entry specification says a launcher does."""
    value = exec_value.replace('\\\\', '\\')  # string level: \\ -> \
    arguments, current, quoted, started, i = [], '', False, False, 0
    while i < len(value):
        c = value[i]
        if quoted and c == '\\':
            current += value[i + 1]
            i += 1
        elif c == '"':
            quoted, started = not quoted, True
        elif c == ' ' and not quoted:
            if started:
                arguments.append(current)
            current, started = '', False
        else:
            current += c
            started = True
        i += 1
    if started:
        arguments.append(current)
    return [a.replace('%%', '%') for a in arguments]


def test_a_path_with_spaces_and_shell_characters_is_quoted_for_the_desktop_entry(home):
    odd = home / 'my demo $x "q" `b` \\n 100%f'
    odd.mkdir()
    _script(odd / 'run_demo.sh', '#!/bin/sh\nexit 0\n')
    result = _run(home, '--joysticks', '/x/a b\\c%u.yaml', run_demo=odd / 'run_demo.sh')
    assert result.returncode == 0, result.stderr
    exec_line = _fields(_entry(home))['Exec']
    assert '%f' not in exec_line.replace('%%', '') and '%u' not in exec_line.replace('%%', '')
    assert _exec_arguments(exec_line) == [
        str(odd / 'run_demo.sh'), '--hold', '--joysticks', '/x/a b\\c%u.yaml']


def test_without_env_bash_it_refuses_and_says_what_to_create(home):
    (home / '.config' / 'marine_simulation_demo' / 'env.bash').unlink()
    result = _run(home)
    assert result.returncode == 1
    assert 'NOT INSTALLED' in result.stderr and 'env.bash is missing' in result.stderr
    assert 'setup.bash' in result.stderr
    assert not (home / 'Desktop' / 'marine_simulation_demo.desktop').exists()


def test_an_env_bash_that_gives_no_ros2_is_refused(home):
    (home / '.config' / 'marine_simulation_demo' / 'env.bash').write_text('true\n')
    result = _run(home)
    assert result.returncode == 1
    assert 'does not put ros2 on the PATH' in result.stderr
    assert not (home / 'Desktop' / 'marine_simulation_demo.desktop').exists()


def test_the_config_dir_override_is_honoured_and_carried_by_the_icon(home):
    other = home / 'elsewhere'
    other.mkdir()
    shutil.copy(home / '.config' / 'marine_simulation_demo' / 'env.bash', other / 'env.bash')
    (home / '.config' / 'marine_simulation_demo' / 'env.bash').unlink()
    assert _run(home, DEMO_CONFIG_DIR=str(other)).returncode == 0
    assert _exec_arguments(_fields(_entry(home))['Exec']) == [
        'env', 'DEMO_CONFIG_DIR=%s' % other, str(home / 'run_demo.sh'), '--hold']


def test_the_check_does_not_inherit_ros_from_the_installing_terminal(home):
    # An env.bash that gives no ros2 must be refused even when the terminal that runs
    # the installer has ros2 on its PATH (a double click will not).
    (home / '.config' / 'marine_simulation_demo' / 'env.bash').write_text('true\n')
    ros_bin = home / 'ros' / 'bin'
    result = _run(home, PATH='%s:%s/bin:/usr/bin:/bin' % (ros_bin, home))
    assert result.returncode == 1
    assert 'does not put ros2 on the PATH' in result.stderr


def test_the_desktop_directory_comes_from_xdg_user_dir_when_it_answers(home):
    custom = home / 'Bureau'
    custom.mkdir()
    result = _run(home, FAKE_DESKTOP=str(custom))
    assert result.returncode == 0, result.stderr
    assert 'Exec=' in _entry(home, 'Bureau')
    assert not (home / 'Desktop' / 'marine_simulation_demo.desktop').exists()


def test_a_missing_desktop_directory_is_refused(home):
    shutil.rmtree(home / 'Desktop')
    result = _run(home)
    assert result.returncode == 1 and 'Desktop does not exist' in result.stderr


def test_a_missing_run_demo_is_refused(home):
    result = _run(home, run_demo=home / 'nowhere' / 'run_demo.sh')
    assert result.returncode == 1 and 'not there' in result.stderr


def test_gio_failing_still_installs_and_says_so(home):
    result = _run(home, FAKE_GIO_STATUS='1')
    assert result.returncode == 0, result.stderr
    assert (home / 'Desktop' / 'marine_simulation_demo.desktop').exists()
    assert 'could not mark it trusted' in result.stdout


def test_without_gio_it_still_installs(home):
    # A PATH holding only what the installer needs, and no gio at all (not the real one).
    (home / 'bin' / 'gio').unlink()
    for tool in ('bash', 'cat', 'chmod', 'dirname', 'env', 'sed'):
        (home / 'bin' / tool).symlink_to(shutil.which(tool))
    result = _run(home, PATH=str(home / 'bin'))
    assert result.returncode == 0, result.stderr
    assert (home / 'Desktop' / 'marine_simulation_demo.desktop').exists()
    assert 'trusted' not in result.stdout


def test_a_copy_beside_run_demo_finds_it_without_the_override(home):
    lib = home / 'prefix' / 'lib' / 'marine_simulation'
    lib.mkdir(parents=True)
    shutil.copy(SCRIPT, lib / 'install_demo_shortcut.sh')
    _script(lib / 'run_demo.sh', '#!/bin/sh\nexit 0\n')
    env = {'PATH': str(home / 'bin') + ':/usr/bin:/bin', 'HOME': str(home)}
    result = subprocess.run(['bash', str(lib / 'install_demo_shortcut.sh')], env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert _fields(_entry(home))['Exec'] == '"%s" "--hold"' % (lib / 'run_demo.sh')


def test_help_prints_the_usage_and_installs_nothing(home):
    result = _run(home, '--help')
    assert result.returncode == 0 and 'install_demo_shortcut.sh' in result.stdout
    assert not (home / 'Desktop' / 'marine_simulation_demo.desktop').exists()


def test_the_scripts_are_executable_and_the_shortcut_runs_the_real_run_demo():
    assert os.access(SCRIPT, os.X_OK) and os.access(RUN_DEMO, os.X_OK)
    assert '--hold' in RUN_DEMO.read_text()
