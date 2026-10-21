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
The navigation stack of the demo boats: what differs from Ben's, and what to leave alone.

Each boat runs the real ``ben_project11`` nav2 bring-up and ``mission_manager``. The only
change to Ben's nav2 parameters is the small, named delta in ``nav2_params``. Plain functions
with no launch context, so they are unit tested directly.
"""

import copy
import hashlib
import os
import re
from typing import Dict, Sequence

import yaml

# The lifecycle servers ben_project11's navigation_launch.py starts (its ``lifecycle_nodes``
# list) and nav2's own lifecycle manager brings up. The demo launch manager must not touch
# them: two writers on one node is how a lifecycle node ends up in the wrong state.
NAV2_SERVERS = (
    'controller_server', 'smoother_server', 'planner_server', 'behavior_server',
    'manda_coverage', 'velocity_smoother', 'collision_monitor', 'bt_task_navigator',
    'waypoint_follower', 'docking_server',
)
# The costmap nodes the controller and planner servers create (also lifecycle nodes, also
# configured by their parent server).
NAV2_COSTMAPS = ('local_costmap/local_costmap', 'global_costmap/global_costmap')

# The nav2 servers of one boat as composable nodes (issue 116): ``(package, plugin, name,
# remappings)``, the same nodes with the same remappings as the non-composed branch of
# ben_project11's ``navigation_launch.py`` (test_demo_nav compares the two, so a platform change
# cannot leave the composed boat different). ``manda_coverage`` is not a registered component:
# it stays its own process (COMPOSED_SEPARATE).
CMD_VEL_NAV = ('cmd_vel', 'cmd_vel_nav')
COMPOSED_NODES = (
    ('nav2_controller', 'nav2_controller::ControllerServer', 'controller_server',
     (CMD_VEL_NAV,)),
    ('nav2_smoother', 'nav2_smoother::SmootherServer', 'smoother_server', ()),
    ('nav2_planner', 'nav2_planner::PlannerServer', 'planner_server', ()),
    ('nav2_behaviors', 'behavior_server::BehaviorServer', 'behavior_server', (CMD_VEL_NAV,)),
    ('nav2_velocity_smoother', 'nav2_velocity_smoother::VelocitySmoother', 'velocity_smoother',
     (CMD_VEL_NAV, ('cmd_vel_smoothed', 'piloting_mode/autonomous/cmd_vel'))),
    ('nav2_collision_monitor', 'nav2_collision_monitor::CollisionMonitor', 'collision_monitor',
     ()),
    ('nav2_bt_navigator', 'nav2_bt_navigator::BtNavigator', 'bt_task_navigator', ()),
    ('nav2_waypoint_follower', 'nav2_waypoint_follower::WaypointFollower', 'waypoint_follower',
     ()),
    ('opennav_docking', 'opennav_docking::DockingServer', 'docking_server', ()),
)
COMPOSED_SEPARATE = {'manda_coverage': (('soundings', 'sensors/mbes/soundings'),)}
CONTAINER_NAME = 'nav2_container'
LIFECYCLE_MANAGER_NAME = 'lifecycle_manager_navigation'
LIFECYCLE_MANAGER_PLUGIN = 'nav2_lifecycle_manager::LifecycleManager'

# Lifecycle nodes the demo launch manager owns per boat when navigation is on, on top of the
# nine of a boat without it: ``mission_manager``.
NAV_MANAGED_NODES_PER_BOAT = 1

# nav2's lifecycle manager gives a server this long to answer on its bond (heartbeat), at
# bring-up and while running; the default is 4 s. Starting four boats with nav saturates a
# 16 core computer for over a minute, a bond then times out, and the manager aborts that
# boat's whole bring-up for good (seen: one of four boats stayed inactive). A node that dies
# is still noticed, after this long.
BOND_TIMEOUT_S = 30.0

# The global costmap of Ben's file is 5000 m x 5000 m at 1 m (25 million cells per boat, sent
# in full every second). The demo target is under 2 km across and the window follows the boat.
# 2400 m at 1 m (5.8 million cells) still made four boats' planners miss nav2's ten second
# acknowledge timeout on a 16 core computer, so the resolution is coarser too (2.6 million cells
# at 3200 m); the planner only plans transits between survey lines, the lines themselves are
# followed as sent.
GLOBAL_COSTMAP_SIZE_M = 3200
GLOBAL_COSTMAP_RESOLUTION_M = 2.0

# Ben's planner is SmacPlannerHybrid, tuned for the harbour's charted shallows. On the demo's
# empty costmap it gave up on a transit of 700 m or more (`no valid path found` after its 5 s
# budget, seen live), and a survey section starts with exactly such a transit. A boat's first
# line is up to a kilometre and a half away and the window follows the boat, hence 3200 m too.
# NavFn plans a straight line in open water in a moment; the planner id (GridBased) is kept.
PLANNER_PLUGIN = 'nav2_navfn_planner::NavfnPlanner'

# Ben's chart layer needs the S57 ENC tree and one ``s57_grids`` node per boat; the demo has
# neither, and its boats are put on open water.
CHART_LAYER = 'chart_layer'

# marine_nav_bt_task_navigator opens a BT::Groot2Publisher (ZeroMQ, ports 1667 and 1668) on every
# goal with no way to change or switch it off, so a second boat on the same computer cannot run a
# goal ("Address already in use", seen live: only one boat ever ran its section). The nav2
# processes of each boat are started with this library preloaded and DEMO_ZMQ_PORT_OFFSET set
# to a different number, which moves their ZeroMQ binds (src/demo_zmq_ports.c).
ZMQ_SHIM_LIBRARY = 'libdemo_zmq_ports.so'
ZMQ_PORT_STEP = 10

SOURCE_PACKAGE = 'ben_project11'
SOURCE_FILE = 'nav2_params.yaml'


def nav_exclude_regex(names: Sequence[str]) -> str:
    """Return the regular expression matching the nav2 lifecycle nodes of these boats."""
    boats = '|'.join(re.escape(n) for n in names)
    nodes = '|'.join(re.escape(n) for n in NAV2_SERVERS + NAV2_COSTMAPS)
    return '^/(%s)/(%s)$' % (boats, nodes)


def nav2_params(source: dict) -> dict:
    """
    Return Ben's nav2 parameters with the demo's delta applied (``source`` is not changed).

    The delta: the chart layer is removed from both costmaps (no ENC tree, no ``s57_grids``),
    the global costmap is ``GLOBAL_COSTMAP_SIZE_M`` square at ``GLOBAL_COSTMAP_RESOLUTION_M``
    instead of 5000 m at 1 m, and the ``GridBased`` planner is ``PLANNER_PLUGIN``. Raises
    ``ValueError`` when the source does not have the shape the delta needs, so a platform
    change cannot make it a silent no-op.
    """
    params = copy.deepcopy(source)
    for costmap in ('local_costmap', 'global_costmap'):
        try:
            node = params[costmap][costmap]['ros__parameters']
            plugins = list(node['plugins'])
        except (KeyError, TypeError):
            raise ValueError('the nav2 parameters have no %s.%s.ros__parameters.plugins'
                             % (costmap, costmap)) from None
        if CHART_LAYER not in plugins or CHART_LAYER not in node:
            raise ValueError('the %s of the nav2 parameters no longer has a %s to remove'
                             % (costmap, CHART_LAYER))
        node['plugins'] = [p for p in plugins if p != CHART_LAYER]
        del node[CHART_LAYER]
    try:
        node = params['global_costmap']['global_costmap']['ros__parameters']
        for key in ('width', 'height'):
            if key not in node:
                raise KeyError(key)
            node[key] = GLOBAL_COSTMAP_SIZE_M
        if 'resolution' not in node:
            raise KeyError('resolution')
        node['resolution'] = GLOBAL_COSTMAP_RESOLUTION_M
    except KeyError as error:
        raise ValueError('the global costmap of the nav2 parameters has no %s' % error) from None
    try:
        planner = params['planner_server']['ros__parameters']['GridBased']
    except (KeyError, TypeError):
        raise ValueError('the nav2 parameters have no planner_server GridBased planner') from None
    params['planner_server']['ros__parameters']['GridBased'] = {
        'plugin': PLANNER_PLUGIN,
        'tolerance': planner.get('tolerance', 1.5),
        'use_astar': True,
        'allow_unknown': True,
    }
    return params


def source_path() -> str:
    """Return the installed ``ben_project11`` nav2 parameter file."""
    from ament_index_python.packages import get_package_share_directory
    return os.path.join(get_package_share_directory(SOURCE_PACKAGE), 'config', SOURCE_FILE)


def write_params(directory: str, source_file: str = None) -> str:
    """
    Write the demo's nav2 parameters under ``directory`` and return the file's path.

    The name carries a hash of the content, so a start with the same inputs reuses the file
    and two demos never overwrite each other's.
    """
    with open(source_file or source_path()) as f:
        source = yaml.safe_load(f)
    text = yaml.safe_dump(nav2_params(source), default_flow_style=False, sort_keys=False)
    digest = hashlib.sha256(text.encode()).hexdigest()[:12]
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, 'nav2_params-%s.yaml' % digest)
    try:
        with open(path) as f:
            if f.read() == text:
                return path
    except OSError:
        pass            # absent, or unreadable: written below
    tmp = '%s.%d.tmp' % (path, os.getpid())
    try:
        with open(tmp, 'w') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def lifecycle_nodes_per_boat(base: int, enable_nav: bool) -> int:
    """Return how many lifecycle nodes the launch manager owns per boat."""
    return base + (NAV_MANAGED_NODES_PER_BOAT if enable_nav else 0)


def container_name(boat: str) -> str:
    """Return the fully qualified name of one boat's nav2 container (composed bring-up)."""
    return '/%s/%s' % (boat, CONTAINER_NAME)


def nav_node_names(boat: str) -> Dict[str, str]:
    """Return ``{short name: fully qualified name}`` of one boat's nav2 lifecycle nodes."""
    return {n: '/%s/%s' % (boat, n) for n in NAV2_SERVERS + NAV2_COSTMAPS}


def zmq_port_offset(index: int) -> int:
    """Return the ZeroMQ port offset of the ``index``-th boat that runs (the first keeps 0)."""
    if index < 0:
        raise ValueError('a boat index is not negative')
    return index * ZMQ_PORT_STEP


def zmq_shim_path(prefix: str) -> str:
    """Return where the ZeroMQ port shim is installed under a package ``prefix``."""
    return os.path.join(prefix, 'lib', 'marine_simulation', ZMQ_SHIM_LIBRARY)


def preload(shim: str, existing: str = '') -> str:
    """Return an ``LD_PRELOAD`` value that has ``shim`` first and keeps what was there."""
    kept = [p for p in existing.replace(':', ' ').split() if p != shim]
    return ' '.join([shim] + kept)
