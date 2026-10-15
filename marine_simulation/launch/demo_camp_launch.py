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
Start CAMP on the demo's own settings and an emptied tile cache, for the launch manager.

The manager's ``camp`` group uses this instead of CAMP's plain ``camp_launch.py``, which runs
on the operator's own settings and the shared live tile cache (stale coverage from an earlier
session shows). Everything is done by ``demo_launch.camp_actions``, the same code the
one-launch demo uses, so the two cannot drift. Unlike ``demo_launch.py`` nothing here shuts
the launch down when CAMP closes: the manager treats that exit as the operator closing the
demo.
"""

import importlib.util
import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch.substitutions import PathJoinSubstitution
from launch.substitutions import TextSubstitution
from launch_ros.substitutions import FindPackageShare


def _load_demo_launch():
    """Load the sibling ``demo_launch.py`` (a launch file is not a package)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'demo_launch.py')
    spec = importlib.util.spec_from_file_location('demo_launch', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


demo_launch = _load_demo_launch()


def launch_setup(context, *args, **kwargs):
    """Select the boats, take the demo lock and return the CAMP start actions."""
    def arg(name: str) -> str:
        return LaunchConfiguration(name).perform(context)

    boats_launch = demo_launch.boats_launch
    boats = boats_launch.select_boats(boats_launch.load_roster(arg('roster_file')),
                                      arg('boats'))
    target_file = arg('target_area_file')
    if target_file:
        target_file = os.path.abspath(os.path.expanduser(target_file))
        demo_launch.require_file(target_file, 'target_area_file')
    state = demo_launch.state_dir()
    if os.path.join(state, 'lock') not in demo_launch._LOCKS:
        # A manager starts this group again in the same process; it keeps the lock between.
        demo_launch.acquire_demo_lock(state)
    demo_launch.refuse_running_camp()
    return demo_launch.camp_actions(boats, arg('camp_profile'), arg('camp_view_config'),
                                    target_file)


def generate_launch_description():
    share = FindPackageShare('marine_simulation')
    return LaunchDescription([
        DeclareLaunchArgument('boats', default_value=TextSubstitution(text=''),
                              description='Comma separated boat names (default: the roster).'),
        DeclareLaunchArgument(
            'roster_file',
            default_value=PathJoinSubstitution([share, 'config', 'demo_roster.yaml']),
            description='Boat roster: the only place boat names live.'),
        DeclareLaunchArgument(
            'camp_profile',
            default_value=PathJoinSubstitution([share, 'config', 'demo_camp_profile.conf']),
            description='Fixed part of the CAMP settings every start begins from.'),
        DeclareLaunchArgument(
            'camp_view_config',
            default_value=PathJoinSubstitution([share, 'config', 'demo_camp_view.yaml']),
            description='Where and how far in CAMP starts.'),
        DeclareLaunchArgument('target_area_file', default_value=TextSubstitution(text=''),
                              description='Saved CAMP .json to open (optional).'),
        OpaqueFunction(function=launch_setup),
    ])
