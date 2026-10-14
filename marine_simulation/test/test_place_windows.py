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

"""Unit tests for scripts/place_windows.py (no display, no wmctrl: a fake runner)."""

import importlib.util
import pathlib

import pytest
import yaml

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = PACKAGE / 'scripts' / 'place_windows.py'
_spec = importlib.util.spec_from_file_location('place_windows', SCRIPT)
pw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pw)

XRANDR = """Monitors: 3
 0: +*HDMI-0 3840/800x2160/450+0+240  HDMI-0
 1: +DP-2 1920/519x1200/320+4966+0  DP-2
 2: +eDP-1-1 1920/381x1080/214+3840+1200  eDP-1-1
"""
LIST_X = """0x01800004  0 crx_x.Google-chrome  host Outlook
0x04200003  0 CCOMAutonomousMissionPlanner.CCOMAutonomousMissionPlanner  host CAMP - map
"""
LIST_G = """0x01800004  0 10 20 800 600  host Outlook
0x04200003  0 100 120 1384 753  host CAMP - map
"""


def _layout(tmp_path, **overrides):
    data = {'timeout_seconds': 5,
            'windows': [{'name': 'camp', 'match': {'wm_class': 'CCOMAutonomousMissionPlanner'},
                         'monitor': 'HDMI-0', 'fullscreen': True}]}
    data.update(overrides)
    path = tmp_path / 'layout.yaml'
    path.write_text(yaml.safe_dump(data))
    return str(path)


def _window_entry(**overrides):
    entry = {'name': 'w', 'match': {'title': 'x'}, 'monitor': 'HDMI-0', 'fullscreen': True}
    entry.update(overrides)
    return entry


# --- parsing ------------------------------------------------------------------------

def test_monitors_are_parsed_with_their_offsets():
    monitors = pw.parse_monitors(XRANDR)
    assert set(monitors) == {'HDMI-0', 'DP-2', 'eDP-1-1'}
    assert monitors['HDMI-0'] == pw.Monitor('HDMI-0', 0, 240, 3840, 2160)
    assert monitors['DP-2'] == pw.Monitor('DP-2', 4966, 0, 1920, 1200)


def test_windows_combine_class_title_and_geometry():
    windows = pw.parse_windows(LIST_X, LIST_G)
    camp = [w for w in windows if 'Mission' in w.wm_class][0]
    assert camp.title == 'CAMP - map'
    assert (camp.x, camp.y, camp.width, camp.height) == (100, 120, 1384, 753)


def test_a_window_without_a_geometry_line_gets_zeros():
    windows = pw.parse_windows(LIST_X, '')
    assert all(w.width == 0 for w in windows) and len(windows) == 2


def test_the_shipped_example_layout_loads_and_places_camp_full_screen():
    placements, timeout = pw.load_layout(str(PACKAGE / 'config' / 'demo_layout.yaml'))
    assert [p.name for p in placements] == ['camp']
    assert placements[0].fullscreen and placements[0].wm_class
    assert timeout > 0


# --- layout refusals ----------------------------------------------------------------

@pytest.mark.parametrize('overrides', [
    {'windows': []},
    {'windows': [_window_entry(fullscreen=False)]},
    {'windows': [_window_entry(rect={'x': 0, 'y': 0, 'width': 10, 'height': 10})]},
    {'windows': [_window_entry(fullscreen=False, rect={'x': 0, 'y': 0, 'width': 10})]},
    {'windows': [_window_entry(fullscreen=False,
                               rect={'x': -1, 'y': 0, 'width': 10, 'height': 10})]},
    {'windows': [_window_entry(fullscreen='yes')]},
    {'windows': [_window_entry(match={})]},
    {'windows': [_window_entry(match={'color': 'red'})]},
    {'windows': [_window_entry(monitor='')]},
    {'windows': [_window_entry(name='')]},
    {'windows': [_window_entry(), _window_entry()]},
    {'windows': [_window_entry(extra=1)]},
    {'timeout_seconds': 0},
    {'timeout_seconds': 'soon'},
    {'surprise': 1},
], ids=['no-windows', 'neither', 'both', 'rect-short', 'rect-negative', 'fullscreen-string',
        'match-empty', 'match-unknown', 'monitor-empty', 'name-empty', 'duplicate-name',
        'unknown-key', 'timeout-zero', 'timeout-text', 'top-level-unknown'])
def test_layout_rejects_a_malformed_file(tmp_path, overrides):
    with pytest.raises(pw.LayoutError):
        pw.load_layout(_layout(tmp_path, **overrides))


def test_layout_that_is_not_a_mapping_is_rejected(tmp_path):
    path = tmp_path / 'layout.yaml'
    path.write_text('- just\n- a list\n')
    with pytest.raises(pw.LayoutError):
        pw.load_layout(str(path))


# --- geometry -----------------------------------------------------------------------

def test_fullscreen_target_is_the_monitor():
    monitors = pw.parse_monitors(XRANDR)
    p = pw.Placement('camp', 'c', '', 'DP-2', True, None)
    assert pw.target_geometry(p, monitors) == (4966, 0, 1920, 1200)


def test_rect_is_relative_to_the_monitor():
    monitors = pw.parse_monitors(XRANDR)
    p = pw.Placement('camp', 'c', '', 'DP-2', False, (10, 20, 800, 600))
    assert pw.target_geometry(p, monitors) == (4976, 20, 800, 600)


def test_a_missing_monitor_names_the_ones_that_exist():
    monitors = pw.parse_monitors(XRANDR)
    p = pw.Placement('camp', 'c', '', 'HDMI-9', True, None)
    with pytest.raises(pw.LayoutError, match='HDMI-9.*DP-2'):
        pw.target_geometry(p, monitors)


def test_a_rect_larger_than_its_monitor_is_refused():
    monitors = pw.parse_monitors(XRANDR)
    p = pw.Placement('camp', 'c', '', 'DP-2', False, (1000, 0, 1000, 600))
    with pytest.raises(pw.LayoutError, match='does not fit'):
        pw.target_geometry(p, monitors)


def test_matching_by_class_and_title():
    windows = pw.parse_windows(LIST_X, LIST_G)
    assert pw.find_window(windows, pw.Placement('a', 'Mission', '', 'm', True, None)).ident == \
        '0x04200003'
    assert pw.find_window(windows, pw.Placement('a', '', 'Outlook', 'm', True, None)).ident == \
        '0x01800004'
    assert pw.find_window(windows, pw.Placement('a', 'Mission', 'Outlook', 'm', True, None)) \
        is None


def test_move_commands_clear_state_then_move_then_fullscreen():
    w = pw.Window('0x1', 'c', 't')
    commands = pw.move_commands(w, (0, 240, 3840, 2160), True)
    assert commands[0][-1] == 'remove,fullscreen,maximized_vert,maximized_horz'
    assert commands[1][-2:] == ['-e', '0,0,240,3840,2160']
    assert commands[2][-1] == 'add,fullscreen'
    assert len(pw.move_commands(w, (0, 0, 10, 10), False)) == 2


# --- placing ------------------------------------------------------------------------

class FakeDesktop:
    """A wmctrl stand-in: windows appear after some polls and may resize themselves."""

    def __init__(self, appear_after=0, resize_once=False, never_moves=False):
        self.polls = 0
        self.appear_after = appear_after
        self.resize_once = resize_once
        self.never_moves = never_moves
        self.geometry = (100, 120, 1384, 753)
        self.calls = []
        self.now = 0.0

    def runner(self, command):
        self.calls.append(list(command))
        if command[:2] == ['wmctrl', '-lx']:
            self.polls += 1
            if self.polls <= self.appear_after:
                return ''
            return '0x04200003  0 CCOMAutonomousMissionPlanner.CCOMAutonomousMissionPlanner' \
                   '  host CAMP\n'
        if command[:2] == ['wmctrl', '-lG']:
            x, y, w, h = self.geometry
            if self.polls <= self.appear_after:
                return ''
            return '0x04200003  0 %d %d %d %d host CAMP\n' % (x, y, w, h)
        if '-e' in command and not self.never_moves:
            _, x, y, w, h = command[-1].split(',')
            self.geometry = (int(x), int(y), int(w), int(h))
            if self.resize_once:
                self.resize_once = False
                self.geometry = (int(x), int(y), 1384, 753)  # the app resized itself
        return ''

    def sleep(self, seconds):
        self.now += seconds

    def clock(self):
        return self.now


def _place(desktop, timeout=10.0):
    monitors = pw.parse_monitors(XRANDR)
    p = pw.Placement('camp', 'CCOMAutonomousMissionPlanner', '', 'HDMI-0', True, None)
    logs = []
    problems = pw.place_all([p], monitors, timeout, runner=desktop.runner,
                            sleep=desktop.sleep, clock=desktop.clock, log=logs.append)
    return problems, logs


def test_a_window_is_found_moved_and_verified():
    desktop = FakeDesktop()
    problems, logs = _place(desktop)
    assert problems == []
    assert desktop.geometry == (0, 240, 3840, 2160)
    assert any('placed camp' in line for line in logs)
    assert ['wmctrl', '-i', '-r', '0x04200003', '-b', 'add,fullscreen'] in desktop.calls


def test_it_waits_for_a_window_that_appears_late():
    desktop = FakeDesktop(appear_after=4)
    problems, _ = _place(desktop)
    assert problems == [] and desktop.polls > 4


def test_a_window_that_resizes_itself_after_the_first_move_is_moved_again():
    desktop = FakeDesktop(resize_once=True)
    problems, logs = _place(desktop)
    assert problems == []
    assert sum('-e' in c for c in desktop.calls) == 2
    assert any('attempt 1' in line for line in logs)


def test_a_window_that_never_appears_is_a_named_problem():
    desktop = FakeDesktop(appear_after=10 ** 6)
    problems, _ = _place(desktop, timeout=3.0)
    assert len(problems) == 1 and "'camp'" in problems[0] and 'did not appear' in problems[0]


def test_a_window_that_will_not_stay_is_a_named_problem():
    desktop = FakeDesktop(never_moves=True)
    problems, _ = _place(desktop)
    assert len(problems) == 1 and 'did not stay' in problems[0]
    assert sum('-e' in c for c in desktop.calls) == 2  # tried twice, then gave up


def test_one_deadline_covers_every_window():
    desktop = FakeDesktop(appear_after=10 ** 6)
    monitors = pw.parse_monitors(XRANDR)
    ps = [pw.Placement(n, 'zzz', '', 'HDMI-0', True, None) for n in ('a', 'b', 'c')]
    problems = pw.place_all(ps, monitors, 3.0, runner=desktop.runner, sleep=desktop.sleep,
                            clock=desktop.clock, log=lambda _: None)
    assert len(problems) == 3 and desktop.now < 3.0 + 2 * pw.POLL_SECONDS


def test_tolerance_accepts_a_title_bar_offset_but_not_a_wrong_size():
    w = pw.Window('0x1', 'c', 't', x=10, y=40, width=800, height=600)
    assert pw.in_place(w, (0, 0, 800, 600))
    assert not pw.in_place(w, (0, 0, 1000, 600))
    assert not pw.in_place(w, (500, 0, 800, 600))


# --- session ------------------------------------------------------------------------

def test_wayland_is_refused_with_the_way_out():
    with pytest.raises(pw.LayoutError, match='X11'):
        pw.check_session({'XDG_SESSION_TYPE': 'wayland', 'DISPLAY': ':0'})


def test_no_display_is_refused():
    with pytest.raises(pw.LayoutError, match='DISPLAY'):
        pw.check_session({'XDG_SESSION_TYPE': 'x11'})


def test_x11_with_a_display_is_accepted():
    pw.check_session({'XDG_SESSION_TYPE': 'x11', 'DISPLAY': ':0'})


def test_a_missing_tool_says_how_to_install_it(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError()
    monkeypatch.setattr(pw.subprocess, 'run', boom)
    with pytest.raises(pw.LayoutError, match='apt install wmctrl'):
        pw.run(['wmctrl', '-l'])


def test_main_exits_2_for_an_unusable_session(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv('XDG_SESSION_TYPE', 'wayland')
    assert pw.main(['--layout', _layout(tmp_path)]) == 2
    assert 'X11' in capsys.readouterr().err
