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
Shared helpers of the demo: CAMP's settings, the one-demo lock, the scorer's parameters.

The launch manager's starter (``scripts/demo_manager.py``) and the launch files its groups run
(``demo_camp_launch.py``, ``demo_target_area_launch.py``, ``demo_layout_launch.py``) import this
module; nothing is loaded by file path. Everything that can be checked without a launch
context is a plain module-level function so it can be unit tested.

The boat names come from the roster only (``marine_simulation.roster``). The scorer parameters
and CAMP's live coverage layers are generated from it at start, so no boat name is copied into
a second file.
"""

import fcntl
import math
import os
import re
import shutil
import struct
import subprocess
from typing import Dict, List, Optional, Sequence, Tuple

from ament_index_python.packages import get_package_prefix
from ament_index_python.packages import get_package_share_directory
from launch import LaunchContext
from launch.actions import DeclareLaunchArgument
from launch.actions import ExecuteProcess
from launch.actions import LogInfo
from launch.actions import RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
import yaml

# Where a launch keeps what it generates. It is rebuilt from nothing on every
# start so a previous session can never leave the next one in a different state.
STATE_PARTS = ('.local', 'state', 'marine_simulation_demo')
SETTINGS_ROOT_NAME = 'xdg_config'
CACHE_DIR_NAME = 'live_tile_cache'
# QSettings names CAMP sets in main.cpp: <root>/<organisation>/<application>.conf.
CAMP_ORGANISATION = 'UNH-CCOMJHC'
CAMP_APPLICATION = 'CCOMAutonomousMissionPlanner'
# Dropped into the settings root when this launch creates it. A directory that
# exists without it is somebody else's and is never deleted.
ROOT_MARKER = '.marine_simulation_demo'

# The namespace CAMP's live coverage layer is keyed by for a boat (read from a
# real CAMP settings file: live:%2F<boat>%2Fsensors%2Fmbes%2Fcube_bathymetry).
LIVE_SOURCE_NAMESPACE = '/%s/sensors/mbes/cube_bathymetry'

# The target-area publisher (issue #93) is a script of this package.
TARGET_AREA_EXECUTABLE = 'publish_survey_area.py'
TARGET_AREA_NODE_NAME = 'survey_area_publisher'

_EARTH_RADIUS = 6378137.0  # camp_map/map_view/web_mercator.cpp: earth_radius_at_equator


# --- CAMP settings profile ----------------------------------------------------------

def web_mercator(lat: float, lon: float) -> Tuple[float, float]:
    """Return CAMP's map (scene) coordinates for a WGS84 point, as ``geoToMap`` does."""
    x = math.radians(lon) * _EARTH_RADIUS
    y = math.asinh(math.tan(math.radians(lat))) * _EARTH_RADIUS
    return x, y


_NAMED_ESCAPES = {7: '\\a', 8: '\\b', 9: '\\t', 10: '\\n', 11: '\\v', 12: '\\f', 13: '\\r'}
_HEX_DIGITS = frozenset(b'0123456789abcdefABCDEF')


def qt_point_variant(x: float, y: float) -> str:
    """
    Return the value text QSettings writes to an INI file for a ``QPointF``.

    ``@Variant(`` plus the type id (26) and two big-endian doubles, escaped the way
    Qt's INI writer escapes them. Checked byte for byte against Qt 5.15's own output
    (``test_demo_support.py`` pins samples; 5000 random points matched when this was
    written). CAMP reads ``MainWindow/mapCenter`` and ``MapView/mapView/center`` with
    ``toPointF()``.
    """
    raw = struct.pack('>I', 26) + struct.pack('>dd', x, y)
    out = []
    after_escape = False  # a hex digit right after \x.. or \0 would be read into it
    for byte in raw:
        if byte == 0x5c:
            out.append('\\\\')
            after_escape = False
        elif byte == 0:
            out.append('\\0')
            after_escape = True
        elif byte == 0x22:
            out.append('\\"')
            after_escape = False
        elif byte in _NAMED_ESCAPES:
            out.append(_NAMED_ESCAPES[byte])
            after_escape = False
        elif byte < 0x20 or byte > 0x7e or (after_escape and byte in _HEX_DIGITS):
            out.append('\\x%x' % byte)
            after_escape = True
        else:
            out.append(chr(byte))
            after_escape = False
    text = '@Variant(' + ''.join(out) + ')'
    if any(c in text for c in ',;='):
        text = '"' + text + '"'
    return text


def qt_ini_string(text: str) -> str:
    """Return ``text`` as QSettings writes a string value into an INI file."""
    escaped = text.replace('\\', '\\\\').replace('"', '\\"')
    if any(c in text for c in ',;=') or text != text.strip() or not text:
        return '"%s"' % escaped
    return escaped


def parse_profile(text: str) -> Dict[str, List[str]]:
    """Split a CAMP settings file into ``{section: [raw "key=value" lines]}``."""
    sections: Dict[str, List[str]] = {}
    current = None
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(';'):
            continue
        if stripped.startswith('['):
            if not stripped.endswith(']') or len(stripped) < 3:
                raise ValueError('settings profile line %d: bad section %r' % (number, line))
            current = stripped[1:-1]
            sections.setdefault(current, [])
        elif current is None or '=' not in stripped:
            raise ValueError('settings profile line %d: expected key=value inside a '
                             'section, got %r' % (number, line))
        else:
            sections[current].append(stripped)
    return sections


def live_layer_key(boat: str) -> str:
    """Return the ``MapItem`` group name of the boat's live coverage layer."""
    namespace = LIVE_SOURCE_NAMESPACE % boat
    # CAMP: "live:" + percent-encoded namespace, then QSettings percent-encodes the
    # result again (':' becomes %3A and each '%' becomes %25).
    inner = 'live:' + namespace.replace('/', '%2F')
    return inner.replace('%', '%25').replace(':', '%3A')


# What CAMP writes about its own window and map when it closes (mainwindow.cpp, camp#90), and
# what the demo keeps from one start to the next. Everything else (layers, sources) comes
# from the template every start.
SAVED_WINDOW_KEYS = ('geometry', 'state')
SAVED_VIEW_KEYS = ('mapCenter', 'mapScale')


def _key_of(line: str) -> str:
    return line.split('=', 1)[0].strip()


def carry_over(saved_text: str) -> Dict[str, List[str]]:
    """
    Return the part of a settings file CAMP wrote that the next start keeps.

    ``{'MainWindow': [raw lines of geometry, state, mapCenter, mapScale that are present],
    'MapView': [every raw line of that section]}``, with the empty ones left out. The lines
    are kept exactly as CAMP wrote them (``geometry`` is a Qt-escaped byte array that must not
    be re-encoded). The view is kept only whole: a ``mapCenter`` without a ``mapScale``, or the
    reverse, is dropped (together with ``[MapView]``), so the start falls back to the fitted view.
    Raises ValueError when the text is not a settings file.
    """
    sections = parse_profile(saved_text)
    window = sections.get('MainWindow', [])
    kept: Dict[str, List[str]] = {}
    lines = [line for line in window if _key_of(line) in SAVED_WINDOW_KEYS]
    view = [line for line in window if _key_of(line) in SAVED_VIEW_KEYS]
    if {_key_of(line) for line in view} == set(SAVED_VIEW_KEYS):
        lines.extend(view)
        if sections.get('MapView'):
            kept['MapView'] = list(sections['MapView'])
    if lines:
        kept['MainWindow'] = lines
    return kept


def has_saved_view(saved: Optional[Dict[str, List[str]]]) -> bool:
    """Return True when ``saved`` (from ``carry_over``) holds a whole map view."""
    keys = {_key_of(line) for line in (saved or {}).get('MainWindow', [])}
    return set(SAVED_VIEW_KEYS) <= keys


def build_profile(template: str, boats: Sequence, view_lat: Optional[float] = None,
                  view_lon: Optional[float] = None, view_scale: Optional[float] = None,
                  tile_cache_dir: Optional[str] = None,
                  saved: Optional[Dict[str, List[str]]] = None) -> str:
    """
    Return the settings file CAMP starts from.

    ``template`` holds the fixed part (background maps); this adds the map view and a
    live coverage layer, switched on, for each boat. Everything else CAMP would
    restore (chart lists, vector layers) is left out on purpose, so a fresh profile shows
    exactly these layers and nothing else.

    ``saved`` (``carry_over`` of the file CAMP wrote last time) is the exception: its window
    geometry and state, and its map view when it holds a whole one, are written back exactly as
    CAMP wrote them. Only without a saved view is the view generated from ``view_lat``,
    ``view_lon`` and ``view_scale`` (the first start on a computer).
    """
    saved = saved or {}
    keep_view = has_saved_view(saved)
    if not keep_view and not (view_scale is not None and view_scale > 0.0
                              and math.isfinite(view_scale)):
        raise ValueError('view_scale must be a positive number, got %r' % view_scale)
    sections = parse_profile(template)
    for forbidden in ('MainWindow', 'MapView', 'LiveTileCache'):
        if forbidden in sections:
            raise ValueError('the profile template must not set [%s]: the view is '
                             'generated from the view settings' % forbidden)
    if keep_view:
        sections['MainWindow'] = list(saved['MainWindow'])
        if saved.get('MapView'):
            sections['MapView'] = list(saved['MapView'])
    else:
        center = qt_point_variant(*web_mercator(view_lat, view_lon))
        scale = repr(float(view_scale))
        # MainWindow's deferred restore (mainwindow.cpp) runs after the map view's own
        # and wins; both are set to the same view so neither can disagree.
        sections['MainWindow'] = (list(saved.get('MainWindow', [])) +
                                  ['mapCenter=' + center, 'mapScale=' + scale])
        sections['MapView'] = [r'mapView\center=' + center, r'mapView\scale=' + scale]
    if tile_cache_dir:
        # Keep the live tile cache where the launch can empty it, so tiles from an
        # earlier session are not warm-loaded into this one.
        sections['LiveTileCache'] = ['cache_dir=' + qt_ini_string(tile_cache_dir)]
    items = sections.setdefault('MapItem', [])
    for boat in boats:
        key = live_layer_key(boat.name)
        items.append('%s\\live_enabled=true' % key)
        items.append('%s\\visible=true' % key)
    lines = ['; Generated by marine_simulation (the demo manager) on every start, except the',
             '; window and map view CAMP saved. Edit config/demo_camp_profile.conf, not this.']
    for section, entries in sections.items():
        lines.append('')
        lines.append('[%s]' % section)
        lines.extend(entries)
    return '\n'.join(lines) + '\n'


def view_center(boats: Sequence) -> Tuple[float, float]:
    """Return the mean start position of the boats (latitude, longitude)."""
    if not boats:
        raise ValueError('there are no boats to centre the map on')
    return (sum(b.lat for b in boats) / len(boats), sum(b.lon for b in boats) / len(boats))


def load_view(path: str) -> dict:
    """Read and validate the CAMP view override (``scale``, with ``lat``/``lon``); {} means fit."""
    with open(path) as f:
        data = yaml.safe_load(f)
    view = data.get('camp_view') if isinstance(data, dict) else None
    if not isinstance(view, dict):
        raise ValueError("%s: expected a 'camp_view' mapping" % path)
    unknown = set(view) - {'scale', 'lat', 'lon'}
    if unknown:
        raise ValueError('%s: unknown camp_view key(s) %s' % (path, ', '.join(sorted(unknown))))
    if ('lat' in view) != ('lon' in view):
        raise ValueError("%s: camp_view needs both 'lat' and 'lon' or neither" % path)
    if 'lat' in view and 'scale' not in view:
        raise ValueError("%s: camp_view 'lat' and 'lon' need a 'scale' too (leave all three "
                         'out to fit the view to the target area)' % path)

    def number(key, low, high):
        value = view[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value):
            raise ValueError('%s: camp_view %s must be a finite number, got %r'
                             % (path, key, value))
        if value < low or value > high:
            raise ValueError('%s: camp_view %s = %s is outside [%s, %s]'
                             % (path, key, value, low, high))
        return float(value)

    if 'scale' in view:
        view['scale'] = number('scale', 0.0, 1e9)
        if view['scale'] <= 0.0:
            raise ValueError('%s: camp_view scale must be greater than zero' % path)
    if 'lat' in view:
        # Web Mercator stops being finite at the poles.
        view['lat'] = number('lat', -85.0, 85.0)
        view['lon'] = number('lon', -180.0, 180.0)
    return view


# --- fitting CAMP's starting view to the target area ---------------------------------

# CAMP's map scale (``MainWindow/mapScale``, the QGraphicsView transform's m11) is screen pixels
# per scene unit; a scene unit is one Web Mercator metre (camp_map/map_view/map_view.cpp,
# web_mercator.cpp), and the view is limited to 1/50000 .. 50.
MIN_CAMP_SCALE = 1 / 50000.0
MAX_CAMP_SCALE = 50.0
# The map widget is the window minus CAMP's panel on the left and the title bar, top bar,
# menu and tool bars above it. Overestimated on purpose: a smaller viewport only zooms out a
# little, a larger one cuts the polygon off. The target also gets this much empty margin on
# each side.
PANEL_WIDTH_FRACTION = 0.15
CHROME_HEIGHT_PIXELS = 200
FIT_MARGIN = 0.125
# Used when the monitor CAMP is placed on cannot be read (no layout, no xrandr).
FALLBACK_WINDOW = (1920, 1080)
# The scale when there is nothing to fit to (CAMP started without a target file): roughly
# 2.6 km of harbour across a 3840 pixel wide map.
UNFITTED_SCALE = 1.0
# Below this many map units (about a metre) the target is a point or a line, not an area.
MIN_TARGET_EXTENT = 1.0


def target_bounds(target_file: str, tool: str = None) -> Tuple[float, float, float, float]:
    """
    Return ``(min_lat, min_lon, max_lat, max_lon)`` of the vertices in the target file.

    Asks ``publish_survey_area.py --bounds`` so the file is read by the one parser the
    publisher uses (the file CAMP and the scorer get is the same one). Raises ValueError with
    the reason when the file cannot be used.
    """
    tool = tool or os.path.join(get_package_prefix('marine_simulation'), 'lib',
                                'marine_simulation', TARGET_AREA_EXECUTABLE)
    try:
        result = subprocess.run([tool, '--bounds', target_file], capture_output=True,
                                text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError('cannot run %s: %s' % (tool, error)) from None
    if result.returncode != 0:
        raise ValueError('the target area file cannot be used: %s' % (
            (result.stderr or result.stdout).strip().replace('publish_survey_area: ', '', 1)))
    try:
        lat0, lon0, lat1, lon1 = (float(v) for v in result.stdout.split())
    except ValueError:
        raise ValueError('unexpected answer of %s --bounds: %r' % (tool, result.stdout)) from None
    return lat0, lon0, lat1, lon1


def inverse_web_mercator(x: float, y: float) -> Tuple[float, float]:
    """Return the (latitude, longitude) of CAMP map coordinates (inverse of ``web_mercator``)."""
    return (math.degrees(math.atan(math.sinh(y / _EARTH_RADIUS))),
            math.degrees(x / _EARTH_RADIUS))


def fit_view(bounds: Tuple[float, float, float, float], window: Tuple[int, int],
             margin: float = FIT_MARGIN) -> Tuple[float, float, float]:
    """
    Return ``(lat, lon, scale)`` that shows all of ``bounds`` with ``margin`` on every side.

    ``window`` is the CAMP window in pixels (width, height); the map widget in it is smaller
    by CAMP's side panel and the bars above. The centre is the middle of the box in CAMP's own
    map coordinates. Raises ValueError for a target with no extent (one vertex, a line).
    """
    lat0, lon0, lat1, lon1 = bounds
    x0, y0 = web_mercator(lat0, lon0)
    x1, y1 = web_mercator(lat1, lon1)
    width, height = abs(x1 - x0), abs(y1 - y0)
    if not (width >= MIN_TARGET_EXTENT and height >= MIN_TARGET_EXTENT):
        raise ValueError('the target area has no extent to fit the map view to (%.1f x %.1f '
                         'map units); it needs at least three vertices that are not in a line'
                         % (width, height))
    view_width = window[0] * (1.0 - PANEL_WIDTH_FRACTION)
    view_height = window[1] - CHROME_HEIGHT_PIXELS
    if view_width <= 0 or view_height <= 0:
        raise ValueError('the CAMP window %dx%d is too small to fit a view into' % window)
    scale = min(view_width / (width * (1.0 + 2.0 * margin)),
                view_height / (height * (1.0 + 2.0 * margin)))
    scale = max(MIN_CAMP_SCALE, min(MAX_CAMP_SCALE, scale))
    lat, lon = inverse_web_mercator((x0 + x1) / 2.0, (y0 + y1) / 2.0)
    return lat, lon, scale


_MONITOR_LINE = re.compile(
    r'^\s*\d+:\s+[+*]*(\S+)\s+(\d+)/\d+x(\d+)/\d+\+(-?\d+)\+(-?\d+)\s*(.*)$')


def _camp_layout_entry(entries: Sequence[dict]) -> Optional[dict]:
    """
    Return the layout entry that places CAMP, or None.

    ``place_windows.py`` matches by substring of the window's class and title, so an entry
    whose ``wm_class`` is part of CAMP's executable name matches, as does one that holds it.
    A lone entry (for example one that matches by title only) is taken to be CAMP's.
    """
    for entry in entries:
        wm_class = (entry.get('match') or {}).get('wm_class') or ''
        if wm_class and (wm_class in CAMP_EXECUTABLE or CAMP_EXECUTABLE in wm_class):
            return entry
    return entries[0] if len(entries) == 1 else None


def camp_window_size(layout_config: str, runner=None) -> Tuple[Optional[Tuple[int, int]], str]:
    """
    Return ``((width, height) or None, note)``: the size CAMP's window will have.

    Read from the layout file's CAMP entry: its ``rect``, else (maximised or full screen) the
    monitor it names as ``xrandr --listmonitors`` reports it. None, with the reason in the
    note, when that cannot be found; the caller then uses ``FALLBACK_WINDOW``.
    """
    try:
        with open(layout_config) as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as error:
        return None, 'cannot read the layout file %s: %s' % (layout_config, error)
    entries = data.get('windows') if isinstance(data, dict) else None
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        return None, 'the layout file %s has no list of windows' % layout_config
    entry = _camp_layout_entry(entries)
    if entry is None:
        return None, 'no CAMP window entry in the layout file %s' % layout_config
    rect = entry.get('rect')
    if isinstance(rect, dict) and all(isinstance(rect.get(k), int) for k in ('width', 'height')):
        return (rect['width'], rect['height']), "the layout's CAMP rect"
    try:
        output = (runner or (lambda c: subprocess.run(
            c, capture_output=True, text=True, timeout=20, check=True).stdout))(
                ['xrandr', '--listmonitors'])
    except (OSError, subprocess.SubprocessError) as error:
        return None, 'cannot ask xrandr for the monitors: %s' % error
    for line in output.splitlines():
        match = _MONITOR_LINE.match(line)
        if match and entry.get('monitor') in [match.group(1)] + match.group(6).split():
            return (int(match.group(2)), int(match.group(3))), 'monitor %s' % entry.get('monitor')
    return None, 'monitor %r of the layout is not connected' % entry.get('monitor')


def camp_start_view(boats: Sequence, view: dict, target_file: str, layout_config: str,
                    bounds_tool: str = None, runner=None) -> Tuple[float, float, float, str]:
    """
    Return ``(lat, lon, scale, how)`` for CAMP's starting view.

    ``view`` (``demo_camp_view.yaml``) with a ``scale`` is an explicit override and is used as
    written (centre: its lat/lon, else the middle of the boats). Without one the view is
    fitted to the target area in the window CAMP is placed on.
    """
    if 'scale' in view:
        lat, lon = (view['lat'], view['lon']) if 'lat' in view else view_center(boats)
        return lat, lon, view['scale'], 'the explicit view of the view config'
    if not target_file:
        # CAMP started on its own, with nothing to fit to: the boats, at a fixed scale.
        lat, lon = view_center(boats)
        return (lat, lon, UNFITTED_SCALE,
                'no target area file to fit to; the boats at a fixed scale')
    window, note = camp_window_size(layout_config, runner) if layout_config else (
        None, 'no layout file')
    if window is None:
        window = FALLBACK_WINDOW
        note = 'assuming a %dx%d window (%s)' % (window + (note,))
    lat, lon, scale = fit_view(target_bounds(target_file, bounds_tool), window)
    return lat, lon, scale, 'fitted to %s in a %dx%d window (%s)' % (
        os.path.basename(target_file), window[0], window[1], note)


def state_dir(home: Optional[str] = None) -> str:
    """Return the directory the launch keeps what it generates."""
    return os.path.join(home or os.path.expanduser('~'), *STATE_PARTS)


def settings_root(home: Optional[str] = None) -> str:
    """Return the directory the launch hands CAMP as ``XDG_CONFIG_HOME``."""
    return os.path.join(state_dir(home), SETTINGS_ROOT_NAME)


def reset_state_dir(root: str, name: str, home: Optional[str] = None) -> str:
    """
    Empty and re-create the demo's state directory ``name``; return it.

    Deleting is guarded: the path must be exactly ``<state dir>/<name>`` under the
    home directory, must not be a symlink, and an existing one must carry the
    marker this function leaves in it (an empty directory is also accepted).
    Anything else raises and nothing is removed.
    """
    expected = os.path.abspath(os.path.join(state_dir(home), name))
    if os.path.abspath(root) != expected:
        raise ValueError('refusing to reset %r: the demo directory is %r' % (root, expected))
    if os.path.islink(root):
        raise ValueError('refusing to reset %r: it is a symlink' % root)
    if os.path.exists(root):
        if not os.path.isdir(root):
            raise ValueError('refusing to reset %r: it is not a directory' % root)
        if os.listdir(root) and not os.path.isfile(os.path.join(root, ROOT_MARKER)):
            raise ValueError('refusing to reset %r: it has files in it that this launch '
                             'did not create (no %s marker)' % (root, ROOT_MARKER))
        shutil.rmtree(root)
    os.makedirs(root, mode=0o700)
    with open(os.path.join(root, ROOT_MARKER), 'w') as f:
        f.write('Recreated by the marine_simulation demo manager on every demo start.\n')
    return root


def reset_settings_root(root: str, home: Optional[str] = None) -> str:
    """Empty and re-create the settings directory CAMP gets as ``XDG_CONFIG_HOME``."""
    return reset_state_dir(root, SETTINGS_ROOT_NAME, home)


def cache_dir(home: Optional[str] = None) -> str:
    """Return the directory CAMP keeps its live coverage tile cache in during the demo."""
    return os.path.join(state_dir(home), CACHE_DIR_NAME)


def camp_settings_path(root: str) -> str:
    """Return where CAMP's QSettings keeps its file under the demo's settings root."""
    return os.path.join(root, CAMP_ORGANISATION, CAMP_APPLICATION + '.conf')


def read_saved_settings(root: str) -> Tuple[Dict[str, List[str]], str]:
    """
    Return ``(carry_over of the file CAMP wrote last time, note)``; empty when there is none.

    The note says why nothing was carried over (no file, unreadable, not a settings file) or
    what was. A file that cannot be used never stops the start: the start is then a first one.
    """
    path = camp_settings_path(root)
    try:
        with open(path, encoding='utf-8', errors='surrogateescape') as f:
            text = f.read()
    except FileNotFoundError:
        return {}, 'nothing saved yet'
    except OSError as error:
        return {}, 'cannot read %s: %s' % (path, error)
    try:
        saved = carry_over(text)
    except ValueError as error:
        return {}, 'not using %s: %s' % (path, error)
    if not saved:
        return {}, 'CAMP saved no window or view'
    return saved, 'saved: %s' % ', '.join(
        name for name, present in (
            ('window', any(_key_of(x) in SAVED_WINDOW_KEYS for x in saved.get('MainWindow', []))),
            ('view', has_saved_view(saved))) if present)


def seed_camp_settings(root: str, profile: str, home: Optional[str] = None) -> str:
    """Reset ``root`` and write ``profile`` where CAMP's QSettings will read it."""
    reset_settings_root(root, home)
    path = camp_settings_path(root)
    os.makedirs(os.path.dirname(path))
    with open(path, 'w', encoding='utf-8', errors='surrogateescape') as f:
        f.write(profile)
    return path


# --- one demo at a time -----------------------------------------------------------

_LOCKS: Dict[str, object] = {}
CAMP_EXECUTABLE = 'CCOMAutonomousMissionPlanner'


def acquire_demo_lock(directory: str) -> None:
    """
    Take the lock that keeps two demos from sharing the state directory.

    Held until this process exits. A second launch would otherwise delete the first
    one's CAMP settings from under it and overwrite its scorer parameters.
    """
    os.makedirs(directory, mode=0o700, exist_ok=True)
    path = os.path.join(directory, 'lock')
    handle = open(path, 'w')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise ValueError('another demo is already running on this computer (lock %s); '
                         'close its map window first' % path) from None
    _LOCKS[path] = handle


def release_demo_locks() -> None:
    """Release every lock this process holds (tests; a real launch exits instead)."""
    while _LOCKS:
        _LOCKS.popitem()[1].close()


def running_camp_pids(proc_root: str = '/proc') -> List[int]:
    """Return the process ids of CAMP instances already running on this computer."""
    found = []
    for entry in os.listdir(proc_root):
        if not entry.isdigit():
            continue
        try:
            with open(os.path.join(proc_root, entry, 'cmdline'), 'rb') as f:
                argv0 = f.read().split(b'\0')[0]
        except OSError:
            continue  # the process ended while we looked
        if os.path.basename(argv0.decode(errors='replace')) == CAMP_EXECUTABLE:
            found.append(int(entry))
    return sorted(found)


def refuse_running_camp(proc_root: str = '/proc') -> None:
    """Raise when a CAMP is already running: window placement could pick the wrong one."""
    pids = running_camp_pids(proc_root)
    if pids:
        raise ValueError('CAMP is already running (process %s); close it first so the demo '
                         'places its own CAMP window' % ', '.join(map(str, pids)))


# --- scorer -----------------------------------------------------------------------

# The demo scores coverage on a 2 m lattice, not the example's 1 m. The scorer refuses a target
# area whose bounding box has more than ``max_raster_cells`` lattice cells (1,000,000 in the
# example), and the demo's polygon (1.77 km2, a box of about 1408 x 1774 m) is 2.5 million cells
# at 1 m ("Rejecting SurveyArea ... polygon spans 2.49846e+06 lattice cells") and about 625,000
# at 2 m. CUBE itself keeps mapping at its own cell size (the boats launch's ``cell_size``);
# this only sets how finely the scorer rasterises the target. A test pins that the shipped
# polygon fits.
DEMO_SCORER_CELL_SIZE = 2.0


def scorer_parameters(template: dict, boats: Sequence) -> dict:
    """
    Return the scorer's parameter file content for ``boats``.

    ``template`` is the example ``coverage_assessment.yaml`` of the scorer package;
    the grid topics, source names and the frames of the tide boat come from the
    boats instead of the names written in the example.
    """
    try:
        params = template['/**/coverage_assessment']['ros__parameters']
    except (KeyError, TypeError):
        raise ValueError("the scorer example has no '/**/coverage_assessment: "
                         "ros__parameters' section") from None
    if not boats:
        raise ValueError('the scorer needs at least one boat')
    out = {'/**/coverage_assessment': {'ros__parameters': dict(params)}}
    p = out['/**/coverage_assessment']['ros__parameters']
    first = boats[0]
    p['grid_topics'] = ['/%s/sensors/mbes/grid' % b.name for b in boats]
    p['source_names'] = [b.name for b in boats]
    p['map_frame'] = first.frame('map')
    p['water_surface_frame'] = first.frame('map_tide')
    p['water_surface_boat_frame'] = first.frame('base_link')
    p['cell_size'] = DEMO_SCORER_CELL_SIZE
    return out


def write_scorer_parameters(template_path: str, boats: Sequence, out_dir: str) -> str:
    """Write the generated scorer parameter file into ``out_dir``; return its path."""
    with open(template_path) as f:
        template = yaml.safe_load(f)
    os.makedirs(out_dir, mode=0o700, exist_ok=True)
    path = os.path.join(out_dir, 'coverage_assessment.yaml')
    with open(path, 'w') as f:
        yaml.safe_dump(scorer_parameters(template, boats), f)
    return path


# --- CAMP and window placement ------------------------------------------------------

def camp_node(settings_home: str, project_file: str = '') -> Node:
    """Return CAMP started like ``camp_launch.py`` does, on the demo settings."""
    arguments = [os.path.join(get_package_share_directory('camp'), 'workspace') + '/']
    if project_file:
        arguments.append(project_file)  # main.cpp opens an argument ending in .json
    return Node(package='camp', executable='CCOMAutonomousMissionPlanner', name='camp',
                arguments=arguments, emulate_tty=True,
                additional_env={'XDG_CONFIG_HOME': settings_home})


def camp_actions(boats: Sequence, camp_profile: str, camp_view_config: str,
                 target_file: str = '', layout_config: str = '', fresh: bool = False) -> list:
    """
    Return the actions that start CAMP on the demo's own settings and tile cache.

    Seeds the private ``XDG_CONFIG_HOME`` with the generated profile and empties the demo's
    live tile cache, so nothing of the operator's settings or of an earlier session's coverage
    shows. What CAMP saved of its own window (geometry, state) and map view when it last closed
    is carried over, unless ``fresh``; the view is generated (fitted to the target) only when
    none is saved. Used by the launch manager's ``camp`` group (``demo_camp_launch.py``); the
    last action is the CAMP node.
    """
    require_file(camp_profile, 'camp_profile')
    root = settings_root()
    if fresh:
        saved, why = {}, 'discarded (--camp-fresh)'
    else:
        saved, why = read_saved_settings(root)
    if has_saved_view(saved):
        lat = lon = scale = None
        how = 'the view CAMP saved'
    else:
        view = load_view(camp_view_config)
        lat, lon, scale, how = camp_start_view(boats, view, target_file, layout_config)
    with open(camp_profile) as f:
        profile = build_profile(f.read(), boats, lat, lon, scale, cache_dir(), saved)
    seed_camp_settings(root, profile)
    reset_state_dir(cache_dir(), CACHE_DIR_NAME)
    camp = camp_node(root, target_file)
    view_text = ('CAMP map view: %s' % how if lat is None else
                 'CAMP map view: %.6f, %.6f at scale %.4f, %s' % (lat, lon, scale, how))
    return [LogInfo(msg='CAMP settings: %s' % root),
            LogInfo(msg='CAMP window and view from its last run: %s' % why),
            LogInfo(msg=view_text),
            camp]


def target_area_node(target_file: str = '') -> Node:
    """
    Return the node that publishes the target survey area to the scorer.

    ``target_file`` is a saved CAMP project; empty leaves the publisher on its own default,
    the installed ``config/demo_target_polygon_camp.json``. The publisher is the scorer's
    source of truth for what is to be surveyed, in the root namespace so the topic is
    ``/survey_area``.
    """
    parameters = [{'file': target_file}] if target_file else []
    return Node(package='marine_simulation', executable=TARGET_AREA_EXECUTABLE,
                name=TARGET_AREA_NODE_NAME, emulate_tty=True, output='screen',
                parameters=parameters)


def placement_process(layout_config: str) -> ExecuteProcess:
    """Return the process that moves the windows (``scripts/place_windows.py``)."""
    script = os.path.join(get_package_prefix('marine_simulation'), 'lib',
                          'marine_simulation', 'place_windows.py')
    return ExecuteProcess(cmd=[script, '--layout', layout_config], output='screen',
                          name='place_windows')


def placement_exit(event, context):
    """Return a conspicuous message when the window placement did not succeed."""
    if event.returncode == 0:
        return []
    return [LogInfo(msg='*** THE WINDOWS ARE NOT IN PLACE (place_windows exited with %s; see '
                        'above). Close the map window and start the demo again. ***'
                        % event.returncode)]


def placement_actions(layout_config: str) -> list:
    """Return the actions that run the window placement once and announce a failure of it."""
    placement = placement_process(layout_config)
    return [placement, RegisterEventHandler(
        OnProcessExit(target_action=placement, on_exit=placement_exit))]


def declared_launch_arguments(launch_file: str = None) -> List[str]:
    """
    Return the names of the launch arguments ``launch_file`` declares (the boats launch).

    Read from the launch description itself (what ``ros2 launch`` shows with ``-s``), so the
    list cannot drift from the launch file.
    """
    launch_file = launch_file or os.path.join(
        get_package_share_directory('marine_simulation'), 'launch', 'demo_boats_launch.py')
    description = PythonLaunchDescriptionSource(launch_file).get_launch_description(
        LaunchContext())
    return [e.name for e in description.entities if isinstance(e, DeclareLaunchArgument)]


_LAUNCH_ARGUMENT = re.compile(r'([A-Za-z_][A-Za-z0-9_]*):=(.*)', re.DOTALL)


def parse_launch_arguments(items: Sequence[str], declared: Sequence[str],
                           owned: Sequence[str]) -> Dict[str, str]:
    """
    Return ``{name: value}`` for extra ``name:=value`` arguments meant for the boats launch.

    A name the launch does not declare is refused (a typo would otherwise vanish silently),
    and so is one the manager sets itself from its own options (``owned``): the second
    value would fight the first. A name given twice keeps the last value, as ``ros2 launch``
    does.
    """
    result: Dict[str, str] = {}
    for item in items:
        match = _LAUNCH_ARGUMENT.fullmatch(item)
        if match is None:
            raise ValueError('%r is not a launch argument; the form is name:=value' % item)
        name, value = match.groups()
        if name in owned:
            raise ValueError("%s:= is set by the demo's own options, not as a launch "
                             'argument (%s are)' % (name, ', '.join(sorted(owned))))
        if name not in declared:
            known = sorted(set(declared) - set(owned))
            raise ValueError('%s:= is not an argument of the boats launch; it has %s'
                             % (name, ', '.join(known)))
        result[name] = value
    return result


def require_file(path: str, what: str) -> None:
    """Raise unless ``path`` is a file."""
    if not os.path.isfile(path):
        raise ValueError('%s %r is not a file' % (what, path))
