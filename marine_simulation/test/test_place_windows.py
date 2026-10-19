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


CAMP_LAYOUT = str(pathlib.Path(__file__).resolve().parent / 'camp_maximized_layout.yaml')


def test_a_maximised_camp_layout_loads():
    placements, timeout = pw.load_layout(CAMP_LAYOUT)
    assert [p.name for p in placements] == ['camp']
    assert placements[0].maximized and not placements[0].fullscreen
    assert placements[0].rect is None and placements[0].wm_class
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
    {'windows': 'camp'},
    {'windows': [_window_entry(fullscreen=False)]},
    {'windows': [_window_entry(rect={'x': 0, 'y': 0, 'width': 10, 'height': 10})]},
    {'windows': [_window_entry(fullscreen=False, rect={'x': 0, 'y': 0, 'width': 10})]},
    {'windows': [_window_entry(fullscreen=False,
                               rect={'x': -1, 'y': 0, 'width': 10, 'height': 10})]},
    {'windows': [_window_entry(fullscreen='yes')]},
    {'windows': [_window_entry(fullscreen=True, maximized=True)]},
    {'windows': [_window_entry(fullscreen=False, maximized=True,
                               rect={'x': 0, 'y': 0, 'width': 10, 'height': 10})]},
    {'windows': [_window_entry(fullscreen=False, maximized='yes')]},
    {'windows': [_window_entry(fullscreen=False, maximized=False)]},
    {'windows': [_window_entry(match={})]},
    {'windows': [_window_entry(match={'color': 'red'})]},
    {'windows': [_window_entry(monitor='')]},
    {'windows': [_window_entry(name='')]},
    {'windows': [_window_entry(), _window_entry()]},
    {'windows': [_window_entry(extra=1)]},
    {'timeout_seconds': 0},
    {'timeout_seconds': 'soon'},
    {'timeout_seconds': float('nan')},
    {'timeout_seconds': float('inf')},
    {'surprise': 1},
], ids=['windows-not-a-list', 'neither', 'both', 'rect-short', 'rect-negative',
        'fullscreen-string',
        'fullscreen-and-maximized', 'maximized-and-rect', 'maximized-string', 'maximized-false',
        'match-empty', 'match-unknown', 'monitor-empty', 'name-empty', 'duplicate-name',
        'unknown-key', 'timeout-zero', 'timeout-text', 'timeout-nan', 'timeout-inf',
        'top-level-unknown'])
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

    def __init__(self, appear_after=0, resize_once=False, never_moves=False,
                 maximizes_to=None):
        self.maximizes_to = maximizes_to      # the work area a maximised window gets
        self.polls = 0
        self.appear_after = appear_after
        self.resize_once = resize_once
        self.never_moves = never_moves
        self.geometry = (100, 120, 1384, 753)
        self.calls = []
        self.now = 0.0
        self.state = set()
        # mutter: a client resized to exactly this goes full screen
        self.monitor = (0, 240, 3840, 2160)

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
        if command[:1] == ['xprop']:
            if not self.state:
                return '_NET_WM_STATE:  not found.\n'
            return '_NET_WM_STATE(ATOM) = %s\n' % ', '.join(sorted(self.state))
        if '-b' in command:
            action, *props = command[-1].split(',')
            names = {'fullscreen': '_NET_WM_STATE_FULLSCREEN',
                     'maximized_vert': '_NET_WM_STATE_MAXIMIZED_VERT',
                     'maximized_horz': '_NET_WM_STATE_MAXIMIZED_HORZ'}
            for prop in props:
                if action == 'remove':
                    self.state.discard(names[prop])
                elif '_NET_WM_STATE_FULLSCREEN' not in self.state or prop == 'fullscreen':
                    self.state.add(names[prop])         # a full screen window ignores maximise
            if (action == 'add' and 'maximized_vert' in props and self.maximizes_to
                    and '_NET_WM_STATE_FULLSCREEN' not in self.state):
                self.geometry = self.maximizes_to
        if '-e' in command and not self.never_moves:
            _, x, y, w, h = command[-1].split(',')
            if (int(x), int(y), int(w), int(h)) == self.monitor:
                self.state.add('_NET_WM_STATE_FULLSCREEN')
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


def test_check_layout_accepts_a_maximised_camp_layout_on_a_matching_desktop():
    placements, timeout, monitors = pw.check_layout(CAMP_LAYOUT, X11, Tools())
    assert placements[0].monitor in monitors and timeout > 0


def test_check_layout_names_what_is_wrong(tmp_path):
    path = CAMP_LAYOUT
    with pytest.raises(pw.LayoutError, match='X11'):
        pw.check_layout(path, {'XDG_SESSION_TYPE': 'wayland', 'DISPLAY': ':0'}, Tools())
    with pytest.raises(pw.LayoutError, match='apt install wmctrl'):
        pw.check_layout(path, X11, Tools(wmctrl_ok=False))
    with pytest.raises(pw.LayoutError, match='HDMI-0'):
        pw.check_layout(path, X11, Tools(' 0: +*DP-2 1920/1x1080/1+0+0  DP-2\n'))
    with pytest.raises(pw.LayoutError, match='cannot read'):
        pw.check_layout(str(tmp_path / 'missing.yaml'), X11, Tools())


def test_a_window_that_closes_while_it_is_placed_does_not_stop_the_others():
    desktop = FakeDesktop()
    real = desktop.runner

    def runner(command):
        if '-b' in command and '0x04200003' in command:
            raise pw.LayoutError('wmctrl failed: Cannot find client window')
        return real(command)

    monitors = pw.parse_monitors(XRANDR)
    ps = [pw.Placement('camp', 'CCOMAutonomousMissionPlanner', '', 'HDMI-0', True, None),
          pw.Placement('other', 'zzz', '', 'HDMI-0', True, None)]
    problems = pw.place_all(ps, monitors, 3.0, runner=runner, sleep=desktop.sleep,
                            clock=desktop.clock, log=lambda _: None)
    assert len(problems) == 2
    assert "'camp' could not be placed" in problems[0] and 'did not appear' in problems[1]


def test_a_window_that_appears_while_another_is_placed_is_still_found_after_the_deadline():
    desktop = FakeDesktop()
    real = desktop.runner
    seen = {'late': False}

    def runner(command):
        out = real(command)
        if command[:2] == ['wmctrl', '-lx'] and desktop.now >= 1.0:
            seen['late'] = True
            out += '0x05000001  0 late.late  host LATE\n'
        return out

    monitors = pw.parse_monitors(XRANDR)
    ps = [pw.Placement('camp', 'CCOMAutonomousMissionPlanner', '', 'HDMI-0', True, None),
          pw.Placement('late', 'late', '', 'HDMI-0', True, None)]
    # camp settles in 2 s, which is past the 1 s deadline; late must still get one look.
    problems = pw.place_all(ps, monitors, 1.0, runner=runner, sleep=desktop.sleep,
                            clock=desktop.clock, log=lambda _: None)
    assert seen['late']
    assert not any('did not appear' in p for p in problems)


# --- maximised placement (keeps the title bar and its Close button) --------------------

MAX_ENTRY = {'name': 'camp', 'match': {'wm_class': 'CCOMAutonomousMissionPlanner'},
             'monitor': 'HDMI-0', 'maximized': True}
# HDMI-0 is 3840x2160 at +0+240; a top bar and title bar leave a work area a bit smaller.
WORK_AREA = (0, 292, 3840, 2108)


def test_a_maximized_entry_parses_and_is_not_fullscreen(tmp_path):
    placements, _ = pw.load_layout(_layout(tmp_path, windows=[MAX_ENTRY]))
    assert placements[0].maximized and not placements[0].fullscreen
    assert placements[0].rect is None


def test_a_maximized_placement_targets_the_whole_monitor():
    monitors = pw.parse_monitors(XRANDR)
    placement = pw.Placement('camp', 'c', '', 'HDMI-0', False, None, True)
    assert pw.target_geometry(placement, monitors) == (0, 240, 3840, 2160)


def test_maximize_commands_move_then_maximize_two_properties_at_most():
    w = pw.Window('0x1', 'c', 't')
    commands = pw.move_commands(w, (0, 240, 3840, 2160), False, True)
    assert [c[-1] for c in commands] == ['0,960,780,1920,1080',
                                         'add,maximized_vert,maximized_horz']
    assert all(c[-1] != 'add,fullscreen' for c in commands)


def test_maximize_never_resizes_to_exactly_the_monitor():
    w = pw.Window('0x1', 'c', 't')
    monitor = (0, 240, 3840, 2160)
    commands = pw.move_commands(w, monitor, False, True)
    assert not any(c[-1] == '0,0,240,3840,2160' for c in commands)
    _, x, y, width, height = commands[0][-1].split(',')
    x, y, width, height = int(x), int(y), int(width), int(height)
    assert x > monitor[0] and y > monitor[1]
    assert x + width < monitor[0] + monitor[2] and y + height < monitor[1] + monitor[3]


def _place_maximized(desktop):
    monitors = pw.parse_monitors(XRANDR)
    placement = pw.Placement('camp', 'CCOMAutonomousMissionPlanner', '', 'HDMI-0', False, None,
                             True)
    logs = []
    problems = pw.place_all([placement], monitors, 10.0, runner=desktop.runner,
                            sleep=desktop.sleep, clock=desktop.clock, log=logs.append)
    return problems, logs


def test_a_maximized_window_gets_exactly_this_wmctrl_sequence():
    desktop = FakeDesktop(maximizes_to=WORK_AREA)
    problems, logs = _place_maximized(desktop)
    assert problems == [] and any('placed camp' in line for line in logs)
    sent = [c for c in desktop.calls if c[:2] == ['wmctrl', '-i']]
    assert sent == [
        ['wmctrl', '-i', '-r', '0x04200003', '-b', 'remove,fullscreen'],
        ['wmctrl', '-i', '-r', '0x04200003', '-b', 'remove,maximized_vert,maximized_horz'],
        ['wmctrl', '-i', '-r', '0x04200003', '-e', '0,960,780,1920,1080'],
        ['wmctrl', '-i', '-r', '0x04200003', '-b', 'add,maximized_vert,maximized_horz'],
    ]
    assert desktop.state == {'_NET_WM_STATE_MAXIMIZED_VERT', '_NET_WM_STATE_MAXIMIZED_HORZ'}
    assert desktop.geometry == WORK_AREA        # on the monitor, work area, not full screen


class AlwaysFullscreen(FakeDesktop):
    """A window manager that makes the window full screen whatever is asked."""

    def runner(self, command):
        out = super().runner(command)
        if '-e' in command or '-b' in command:
            self.state = {'_NET_WM_STATE_FULLSCREEN'}
            self.geometry = (0, 240, 3840, 2160)
        return out


class NoXprop(FakeDesktop):
    """A desktop without xprop."""

    def runner(self, command):
        if command[:1] == ['xprop']:
            raise pw.LayoutError('xprop is not installed (sudo apt install x11-utils)')
        return super().runner(command)


def test_a_window_that_comes_back_full_screen_is_not_accepted_and_the_message_names_it():
    # a window manager that makes the window full screen whatever is asked: it covers the
    # whole monitor, so geometry alone would accept it

    problems, logs = _place_maximized(AlwaysFullscreen())
    assert len(problems) == 1 and 'full screen' in problems[0] and 'did not stay' in problems[0]
    assert any('attempt 1' in line and 'full screen' in line for line in logs)
    assert any('attempt 2' in line for line in logs)


def test_a_window_exactly_monitor_sized_after_the_move_is_not_accepted():
    # the trap itself: exactly the monitor rect makes the fake (like mutter) go full screen
    state = frozenset({'_NET_WM_STATE_FULLSCREEN'})
    window = pw.Window('0x04200003', 'c', 't', 0, 240, 3840, 2160)
    assert 'full screen' in pw.maximized_problem(window, (0, 240, 3840, 2160), state)


def test_a_maximized_window_missing_a_flag_is_reported():
    window = pw.Window('0x1', 'c', 't', 0, 292, 3840, 2108)
    state = frozenset({'_NET_WM_STATE_MAXIMIZED_VERT'})
    assert 'horz' in pw.maximized_problem(window, (0, 240, 3840, 2160), state)


# What the live run on this machine showed (mutter, GNOME on Xorg): HDMI-0 is 3840x2160+0+240,
# the work area starts at 66,272 and the title bar is 37 px. wmctrl -lG offsets the client's
# top by the frame once more, so the reported rectangle overruns the monitor bottom.
LIVE_MAXIMIZED = (66, 346, 3774, 2091)
LIVE_FRAME = (0, 0, 37, 0)
BOTH_MAXIMIZED = frozenset(pw.STATE_MAXIMIZED)


def test_the_live_maximized_geometry_is_accepted_with_its_frame_extents():
    window = pw.Window('0x1', 'c', 't', *LIVE_MAXIMIZED)
    assert pw.maximized_problem(window, (0, 240, 3840, 2160), BOTH_MAXIMIZED, LIVE_FRAME) is None
    # without the frame the reported rectangle overruns the monitor bottom (2437 > 2400)
    assert 'position' in pw.maximized_problem(window, (0, 240, 3840, 2160), BOTH_MAXIMIZED)


class LiveDesktop(FakeDesktop):
    """A desktop whose window manager also reports a 37 px title bar."""

    def runner(self, command):
        out = super().runner(command)
        if command[:1] == ['xprop']:
            return out + '_NET_FRAME_EXTENTS(CARDINAL) = 0, 0, 37, 0\n'
        return out


def test_the_live_maximized_window_is_placed_and_logged():
    desktop = LiveDesktop(maximizes_to=LIVE_MAXIMIZED)
    problems, logs = _place_maximized(desktop)
    assert problems == [] and any('placed camp on HDMI-0' in line for line in logs)


def test_the_same_window_on_another_monitor_is_rejected():
    window = pw.Window('0x1', 'c', 't', 4966 + 66, 106, 3774, 2091)   # DP-2, 1920x1200+4966+0
    problem = pw.maximized_problem(window, (0, 240, 3840, 2160), BOTH_MAXIMIZED, LIVE_FRAME)
    assert problem is not None and problem.startswith('position')


def test_each_failed_test_is_named():
    monitor = (0, 240, 3840, 2160)
    fine = pw.Window('0x1', 'c', 't', *LIVE_MAXIMIZED)
    small = pw.Window('0x1', 'c', 't', 100, 300, 1384, 753)
    assert pw.maximized_problem(fine, monitor, frozenset({'_NET_WM_STATE_FULLSCREEN'}),
                                LIVE_FRAME).startswith('state')
    assert pw.maximized_problem(fine, monitor, frozenset(), LIVE_FRAME).startswith('state')
    assert pw.maximized_problem(small, monitor, BOTH_MAXIMIZED, LIVE_FRAME).startswith('coverage')


def test_frame_extents_are_parsed_from_xprop_output():
    text = ('_NET_WM_STATE(ATOM) = _NET_WM_STATE_MAXIMIZED_HORZ, _NET_WM_STATE_FOCUSED\n'
            '_NET_FRAME_EXTENTS(CARDINAL) = 0, 0, 37, 0\n')
    assert pw.parse_frame_extents(text) == (0, 0, 37, 0)
    assert '_NET_WM_STATE_MAXIMIZED_HORZ' in pw.parse_window_state(text)
    assert pw.parse_frame_extents('_NET_FRAME_EXTENTS:  not found.\n') == (0, 0, 0, 0)


def test_the_state_is_parsed_from_xprop_output():
    assert pw.parse_window_state('_NET_WM_STATE:  not found.\n') == frozenset()
    assert pw.parse_window_state(
        '_NET_WM_STATE(ATOM) = _NET_WM_STATE_MAXIMIZED_VERT, _NET_WM_STATE_MAXIMIZED_HORZ\n'
    ) == frozenset(pw.STATE_MAXIMIZED)


def test_a_missing_xprop_is_a_problem_naming_it():

    problems, _ = _place_maximized(NoXprop(maximizes_to=WORK_AREA))
    assert len(problems) == 1 and 'xprop' in problems[0]


def test_a_window_that_stays_small_is_a_problem():
    # a window that neither moves nor maximises stays at 1384x753, far under the coverage
    desktop = FakeDesktop(never_moves=True)
    problems, _ = _place_maximized(desktop)
    assert len(problems) == 1 and 'did not stay' in problems[0]


def test_a_maximized_window_on_the_wrong_monitor_is_a_problem():
    desktop = FakeDesktop(maximizes_to=(3840, 1200, 1920, 1000))       # eDP-1-1, not HDMI-0
    problems, _ = _place_maximized(desktop)
    assert len(problems) == 1 and 'did not stay' in problems[0]


@pytest.mark.parametrize('window, expected', [
    ((0, 292, 3840, 2108), True),
    ((70, 292, 3770, 2108), True),          # a dock on the left
    ((0, 240, 3840, 2160), True),           # covers it exactly
    ((100, 120, 1384, 753), False),         # not maximised at all
    ((0, 292, 3840, 1000), False),          # too short
    ((1920, 292, 3840, 2108), False),       # spills off the right edge
])
def test_maximized_verification_is_geometry_on_the_monitor(window, expected):
    w = pw.Window('0x1', 'c', 't', *window)
    assert pw.maximized_in_place(w, (0, 240, 3840, 2160)) is expected


def test_fullscreen_placement_is_unchanged_by_the_maximized_mode():
    desktop = FakeDesktop()
    problems, _ = _place(desktop)
    assert problems == [] and desktop.geometry == (0, 240, 3840, 2160)
    assert not any(c[-1:] == ['add,maximized_vert,maximized_horz'] for c in desktop.calls)


# --- a layout with no windows is a no-op ---------------------------------------------

@pytest.mark.parametrize('text', ['windows: []\n', 'timeout_seconds: 5\n', 'windows:\n'])
def test_a_layout_with_no_windows_loads_empty(tmp_path, text):
    path = tmp_path / 'layout.yaml'
    path.write_text(text)
    assert pw.load_layout(str(path))[0] == []


def test_the_shipped_layout_places_no_window_and_checks_without_a_session_or_tools():
    path = str(PACKAGE / 'config' / 'demo_layout.yaml')
    assert pw.load_layout(path)[0] == []
    calls = []
    placements, _, monitors = pw.check_layout(path, {}, lambda c: calls.append(c) or '')
    assert placements == [] and monitors == {} and calls == []      # not even wmctrl is needed


def test_placing_nothing_does_not_list_windows_or_wait():
    calls = []
    assert pw.place_all([], {}, 90.0, runner=lambda c: calls.append(c) or '',
                        sleep=lambda s: calls.append(s)) == []
    assert calls == []


def test_main_exits_zero_at_once_for_the_shipped_layout(capsys):
    assert pw.main(['--layout', str(PACKAGE / 'config' / 'demo_layout.yaml')]) == 0
    assert pw.main(['--check', '--layout', str(PACKAGE / 'config' / 'demo_layout.yaml')]) == 0
