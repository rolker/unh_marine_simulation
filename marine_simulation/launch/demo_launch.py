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
Launch the whole demo display with one launch file (superseded by the launch manager).

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

import importlib.util
import os
from typing import Callable, List

from ament_index_python.packages import get_package_prefix
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import EmitEvent
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
from marine_simulation import demo_support as support
from marine_simulation import roster as boats_launch


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
                         'until that has landed' % support.TARGET_AREA_EXECUTABLE)
    return [Node(package='marine_simulation', executable=support.TARGET_AREA_EXECUTABLE,
                 name=support.TARGET_AREA_NODE_NAME, emulate_tty=True, output='screen',
                 parameters=[{'file': target_file}])]


def target_script_installed() -> bool:
    """Return True when the installed package carries the target-area publisher."""
    path = os.path.join(get_package_prefix('marine_simulation'), 'lib',
                        'marine_simulation', support.TARGET_AREA_EXECUTABLE)
    return os.path.isfile(path)


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
        support.require_file(target_file, 'target_area_file')
    if enable['camp'] or enable['scorer']:
        support.acquire_demo_lock(support.state_dir())
    if enable['camp']:
        support.refuse_running_camp()

    if enable['window_layout']:
        support.require_file(arg('layout_config'), 'layout_config')
        check_placement_prerequisites(arg('layout_config'))
    if enable['boats']:
        names = ['boats', 'roster_file', 'joystick_config', 'enable_joysticks']
        actions.append(IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(
                os.path.dirname(os.path.abspath(__file__)), 'demo_boats_launch.py')),
            launch_arguments={n: arg(n) for n in names}.items()))

    runtime = os.path.join(support.state_dir(), 'run')
    if enable['scorer']:
        template = os.path.join(get_package_share_directory('coverage_assessment'),
                                'config', 'coverage_assessment.yaml')
        params = support.write_scorer_parameters(template, boats, runtime)
        actions.append(IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('coverage_assessment'), 'launch',
            'coverage_assessment_launch.py')), launch_arguments={'params_file': params}.items()))

    actions.extend(target_area_actions(
        enable['target_area'], target_file, target_script_installed))

    if enable['camp']:
        camp_start = support.camp_actions(
            boats, arg('camp_profile'), arg('camp_view_config'), target_file)
        actions.extend(camp_start)
        actions.extend(camp_exit_handlers(camp_start[-1]))

    if enable['window_layout']:
        placement = support.placement_process(arg('layout_config'))
        actions.extend([placement, RegisterEventHandler(
            OnProcessExit(target_action=placement, on_exit=support.placement_exit))])
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
