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
Launch the whole demo display with one command.

Brings up the boats (``demo_boats_launch.py``), the coverage scorer
(``coverage_assessment``), CAMP on a known settings profile, the target-area
publisher (once issue #93 has landed) and a step that puts the windows where the
per-machine layout file says. See ``marine_simulation/README.md``, "Whole demo
display".

As in ``demo_boats_launch.py``, everything that can be checked without a launch
context is a plain module-level function so it can be unit tested.

The boat names come from the roster only. The scorer parameters and CAMP's live
coverage layers are generated from it at launch, so no boat name is copied into a
second file.
"""

import fcntl
import importlib.util
import math
import os
import shutil
import struct
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ament_index_python.packages import get_package_prefix
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import EmitEvent
from launch.actions import ExecuteProcess
from launch.actions import IncludeLaunchDescription
from launch.actions import LogInfo
from launch.actions import OpaqueFunction
from launch.actions import RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch.substitutions import PathJoinSubstitution
from launch.substitutions import TextSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
import yaml


def _load_boats_launch():
    """Load the sibling ``demo_boats_launch.py`` (a launch file is not a package)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'demo_boats_launch.py')
    spec = importlib.util.spec_from_file_location('demo_boats_launch', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


boats_launch = _load_boats_launch()

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

# #93 ships the target-area publisher as a script of this package.
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
    (``test_demo_launch.py`` pins samples; 5000 random points matched when this was
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


def build_profile(template: str, boats: Sequence, view_lat: float, view_lon: float,
                  view_scale: float, tile_cache_dir: Optional[str] = None) -> str:
    """
    Return the settings file CAMP starts from.

    ``template`` holds the fixed part (background maps); this adds the map view and a
    live coverage layer, switched on, for each boat. Everything else CAMP would
    restore (chart lists, vector layers, window geometry) is left out on purpose, so
    a fresh profile shows exactly these layers and nothing else.
    """
    if not view_scale > 0.0 or not math.isfinite(view_scale):
        raise ValueError('view_scale must be a positive number, got %r' % view_scale)
    sections = parse_profile(template)
    for forbidden in ('MainWindow', 'MapView', 'LiveTileCache'):
        if forbidden in sections:
            raise ValueError('the profile template must not set [%s]: the view is '
                             'generated from the view settings' % forbidden)
    center = qt_point_variant(*web_mercator(view_lat, view_lon))
    scale = repr(float(view_scale))
    # MainWindow's deferred restore (mainwindow.cpp) runs after the map view's own
    # and wins; both are set to the same view so neither can disagree.
    sections['MainWindow'] = ['mapCenter=' + center, 'mapScale=' + scale]
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
    lines = ['; Generated by marine_simulation demo_launch.py on every start. Edit',
             '; config/demo_camp_profile.conf, not this file.']
    for section, entries in sections.items():
        lines.append('')
        lines.append('[%s]' % section)
        lines.extend(entries)
    return '\n'.join(lines) + '\n'


def view_center(boats: Sequence) -> Tuple[float, float]:
    """Return the mean start position of the boats (latitude, longitude)."""
    return (sum(b.lat for b in boats) / len(boats), sum(b.lon for b in boats) / len(boats))


def load_view(path: str) -> dict:
    """Read and validate the CAMP view settings (``scale``, and ``lat``/``lon`` to override)."""
    with open(path) as f:
        data = yaml.safe_load(f)
    view = data.get('camp_view') if isinstance(data, dict) else None
    if not isinstance(view, dict):
        raise ValueError("%s: expected a 'camp_view' mapping" % path)
    unknown = set(view) - {'scale', 'lat', 'lon'}
    if unknown:
        raise ValueError('%s: unknown camp_view key(s) %s' % (path, ', '.join(sorted(unknown))))
    if 'scale' not in view:
        raise ValueError("%s: camp_view needs 'scale'" % path)
    if ('lat' in view) != ('lon' in view):
        raise ValueError("%s: camp_view needs both 'lat' and 'lon' or neither" % path)

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

    view['scale'] = number('scale', 0.0, 1e9)
    if view['scale'] <= 0.0:
        raise ValueError('%s: camp_view scale must be greater than zero' % path)
    if 'lat' in view:
        # Web Mercator stops being finite at the poles.
        view['lat'] = number('lat', -85.0, 85.0)
        view['lon'] = number('lon', -180.0, 180.0)
    return view


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
        f.write('Recreated by marine_simulation demo_launch.py on every demo start.\n')
    return root


def reset_settings_root(root: str, home: Optional[str] = None) -> str:
    """Empty and re-create the settings directory CAMP gets as ``XDG_CONFIG_HOME``."""
    return reset_state_dir(root, SETTINGS_ROOT_NAME, home)


def cache_dir(home: Optional[str] = None) -> str:
    """Return the directory CAMP keeps its live coverage tile cache in during the demo."""
    return os.path.join(state_dir(home), CACHE_DIR_NAME)


def seed_camp_settings(root: str, profile: str, home: Optional[str] = None) -> str:
    """Reset ``root`` and write ``profile`` where CAMP's QSettings will read it."""
    reset_settings_root(root, home)
    directory = os.path.join(root, CAMP_ORGANISATION)
    os.makedirs(directory)
    path = os.path.join(directory, CAMP_APPLICATION + '.conf')
    with open(path, 'w') as f:
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
    os.makedirs(directory, exist_ok=True)
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
    return out


def write_scorer_parameters(template_path: str, boats: Sequence, out_dir: str) -> str:
    """Write the generated scorer parameter file into ``out_dir``; return its path."""
    with open(template_path) as f:
        template = yaml.safe_load(f)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, 'coverage_assessment.yaml')
    with open(path, 'w') as f:
        yaml.safe_dump(scorer_parameters(template, boats), f)
    return path


# --- target area (issue #93) --------------------------------------------------------

def target_area_actions(enabled: bool, target_file: str,
                        script_installed: Callable[[], bool]) -> list:
    """
    Return the actions for the target-area publisher (none when not enabled).

    The publisher is issue #93's ``publish_survey_area.py``. Until it is installed
    with this package, asking for it is refused with the reason instead of failing
    at runtime with a missing executable.
    """
    if not enabled:
        return []
    if not target_file:
        raise ValueError('enable_target_area needs target_area_file:=<saved CAMP .json>')
    if not os.path.isfile(target_file):
        raise ValueError('target_area_file %r is not a file' % target_file)
    if not script_installed():
        raise ValueError('enable_target_area: %s is not installed with marine_simulation '
                         '(it comes with issue #93); run with enable_target_area:=false '
                         'until that has landed' % TARGET_AREA_EXECUTABLE)
    return [Node(package='marine_simulation', executable=TARGET_AREA_EXECUTABLE,
                 name=TARGET_AREA_NODE_NAME, emulate_tty=True, output='screen',
                 parameters=[{'file': target_file}])]


def target_script_installed() -> bool:
    """Return True when the installed package carries the target-area publisher."""
    path = os.path.join(get_package_prefix('marine_simulation'), 'lib',
                        'marine_simulation', TARGET_AREA_EXECUTABLE)
    return os.path.isfile(path)


# --- CAMP and window placement ------------------------------------------------------

def camp_node(settings_home: str, project_file: str = '') -> Node:
    """Return CAMP started like ``camp_launch.py`` does, on the demo settings."""
    arguments = [os.path.join(get_package_share_directory('camp'), 'workspace') + '/']
    if project_file:
        arguments.append(project_file)  # main.cpp opens an argument ending in .json
    return Node(package='camp', executable='CCOMAutonomousMissionPlanner', name='camp',
                arguments=arguments, emulate_tty=True,
                additional_env={'XDG_CONFIG_HOME': settings_home})


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


def camp_exit_handlers(camp: Node) -> list:
    """Return the handler that shuts the whole launch down when the CAMP window closes."""
    return [RegisterEventHandler(OnProcessExit(target_action=camp, on_exit=[
        LogInfo(msg='CAMP was closed: stopping the whole demo.'),
        EmitEvent(event=Shutdown(reason='the CAMP window was closed'))]))]


def load_place_windows():
    """Load ``place_windows.py`` from the source tree or the installed package."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [os.path.join(here, '..', 'scripts', 'place_windows.py'),
                  os.path.join(get_package_prefix('marine_simulation'), 'lib',
                               'marine_simulation', 'place_windows.py')]
    for path in candidates:
        if os.path.isfile(path):
            spec = importlib.util.spec_from_file_location('place_windows', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise ValueError('place_windows.py is not installed with marine_simulation')


def check_placement_prerequisites(layout_path: str, windows=None,
                                  environ=os.environ) -> None:
    """
    Refuse window placement on a session, host or layout that cannot do it.

    Run before anything starts, so a missing tool, a Wayland session, a malformed
    layout or an unplugged monitor stops the launch with the reason instead of
    leaving the windows unplaced.
    """
    windows = windows or load_place_windows()
    try:
        windows.check_layout(layout_path, environ)
    except windows.LayoutError as error:
        raise ValueError('layout_config %s: %s' % (layout_path, error)) from None


def require_file(path: str, what: str) -> None:
    """Raise unless ``path`` is a file."""
    if not os.path.isfile(path):
        raise ValueError('%s %r is not a file' % (what, path))


# --- the launch ---------------------------------------------------------------------

def launch_setup(context, *args, **kwargs):
    """Resolve the arguments, run the fail-fast checks and build the display."""

    def arg(name: str) -> str:
        return LaunchConfiguration(name).perform(context)

    def flag(name: str) -> bool:
        return boats_launch.parse_bool(arg(name), name)

    enable = {name: flag('enable_' + name)
              for name in ('boats', 'camp', 'scorer', 'target_area', 'window_layout')}

    roster = boats_launch.load_roster(arg('roster_file'))
    boats = boats_launch.select_boats(roster, arg('boats'))
    actions: List = []
    target_file = arg('target_area_file')
    if target_file:
        # CAMP opens it whether or not the publisher runs, so check it either way.
        target_file = os.path.abspath(os.path.expanduser(target_file))
        require_file(target_file, 'target_area_file')
    if enable['camp'] or enable['scorer']:
        acquire_demo_lock(state_dir())
    if enable['camp']:
        refuse_running_camp()

    if enable['window_layout']:
        require_file(arg('layout_config'), 'layout_config')
        check_placement_prerequisites(arg('layout_config'))
    if enable['boats']:
        names = ['boats', 'roster_file', 'joystick_config', 'enable_joysticks']
        actions.append(IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(
                os.path.dirname(os.path.abspath(__file__)), 'demo_boats_launch.py')),
            launch_arguments={n: arg(n) for n in names}.items()))

    runtime = os.path.join(state_dir(), 'run')
    if enable['scorer']:
        template = os.path.join(get_package_share_directory('coverage_assessment'),
                                'config', 'coverage_assessment.yaml')
        params = write_scorer_parameters(template, boats, runtime)
        actions.append(IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('coverage_assessment'), 'launch',
            'coverage_assessment_launch.py')), launch_arguments={'params_file': params}.items()))

    actions.extend(target_area_actions(
        enable['target_area'], target_file, target_script_installed))

    if enable['camp']:
        require_file(arg('camp_profile'), 'camp_profile')
        view = load_view(arg('camp_view_config'))
        lat, lon = (view['lat'], view['lon']) if 'lat' in view else view_center(boats)
        with open(arg('camp_profile')) as f:
            profile = build_profile(f.read(), boats, lat, lon, view['scale'], cache_dir())
        root = settings_root()
        seed_camp_settings(root, profile)
        reset_state_dir(cache_dir(), CACHE_DIR_NAME)
        camp = camp_node(root, target_file)
        actions.extend([LogInfo(msg='CAMP settings: %s' % root), camp])
        actions.extend(camp_exit_handlers(camp))

    if enable['window_layout']:
        placement = placement_process(arg('layout_config'))
        actions.extend([placement, RegisterEventHandler(
            OnProcessExit(target_action=placement, on_exit=placement_exit))])
    return actions


def generate_launch_description():
    def declare(name, default, description):
        return DeclareLaunchArgument(
            name, default_value=default, description=description)

    share = FindPackageShare('marine_simulation')
    on, off = TextSubstitution(text='true'), TextSubstitution(text='false')
    return LaunchDescription([
        declare('boats', TextSubstitution(text=''),
                'Comma separated boat names to run (default: every boat in the roster).'),
        declare('roster_file',
                PathJoinSubstitution([share, 'config', 'demo_roster.yaml']),
                'Boat roster: the only place boat names live.'),
        declare('joystick_config',
                PathJoinSubstitution([share, 'config', 'demo_joysticks.yaml']),
                'Joystick bindings for this host (copy and edit; see the README).'),
        declare('enable_joysticks', on,
                'Start a joy_linux driver per boat (see demo_boats_launch.py).'),
        declare('layout_config',
                PathJoinSubstitution([share, 'config', 'demo_layout.yaml']),
                'Window layout for this host (copy and edit; see the README).'),
        declare('camp_profile',
                PathJoinSubstitution([share, 'config', 'demo_camp_profile.conf']),
                'Fixed part of the CAMP settings every start begins from.'),
        declare('camp_view_config',
                PathJoinSubstitution([share, 'config', 'demo_camp_view.yaml']),
                'Where and how far in CAMP starts (scale; optional lat and lon).'),
        declare('target_area_file', TextSubstitution(text=''),
                'Saved CAMP .json holding the target survey area: CAMP opens it to show '
                'the outline and the target-area publisher sends it to the scorer.'),
        declare('enable_boats', on, 'Start the demo boats.'),
        declare('enable_camp', on, 'Start CAMP on the demo settings.'),
        declare('enable_scorer', on, 'Start and activate the coverage scorer.'),
        declare('enable_target_area', off,
                'Start the target-area publisher (issue #93; refused until it is installed).'),
        declare('enable_window_layout', on,
                'Move the windows to the places layout_config names (X11, needs wmctrl).'),
        OpaqueFunction(function=launch_setup),
    ])
