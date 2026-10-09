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
Launch the demo boats: several simulated boats at once, no navigation stack.

The boats come from ``config/demo_roster.yaml`` (the only place their names
appear). Each boat gets its own ROS namespace and TF frame prefix, its own
helm, sonar and CUBE chain, and optionally a joystick. One shared ``asv_sim``
node simulates all of them. See ``marine_simulation/README.md``.

The checks that stop a mis-wired demo from starting are plain functions at
module level (``load_roster``, ``select_boats``, ``assign_joysticks``,
``refuse_enable_nav``) so they can be unit tested without a launch context.
"""

import dataclasses
import os
import re
from typing import Callable, Dict, List, Sequence, Tuple

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import GroupAction
from launch.actions import IncludeLaunchDescription
from launch.actions import OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command
from launch.substitutions import LaunchConfiguration
from launch.substitutions import PathJoinSubstitution
from launch.substitutions import TextSubstitution
from launch.utilities import perform_substitutions
from launch_ros.actions import Node
from launch_ros.actions import PushROSNamespace
from launch_ros.actions import SetParameter
from launch_ros.actions import SetParametersFromFile
from launch_ros.actions import SetRemap
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare
from launch_ros.utilities.evaluate_parameters import evaluate_parameter_dict
import yaml

# Names that are already in use as top-level namespaces or TF frames.
RESERVED_NAMES = frozenset({
    'asv_sim', 'earth', 'marine', 'parameter_events', 'rosout', 'tf', 'tf_static',
})
_NAME_PATTERN = re.compile(r'^[a-z][a-z0-9_]*$')

# Frames the boat's nodes share, as suffixes under the boat's prefix.
FRAME_SUFFIXES = (
    'base_link', 'base_link_north_up', 'odom', 'map', 'map_tide',
    'chart_datum', 'chart_datum_mhhw', 'motion_sensor', 'mbes',
)


class ScopedSetParameter(SetParameter):
    """
    SetParameter that stays inside its GroupAction.

    launch_ros appends to the existing ``global_params`` list in place, so once an
    outer scope has one, a nested group's parameters survive the end of that group
    and land on the next boat's nodes. This copies the list instead, which the
    group's scope then really does discard.
    """

    def execute(self, context):
        items = evaluate_parameter_dict(context, {self.name: self.value})
        existing = context.launch_configurations.get('global_params', [])
        context.launch_configurations['global_params'] = [*existing, *items.items()]


class ScopedSetRemap(SetRemap):
    """SetRemap that stays inside its GroupAction (same in-place list problem)."""

    def execute(self, context):
        src = perform_substitutions(context, self.src)
        dst = perform_substitutions(context, self.dst)
        existing = context.launch_configurations.get('ros_remaps', [])
        context.launch_configurations['ros_remaps'] = [*existing, (src, dst)]


@dataclasses.dataclass(frozen=True)
class Boat:
    """One boat of the roster."""

    name: str
    pad: str
    color: Tuple[float, float, float]
    lat: float
    lon: float
    heading: float
    index: int

    def frame(self, suffix: str) -> str:
        """Return the boat's TF frame name for ``suffix``."""
        return '%s/%s' % (self.name, suffix)


def _number(value, what: str, low: float = None, high: float = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('%s must be a number, got %r' % (what, value))
    value = float(value)
    if (low is not None and value < low) or (high is not None and value > high):
        raise ValueError('%s = %s is outside [%s, %s]' % (what, value, low, high))
    return value


def load_roster(path: str) -> List[Boat]:
    """Read and validate the boat roster; return the boats in file order."""
    with open(path) as f:
        data = yaml.safe_load(f)
    entries = data.get('boats') if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ValueError("%s: expected a non-empty 'boats' list" % path)

    boats = []
    seen = set()
    for index, entry in enumerate(entries):
        where = '%s: boats[%d]' % (path, index)
        if not isinstance(entry, dict) or not isinstance(entry.get('name'), str):
            raise ValueError("%s: each boat needs a string 'name'" % where)
        name = entry['name']
        where = '%s: boat %r' % (path, name)
        if not _NAME_PATTERN.match(name):
            raise ValueError('%s: the name must match %s (it becomes a ROS namespace '
                             'and a TF frame prefix)' % (where, _NAME_PATTERN.pattern))
        if name in RESERVED_NAMES:
            raise ValueError('%s: %r is reserved' % (where, name))
        if name in seen:
            raise ValueError('%s: duplicate boat name' % where)
        seen.add(name)

        color = entry.get('color')
        if not isinstance(color, dict) or set(color) != {'red', 'green', 'blue'}:
            raise ValueError("%s: 'color' needs exactly red, green and blue" % where)
        start = entry.get('start')
        if not isinstance(start, dict) or set(start) != {'lat', 'lon', 'heading'}:
            raise ValueError("%s: 'start' needs exactly lat, lon and heading" % where)
        boats.append(Boat(
            name=name,
            pad=str(entry.get('pad', '')),
            color=tuple(_number(color[k], '%s color.%s' % (where, k), 0.0, 1.0)
                        for k in ('red', 'green', 'blue')),
            lat=_number(start['lat'], where + ' start.lat', -90.0, 90.0),
            lon=_number(start['lon'], where + ' start.lon', -180.0, 180.0),
            heading=_number(start['heading'], where + ' start.heading', 0.0, 360.0),
            index=index,
        ))
    return boats


def select_boats(roster: Sequence[Boat], requested: str) -> List[Boat]:
    """
    Return the roster boats named in the comma separated ``requested``.

    An empty string selects every boat. Boats keep their roster position (and
    so their joystick) whatever subset is chosen.
    """
    names = [n.strip() for n in requested.split(',') if n.strip()]
    if not names:
        return list(roster)
    known = {b.name: b for b in roster}
    unknown = [n for n in names if n not in known]
    if unknown:
        raise ValueError('unknown boat(s) %s; the roster has %s'
                         % (', '.join(repr(n) for n in unknown), ', '.join(known)))
    if len(set(names)) != len(names):
        raise ValueError('boat listed more than once in %r' % requested)
    return [known[n] for n in names]


def load_joystick_config(path: str) -> dict:
    """Read the joystick bindings file."""
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or not isinstance(data.get('devices'), list):
        raise ValueError("%s: expected a 'devices' list" % path)
    return data


def assign_joysticks(
        roster: Sequence[Boat], boats: Sequence[Boat], config: dict,
        exists: Callable[[str], bool] = os.path.exists) -> Dict[str, str]:
    """
    Map each selected boat to its joystick device path, or raise.

    ``config['devices']`` pairs with the roster by position. Refusing to start
    is the point: two boats on one pad, or a boat on the wrong pad, only shows
    up as the wrong boat moving.
    """
    devices = config.get('devices')
    if not all(isinstance(d, str) and d for d in devices):
        raise ValueError('every joystick device must be a non-empty path string')
    if len(devices) != len(roster):
        raise ValueError('the roster has %d boats but the joystick config lists %d devices; '
                         'they pair by position' % (len(roster), len(devices)))
    duplicates = sorted({d for d in devices if devices.count(d) > 1})
    if duplicates:
        raise ValueError('the same joystick device is listed more than once: %s'
                         % ', '.join(duplicates))
    assignment = {b.name: devices[b.index] for b in boats}
    missing = ['%s (%s pad): %s' % (b.name, b.pad or 'no pad label', assignment[b.name])
               for b in boats if not exists(assignment[b.name])]
    if missing:
        raise ValueError(
            'joystick device(s) not found; plug the pads into the labelled ports, check '
            "'ls -l /dev/input/by-path/ | grep -- -joystick$', or launch with "
            'enable_joysticks:=false:\n  ' + '\n  '.join(missing))
    return assignment


def refuse_enable_nav(enable_nav: str) -> None:
    """Raise if the navigation stack was requested; it is not wired yet."""
    if enable_nav.strip().lower() in ('true', '1', 'yes', 'on'):
        raise RuntimeError(
            'enable_nav:=true is not wired yet: the navigation stack (nav2, mission_manager, '
            's57_grids) cannot run per boat in this launch. Leave enable_nav at false.')


def asv_sim_parameters(
        boats: Sequence[Boat], tide_speed_factor: float, current_speed: float) -> dict:
    """Return the ``asv_sim`` parameters for the selected boats."""
    params = {
        'platforms': [b.name for b in boats],
        'environment.tide.speed_factor': tide_speed_factor,
        'environment.current.speed': current_speed,
    }
    for b in boats:
        prefix = 'platforms.%s.' % b.name
        params[prefix + 'model'] = 'demo'
        params[prefix + 'start_lat'] = b.lat
        params[prefix + 'start_lon'] = b.lon
        params[prefix + 'start_heading'] = b.heading
        params[prefix + 'mru_frame'] = b.frame('motion_sensor')
    return params


def asv_sim_remappings(boats: Sequence[Boat]) -> List[Tuple[str, str]]:
    """Return the ``asv_sim`` topic remappings, five per boat."""
    remaps = []
    for b in boats:
        n = b.name
        remaps.extend([
            (n + '/position', n + '/sensors/nav/position'),
            (n + '/orientation', n + '/sensors/nav/orientation'),
            (n + '/velocity', n + '/sensors/nav/velocity'),
            (n + '/throttle', n + '/control/throttle'),
            (n + '/rudder', n + '/control/rudder'),
        ])
    return remaps


def _include(package: str, *path: str, launch_arguments: dict = None):
    return IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([FindPackageShare(package), *path])),
        launch_arguments=(launch_arguments or {}).items())


def _frame_parameters(boat: Boat, **names: str) -> List[ScopedSetParameter]:
    """Return SetParameters for ``param=suffix`` pairs, e.g. map_frame='map'."""
    return [ScopedSetParameter(name=param, value=boat.frame(suffix))
            for param, suffix in names.items()]


def boat_actions(
        boat: Boat, joystick: str, settings: dict) -> GroupAction:
    """
    Build the namespaced group for one boat.

    Every node comes from the same per-node launch file the real boats use
    (they configure and activate the lifecycle nodes through ``ros_namespace``),
    wrapped in a namespace push and the remaps the originals apply.
    """
    n = boat.name
    odom = '/%s/odom' % n

    actions = [
        PushROSNamespace(n),

        # Static and joint TF from the Ben URDF with every link prefixed by the boat.
        Node(
            package='robot_state_publisher', executable='robot_state_publisher',
            name='robot_state_publisher', emulate_tty=True,
            parameters=[{'robot_description': ParameterValue(
                Command(['xacro ', PathJoinSubstitution([
                    FindPackageShare('ben_description'), 'urdf', 'ben_mesh.xacro']),
                    ' namespace:=', n]), value_type=str)}]),
        Node(
            package='joint_state_publisher', executable='joint_state_publisher',
            name='joint_state_publisher', emulate_tty=True),

        # earth -> <n>/map -> <n>/odom -> <n>/base_link from the simulated nav source.
        Node(
            package='mru_transform', executable='mru_transform_node',
            name='mru_transform', emulate_tty=True,
            parameters=[{
                'base_frame': boat.frame('base_link'),
                'map_frame': boat.frame('map'),
                'odom_frame': boat.frame('odom'),
            }]),
        GroupAction([
            *_frame_parameters(boat, sea_surface_frame='map_tide',
                               chart_datum_frame='chart_datum',
                               mhhw_frame='chart_datum_mhhw'),
            _include('mru_transform', 'launch', 'sea_surface_estimator_launch.py'),
        ]),
        GroupAction([
            *_frame_parameters(boat, map_frame='map', chart_datum_frame='chart_datum',
                               mhhw_frame='chart_datum_mhhw', base_frame='base_link'),
            _include('mru_transform', 'launch', 'chart_datum_launch.py'),
        ]),

        # Helm: joystick -> helm_manager -> asv_helm -> throttle/rudder -> asv_sim.
        GroupAction([
            ScopedSetRemap(src='helm', dst='marine/control/helm'),
            ScopedSetRemap(src='cmd_vel', dst='marine/control/cmd_vel'),
            ScopedSetRemap(src='throttle', dst='control/throttle'),
            ScopedSetRemap(src='rudder', dst='control/rudder'),
            ScopedSetRemap(src='have_commands', dst='/asv_sim/%s/have_commands' % n),
            _include('asv_helm', 'launch', 'asv_helm_launch.py'),
        ]),
        GroupAction([
            ScopedSetRemap(src='out/helm', dst='marine/control/helm'),
            ScopedSetRemap(src='out/cmd_vel', dst='marine/control/cmd_vel'),
            ScopedSetRemap(src='heartbeat', dst='marine/heartbeat'),
            ScopedSetRemap(src='status/helm', dst='marine/status/helm'),
            _include('helm_manager', 'launch', 'helm_manager_launch.py'),
        ]),

        # What CAMP shows: one platform per boat, in the colour of its pad.
        GroupAction([
            ScopedSetParameter(name='color.red', value=boat.color[0]),
            ScopedSetParameter(name='color.green', value=boat.color[1]),
            ScopedSetParameter(name='color.blue', value=boat.color[2]),
            _include('marine_autonomy', 'launch', 'platform_sender_launch.py',
                     launch_arguments={'name': n}),
        ]),

        # Simulated multibeam.
        GroupAction([
            ScopedSetParameter(name='sonar_frame_id', value=boat.frame('mbes')),
            ScopedSetParameter(name='ping_interval', value=settings['ping_interval']),
            ScopedSetParameter(name='beam_count', value=settings['beam_count']),
            ScopedSetParameter(name='grid_file', value=settings['mbes_grid_file']),
            ScopedSetRemap(src='detections', dst='/%s/sensors/mbes/detections' % n),
            ScopedSetRemap(src='odom', dst=odom),
            ScopedSetRemap(src='soundings', dst='/%s/sensors/mbes/original_soundings' % n),
            ScopedSetRemap(src='tide_level', dst='/asv_sim/environment/tide_level'),
            _include('mbes_sim', 'launch', 'mbes_sim_launch.py'),
        ]),

        # Detections -> point cloud -> CUBE, in <n>/sensors/mbes.
        GroupAction([
            PushROSNamespace('sensors/mbes'),
            GroupAction([
                *_frame_parameters(boat, base_link_frame='base_link',
                                   level_frame='base_link_north_up',
                                   tide_frame='map_tide'),
                ScopedSetRemap(src='odom', dst=odom),
                _include('cube_bathymetry', 'launch', 'detections_to_pointcloud_launch.py'),
            ]),
            GroupAction([
                *_frame_parameters(boat, map_frame='map', base_link_frame='base_link'),
                ScopedSetParameter(name='cell_size', value=settings['cell_size']),
                _include('cube_bathymetry', 'launch', 'cube_bathymetry_launch.py'),
            ]),
        ]),
    ]

    if joystick is not None:
        actions.append(Node(
            package='joy_linux', executable='joy_linux_node', name='joy_node',
            emulate_tty=True,
            parameters=[{
                'dev': joystick,
                'dev_ff': '',
                'deadzone': settings['deadzone'],
                'autorepeat_rate': settings['autorepeat_rate'],
            }]))

    # joy_to_helm runs with or without a joystick driver: the self-test publishes
    # fake sensor_msgs/Joy on <n>/joy.
    actions.append(GroupAction([
        ScopedSetRemap(src='helm', dst='piloting_mode/manual/helm'),
        _include('joy_to_helm', 'launch', 'joy_to_helm_launch.py'),
    ]))
    return GroupAction(actions)


def launch_setup(context, *args, **kwargs):
    """Resolve the arguments, run the fail-fast checks and build the boats."""

    def arg(name: str) -> str:
        return LaunchConfiguration(name).perform(context)

    refuse_enable_nav(arg('enable_nav'))

    roster = load_roster(arg('roster_file'))
    boats = select_boats(roster, arg('boats'))

    joysticks = {}
    settings = {
        'ping_interval': float(arg('ping_interval')),
        'beam_count': int(arg('beam_count')),
        'cell_size': float(arg('cell_size')),
        'mbes_grid_file': arg('mbes_grid_file'),
        'deadzone': 0.1,
        'autorepeat_rate': 10.0,
    }
    if arg('enable_joysticks').strip().lower() in ('true', '1', 'yes', 'on'):
        config = load_joystick_config(arg('joystick_config'))
        joysticks = assign_joysticks(roster, boats, config)
        settings['deadzone'] = float(config.get('deadzone', settings['deadzone']))
        settings['autorepeat_rate'] = float(
            config.get('autorepeat_rate', settings['autorepeat_rate']))

    actions = [
        SetParametersFromFile(PathJoinSubstitution([
            FindPackageShare('marine_simulation'), 'config', 'demo_params.yaml'])),
        Node(
            package='asv_sim', executable='asv_sim', name='asv_sim', emulate_tty=True,
            parameters=[
                PathJoinSubstitution([FindPackageShare('asv_sim'), 'config', 'demo.yaml']),
                asv_sim_parameters(boats, float(arg('tide_speed_factor')),
                                   float(arg('current_speed'))),
            ],
            remappings=asv_sim_remappings(boats)),
    ]
    actions.extend(boat_actions(b, joysticks.get(b.name), settings) for b in boats)
    return actions


def generate_launch_description():
    def declare(name, default, description):
        return DeclareLaunchArgument(
            name, default_value=default, description=description)

    share = FindPackageShare('marine_simulation')
    return LaunchDescription([
        declare('boats', TextSubstitution(text=''),
                'Comma separated boat names to run (default: every boat in the roster).'),
        declare('roster_file',
                PathJoinSubstitution([share, 'config', 'demo_roster.yaml']),
                'Boat roster: names, platform colours and start poses.'),
        declare('joystick_config',
                PathJoinSubstitution([share, 'config', 'demo_joysticks.yaml']),
                'Joystick bindings (per host: by-path device links, ordered like the '
                'roster).'),
        declare('enable_joysticks', TextSubstitution(text='true'),
                'Start a joy_linux driver per boat. joy_to_helm always runs, so '
                'sensor_msgs/Joy published on <boat>/joy drives the boat either way.'),
        declare('enable_nav', TextSubstitution(text='false'),
                'Reserved for the navigation stack. Not wired yet: true is refused.'),
        declare('tide_speed_factor', TextSubstitution(text='10'),
                'Tide speed multiplier (10 = ~75 min cycle, 3600 = ~12 sec cycle, '
                '1 = real-time).'),
        declare('current_speed', TextSubstitution(text='0.0'),
                'Water current in m/s. asv_sim itself defaults to 1.0 m/s toward 090, '
                'which drifts every boat; the demo defaults to none.'),
        declare('mbes_grid_file',
                PathJoinSubstitution([FindPackageShare('mbes_sim'), 'data',
                                      'US5NH02M.tiff']),
                'Ground-truth bathymetry GeoTIFF sampled by the simulated multibeams.'),
        declare('cell_size', TextSubstitution(text='1.0'),
                'CUBE grid cell size in metres.'),
        declare('ping_interval', TextSubstitution(text='0.2'),
                'Seconds between simulated multibeam pings.'),
        declare('beam_count', TextSubstitution(text='120'),
                'Beams per simulated multibeam ping.'),
        OpaqueFunction(function=launch_setup),
    ])
