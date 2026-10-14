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


def test_windows_with_spaces_in_the_title_a_sticky_desktop_and_negative_positions():
    listing = ('0x01  -1 gjs.Gjs  host Desktop Icons 1\n'
               '0x02   0 a.B  host \n'
               '0x03   1 CCOM.CCOM  host  A title  with   spaces\n')
    geometry = ('0x01  -1 0 0 1920 1080  host Desktop Icons 1\n'
                '0x02   0 -1920 -30 800 600  host \n'
                '0x03   1 5 6 7 8  host  A title  with   spaces\n')
    windows = pw.parse_windows(listing, geometry)
    assert [w.ident for w in windows] == ['0x01', '0x02', '0x03']
    assert windows[0].title == 'Desktop Icons 1' and windows[1].title == ''
    assert (windows[1].x, windows[1].y) == (-1920, -30)
    assert windows[2].title.split() == 'A title with spaces'.split()


def test_monitors_with_negative_offsets_and_several_outputs():
    text = (' 0: +*HDMI-0 3840/800x2160/450+0+0  HDMI-0\n'
            ' 1: +DP-2 1920/519x1200/320+-1920+120  DP-2\n'
            ' 2: +Wall 3840/1x1080/1+3840+0  DP-4 DP-5\n')
    monitors = pw.parse_monitors(text)
    assert monitors['DP-2'].x == -1920 and monitors['DP-2'].y == 120
    wall = pw.Monitor('Wall', 3840, 0, 3840, 1080)
    assert monitors['Wall'] == monitors['DP-4'] == monitors['DP-5'] == wall


def test_the_newest_matching_window_wins():
    listing = ('0x0100  0 CAMP.CAMP  host old\n0x0300  0 CAMP.CAMP  host new\n'
               '0x0200  0 CAMP.CAMP  host middle\n')
    windows = pw.parse_windows(listing, '')
    found = pw.find_window(windows, pw.Placement('c', 'CAMP', '', 'm', True, None))
    assert found.title == 'new'


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


def test_clear_commands_never_send_more_than_two_properties():
    w = pw.Window('0x1', 'c', 't')
    commands = pw.clear_commands(w)
    assert [c[-1] for c in commands] == ['remove,fullscreen',
                                         'remove,maximized_vert,maximized_horz']
    assert all(len(c[-1].split(',')) <= 3 for c in commands)  # action + two properties


def test_move_commands_move_then_fullscreen():
    w = pw.Window('0x1', 'c', 't')
    commands = pw.move_commands(w, (0, 240, 3840, 2160), True)
    assert commands[0][-2:] == ['-e', '0,0,240,3840,2160']
    assert commands[1][-1] == 'add,fullscreen'
    assert len(pw.move_commands(w, (0, 0, 10, 10), False)) == 1


def test_the_window_manager_gets_a_pause_between_clearing_and_moving():
    desktop = FakeDesktop()
    sleeps = []
    pw.settle(pw.Window('0x04200003', 'c', 't'),
              pw.Placement('camp', 'c', '', 'HDMI-0', True, None), (0, 240, 3840, 2160),
              desktop.runner, lambda s: (sleeps.append(s), desktop.sleep(s)), lambda _: None)
    order = [c for c in desktop.calls if c[0] == 'wmctrl' and c[1] == '-i']
    assert order[0][-1] == 'remove,fullscreen' and '-e' in order[2]
    assert sleeps[0] == pw.CLEAR_SECONDS


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
        if '-b' in command:
            # wmctrl reads at most two properties after add/remove/toggle.
            action, *props = command[-1].split(',')
            assert action in ('add', 'remove', 'toggle') and 1 <= len(props) <= 2, command
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
    assert desktop.polls == 7  # t = 0, 0.5, ... 3.0: one last look at the deadline


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
    assert len(problems) == 3
    assert desktop.polls == 7  # one wait for all three windows, not three waits


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


@pytest.mark.parametrize('session', ['', 'tty'])
def test_an_x_display_without_a_session_type_is_accepted(session):
    pw.check_session({'XDG_SESSION_TYPE': session, 'DISPLAY': ':0'})
    pw.check_session({'DISPLAY': ':0'})


@pytest.mark.parametrize('environ', [
    {'XDG_SESSION_TYPE': 'tty'}, {}, {'DISPLAY': ':0', 'WAYLAND_DISPLAY': 'wayland-0'}])
def test_no_x_display_or_a_wayland_one_is_still_refused(environ):
    with pytest.raises(pw.LayoutError, match='X11'):
        pw.check_session(environ)


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


# --- check_layout / --check -----------------------------------------------------

class Tools:
    """A runner standing in for wmctrl and xrandr."""

    def __init__(self, xrandr=XRANDR, wmctrl_ok=True):
        self.xrandr = xrandr
        self.wmctrl_ok = wmctrl_ok

    def __call__(self, command):
        if command[0] == 'wmctrl':
            if not self.wmctrl_ok:
                raise pw.LayoutError('wmctrl is not installed (sudo apt install wmctrl)')
            return 'Name: Mutter\n'
        return self.xrandr


X11 = {'XDG_SESSION_TYPE': 'x11', 'DISPLAY': ':0'}


def test_check_layout_accepts_the_shipped_example_on_a_matching_desktop():
    placements, timeout, monitors = pw.check_layout(
        str(PACKAGE / 'config' / 'demo_layout.yaml'), X11, Tools())
    assert placements[0].monitor in monitors and timeout > 0


def test_check_layout_names_what_is_wrong(tmp_path):
    path = str(PACKAGE / 'config' / 'demo_layout.yaml')
    with pytest.raises(pw.LayoutError, match='X11'):
        pw.check_layout(path, {'XDG_SESSION_TYPE': 'wayland', 'DISPLAY': ':0'}, Tools())
    with pytest.raises(pw.LayoutError, match='apt install wmctrl'):
        pw.check_layout(path, X11, Tools(wmctrl_ok=False))
    with pytest.raises(pw.LayoutError, match='HDMI-0'):
        pw.check_layout(path, X11, Tools(' 0: +*DP-2 1920/1x1080/1+0+0  DP-2\n'))
    with pytest.raises(pw.LayoutError, match='cannot read'):
        pw.check_layout(str(tmp_path / 'missing.yaml'), X11, Tools())
