#!/usr/bin/env python3
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

"""
Put the demo's windows where the layout file says (X11, needs ``wmctrl``).

    place_windows.py --layout ~/.config/marine_simulation_demo/layout.yaml
    place_windows.py --check --layout ...      # only check, change nothing

The layout file is described in ``config/demo_layout.yaml``. For every window it
names, this waits for the window to appear (up to ``timeout_seconds``, default 90 s), clears its
maximised and full screen state, moves and sizes it on the named monitor (or makes it
full screen or maximised there), then reads the geometry back and, because an application may
resize itself after its first show, applies it once more when it does not match.

Exit status 0 when every window is in place, 1 when one is not (the reason is
printed), 2 for a layout, session or tool that cannot be used at all. The
``wmctrl`` and ``xrandr`` calls go through one function (``run``) so the logic is
tested without a display.
"""

import argparse
import dataclasses
import math
import os
import re
import subprocess
import sys
import time
from typing import Callable, Dict, List, Optional, Sequence

import yaml

DEFAULT_TIMEOUT = 90.0
POLL_SECONDS = 0.5
SETTLE_SECONDS = 1.5
# Time for the window manager to finish un-fullscreening / un-maximising before the
# move; a move sent straight after the clear can be ignored.
CLEAR_SECONDS = 0.3
# wmctrl -lG reports a window's outer position on some window managers and its
# client position on others; a title bar and border are tens of pixels. Sizes must
# match closely, positions only within the decoration allowance.
SIZE_TOLERANCE = 4
POSITION_TOLERANCE = 64

# `N: +[*]name WIDTH/mmxHEIGHT/mm+X+Y output [output ...]`; a monitor made from
# several outputs lists them all after the geometry, and the layout may use the
# monitor's name or any of its outputs.
_MONITOR = re.compile(
    r'^\s*\d+:\s+[+*]*(\S+)\s+(\d+)/\d+x(\d+)/\d+\+(-?\d+)\+(-?\d+)\s*(.*)$')


class LayoutError(Exception):
    """The layout file, the monitors or the session cannot be used."""


@dataclasses.dataclass(frozen=True)
class Monitor:
    name: str
    x: int
    y: int
    width: int
    height: int


@dataclasses.dataclass(frozen=True)
class Window:
    ident: str
    wm_class: str
    title: str
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


@dataclasses.dataclass(frozen=True)
class Placement:
    name: str
    wm_class: str  # substring of "instance.Class" as wmctrl -lx prints it; '' = any
    title: str  # substring of the window title; '' = any
    monitor: str
    fullscreen: bool
    rect: Optional[Sequence[int]]  # x, y, width, height from the monitor's top left
    maximized: bool = False  # fills the monitor's work area and keeps its title bar


def parse_monitors(text: str) -> Dict[str, Monitor]:
    """Parse ``xrandr --listmonitors`` into ``{name: Monitor}`` (by name and by output)."""
    monitors = {}
    for line in text.splitlines():
        m = _MONITOR.match(line)
        if m:
            name, w, h, x, y, outputs = m.groups()
            monitor = Monitor(name, int(x), int(y), int(w), int(h))
            for key in [name] + outputs.split():
                monitors.setdefault(key, monitor)
    return monitors


def parse_windows(listing: str, geometry: str) -> List[Window]:
    """
    Combine ``wmctrl -lx`` (class and title) and ``wmctrl -lG`` (geometry).

    Both list the same windows by id; a window missing from the geometry listing gets
    zeros (the verification then reports it rather than crashing here).
    """
    sizes = {}
    for line in geometry.splitlines():
        parts = line.split(None, 7)
        if len(parts) >= 6:
            try:
                sizes[parts[0]] = tuple(int(v) for v in parts[2:6])
            except ValueError:
                continue
    windows = []
    for line in listing.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        ident, wm_class = parts[0], parts[2]
        title = parts[4] if len(parts) > 4 else ''
        x, y, w, h = sizes.get(ident, (0, 0, 0, 0))
        windows.append(Window(ident, wm_class, title, x, y, w, h))
    return windows


def load_layout(path: str):
    """Read the layout file; return ``(placements, timeout_seconds)``."""
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as error:
        raise LayoutError('cannot read %s: %s' % (path, error)) from None
    if not isinstance(data, dict):
        raise LayoutError('%s: expected a mapping' % path)
    unknown = set(data) - {'timeout_seconds', 'windows'}
    if unknown:
        raise LayoutError('%s: unknown key(s) %s' % (path, ', '.join(sorted(unknown))))
    timeout = data.get('timeout_seconds', DEFAULT_TIMEOUT)
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0):
        raise LayoutError('%s: timeout_seconds must be a positive number' % path)
    entries = data.get('windows')
    if not isinstance(entries, list) or not entries:
        raise LayoutError("%s: expected a non-empty 'windows' list" % path)
    placements = []
    for index, entry in enumerate(entries):
        where = '%s: windows[%d]' % (path, index)
        if not isinstance(entry, dict):
            raise LayoutError('%s: expected a mapping' % where)
        extra = set(entry) - {'name', 'match', 'monitor', 'fullscreen', 'maximized', 'rect'}
        if extra:
            raise LayoutError('%s: unknown key(s) %s' % (where, ', '.join(sorted(extra))))
        name = entry.get('name')
        if not isinstance(name, str) or not name:
            raise LayoutError("%s: needs a 'name'" % where)
        where = '%s: window %r' % (path, name)
        match = entry.get('match')
        if not isinstance(match, dict) or not match or set(match) - {'wm_class', 'title'}:
            raise LayoutError("%s: 'match' needs wm_class and/or title" % where)
        for key, value in match.items():
            if not isinstance(value, str) or not value:
                raise LayoutError('%s: match %s must be a non-empty string' % (where, key))
        monitor = entry.get('monitor')
        if not isinstance(monitor, str) or not monitor:
            raise LayoutError("%s: needs a 'monitor' (see xrandr --listmonitors)" % where)
        fullscreen = entry.get('fullscreen', False)
        if not isinstance(fullscreen, bool):
            raise LayoutError('%s: fullscreen must be true or false' % where)
        maximized = entry.get('maximized', False)
        if not isinstance(maximized, bool):
            raise LayoutError('%s: maximized must be true or false' % where)
        rect = entry.get('rect')
        if int(fullscreen) + int(maximized) + int(rect is not None) != 1:
            raise LayoutError("%s: give exactly one of 'fullscreen: true', 'maximized: true' "
                              "or 'rect'" % where)
        if rect is not None:
            if not isinstance(rect, dict) or set(rect) != {'x', 'y', 'width', 'height'}:
                raise LayoutError('%s: rect needs exactly x, y, width and height' % where)
            values = [rect[k] for k in ('x', 'y', 'width', 'height')]
            if any(isinstance(v, bool) or not isinstance(v, int) for v in values):
                raise LayoutError('%s: rect values must be whole numbers' % where)
            if values[0] < 0 or values[1] < 0 or values[2] < 1 or values[3] < 1:
                raise LayoutError('%s: rect needs x, y >= 0 and width, height >= 1' % where)
            rect = tuple(values)
        placements.append(Placement(name, match.get('wm_class', ''), match.get('title', ''),
                                    monitor, fullscreen, rect, maximized))
    names = [p.name for p in placements]
    if len(set(names)) != len(names):
        raise LayoutError('%s: window names must be unique' % path)
    return placements, float(timeout)


def target_geometry(placement: Placement, monitors: Dict[str, Monitor]):
    """Return ``(x, y, width, height)`` on the desktop for a placement."""
    monitor = monitors.get(placement.monitor)
    if monitor is None:
        raise LayoutError('window %r: monitor %r is not connected (xrandr lists %s)'
                          % (placement.name, placement.monitor,
                             ', '.join(sorted(monitors)) or 'none'))
    if placement.fullscreen or placement.maximized:
        return monitor.x, monitor.y, monitor.width, monitor.height
    x, y, width, height = placement.rect
    if x + width > monitor.width or y + height > monitor.height:
        raise LayoutError('window %r: rect %dx%d at +%d+%d does not fit monitor %s (%dx%d)'
                          % (placement.name, width, height, x, y, monitor.name,
                             monitor.width, monitor.height))
    return monitor.x + x, monitor.y + y, width, height


def find_window(windows: Sequence[Window], placement: Placement) -> Optional[Window]:
    """
    Return the newest window that matches, or None.

    The newest (highest id) because a window left over from an earlier run, or one
    the operator opened, is older than the one the demo just started.
    """
    matches = []
    for window in windows:
        if placement.wm_class and placement.wm_class not in window.wm_class:
            continue
        if placement.title and placement.title not in window.title:
            continue
        matches.append(window)
    if not matches:
        return None
    return max(matches, key=lambda w: int(w.ident, 16))


def in_place(window: Window, geometry) -> bool:
    """Return True when ``window`` is at ``geometry`` within the tolerances."""
    x, y, width, height = geometry
    return (abs(window.width - width) <= SIZE_TOLERANCE and
            abs(window.height - height) <= SIZE_TOLERANCE and
            abs(window.x - x) <= POSITION_TOLERANCE and
            abs(window.y - y) <= POSITION_TOLERANCE)


# A maximised window fills the monitor's work area, not the monitor: the top bar and a dock
# take space and the title bar and border take more. It counts as in place when it lies on
# its monitor and covers most of it. This is a geometry check, as for the other two modes
# (the window manager's state flags are not read).
MAXIMIZED_MIN_COVERAGE = 0.85


def maximized_in_place(window: Window, monitor_geometry) -> bool:
    """Return True when ``window`` lies on the monitor and covers most of it."""
    x, y, width, height = monitor_geometry
    return (window.x >= x - SIZE_TOLERANCE and window.y >= y - SIZE_TOLERANCE and
            window.x + window.width <= x + width + SIZE_TOLERANCE and
            window.y + window.height <= y + height + SIZE_TOLERANCE and
            window.width >= MAXIMIZED_MIN_COVERAGE * width and
            window.height >= MAXIMIZED_MIN_COVERAGE * height)


def clear_commands(window: Window) -> List[List[str]]:
    """
    Return the wmctrl calls that clear full screen and maximised state.

    wmctrl's ``-b`` reads at most two properties, so full screen and the two
    maximised flags need two calls.
    """
    return [['wmctrl', '-i', '-r', window.ident, '-b', 'remove,fullscreen'],
            ['wmctrl', '-i', '-r', window.ident, '-b', 'remove,maximized_vert,maximized_horz']]


def move_commands(window: Window, geometry, fullscreen: bool,
                  maximized: bool = False) -> List[List[str]]:
    """Return the wmctrl calls that put a window at ``geometry`` (after clearing it)."""
    x, y, width, height = geometry
    commands = [['wmctrl', '-i', '-r', window.ident, '-e',
                 '0,%d,%d,%d,%d' % (x, y, width, height)]]
    if fullscreen:
        commands.append(['wmctrl', '-i', '-r', window.ident, '-b', 'add,fullscreen'])
    if maximized:
        commands.append(['wmctrl', '-i', '-r', window.ident, '-b',
                         'add,maximized_vert,maximized_horz'])
    return commands


def run(command: Sequence[str]) -> str:
    """Run a command and return its output; raise LayoutError when it cannot run."""
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True,
                              timeout=20).stdout
    except FileNotFoundError:
        raise LayoutError('%s is not installed (sudo apt install wmctrl)' % command[0]) \
            from None
    except subprocess.SubprocessError as error:
        raise LayoutError('%s failed: %s' % (' '.join(command), error)) from None


def list_windows(runner: Callable[[Sequence[str]], str]) -> List[Window]:
    """Return the desktop's windows with class, title and geometry."""
    return parse_windows(runner(['wmctrl', '-lx']), runner(['wmctrl', '-lG']))


def place_all(placements: Sequence[Placement], monitors: Dict[str, Monitor],
              timeout: float, runner: Callable[[Sequence[str]], str] = run,
              sleep: Callable[[float], None] = time.sleep,
              clock: Callable[[], float] = time.monotonic,
              log: Callable[[str], None] = print) -> List[str]:
    """
    Place every window; return the problems (an empty list when all are in place).

    The wait for windows is one deadline for the whole layout, so a window that
    never appears costs ``timeout`` seconds once, not once per window.
    """
    geometries = {p.name: target_geometry(p, monitors) for p in placements}
    problems = []
    pending = list(placements)
    deadline = clock() + timeout
    while True:
        # The listing taken at or after the deadline is the last one.
        last = clock() >= deadline
        windows = list_windows(runner)
        for placement in list(pending):
            window = find_window(windows, placement)
            if window is None:
                continue
            pending.remove(placement)
            problem = settle(window, placement, geometries[placement.name], runner, sleep, log)
            if problem:
                problems.append(problem)
        # One look after the deadline too: placing a window takes seconds, and a
        # window that appeared meanwhile must not be reported as missing.
        if not pending or last:
            break
        sleep(POLL_SECONDS)
    for placement in pending:
        problems.append('window %r (%s) did not appear within %.0f s'
                        % (placement.name, describe(placement), timeout))
    return problems


def describe(placement: Placement) -> str:
    """Return how a placement finds its window, for messages."""
    parts = []
    if placement.wm_class:
        parts.append('class contains %r' % placement.wm_class)
    if placement.title:
        parts.append('title contains %r' % placement.title)
    return ' and '.join(parts)


def geometry_text(x, y, width, height) -> str:
    """Return a geometry as ``WxH+X+Y`` for messages."""
    return '%dx%d+%d+%d' % (width, height, x, y)


def settle(window: Window, placement: Placement, geometry, runner, sleep, log) -> Optional[str]:
    """Move one window, verify it, and move it once more if it did not stay."""
    wanted = geometry_text(*geometry)
    for attempt in (1, 2):
        try:
            for command in clear_commands(window):
                runner(command)
            sleep(CLEAR_SECONDS)
            for command in move_commands(window, geometry, placement.fullscreen,
                                         placement.maximized):
                runner(command)
            sleep(SETTLE_SECONDS)
            now = next((w for w in list_windows(runner) if w.ident == window.ident), None)
        except LayoutError as error:
            # A window that closed under us (a splash screen) must not stop the others.
            return 'window %r could not be placed: %s' % (placement.name, error)
        if now is None:
            return 'window %r disappeared while it was being placed' % placement.name
        window = now
        if (maximized_in_place(window, geometry) if placement.maximized
                else in_place(window, geometry)):
            log('placed %s on %s at %s' % (placement.name, placement.monitor, wanted))
            return None
        log('%s is at %s, wanted %s (attempt %d)' % (
            placement.name, geometry_text(window.x, window.y, window.width, window.height),
            wanted, attempt))
    return 'window %r did not stay at %s; it is at %s' % (
        placement.name, wanted, geometry_text(window.x, window.y, window.width, window.height))


def check_session(environ=os.environ) -> None:
    """
    Raise unless this is an X11 session.

    ``XDG_SESSION_TYPE`` is ``x11`` on a normal login. Where it is unset or ``tty``
    (a session started from a console or a service) an X display with no Wayland
    display is accepted as X11 too.
    """
    session = environ.get('XDG_SESSION_TYPE', '')
    if session in ('', 'tty'):
        if environ.get('WAYLAND_DISPLAY') or not environ.get('DISPLAY'):
            raise LayoutError('window placement needs an X11 session (DISPLAY %s, '
                              'WAYLAND_DISPLAY %s); log in with "GNOME on Xorg"'
                              % (environ.get('DISPLAY') or 'unset',
                                 environ.get('WAYLAND_DISPLAY') or 'unset'))
    elif session != 'x11':
        raise LayoutError('window placement needs an X11 session, this one is %r (log in '
                          'with "GNOME on Xorg")' % session)
    if not environ.get('DISPLAY'):
        raise LayoutError('DISPLAY is not set')


def check_layout(path: str, environ=os.environ, runner=None):
    """
    Check everything placement needs; return ``(placements, timeout, monitors)``.

    The session is X11, a window manager answers to ``wmctrl`` (which also proves it
    is installed), the layout file is well formed and every monitor it names is
    connected. Raises LayoutError with the reason otherwise.
    """
    runner = runner or run
    check_session(environ)
    placements, timeout = load_layout(os.path.expanduser(path))
    runner(['wmctrl', '-m'])
    monitors = parse_monitors(runner(['xrandr', '--listmonitors']))
    for placement in placements:
        target_geometry(placement, monitors)
    return placements, timeout, monitors


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    parser.add_argument('--layout', required=True, help='layout YAML file')
    parser.add_argument('--check', action='store_true',
                        help='only check the session, tools, layout and monitors')
    args = parser.parse_args(argv)
    try:
        placements, timeout, monitors = check_layout(args.layout)
        if args.check:
            print('place_windows: layout %s is usable' % args.layout)
            return 0
        problems = place_all(placements, monitors, timeout)
    except (LayoutError, OSError, yaml.YAMLError) as error:
        print('place_windows: %s' % error, file=sys.stderr)
        return 2
    for problem in problems:
        print('place_windows: PROBLEM: %s' % problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
