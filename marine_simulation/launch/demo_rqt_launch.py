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
Start rqt on the demo's perspective, for the launch manager's ``rqt`` group.

The perspective (``config/demo.perspective``) holds Survey Coverage and one Ping Profile per boat.
On a first start, when the operator's rqt settings (``ros.org/rqt_gui.ini``) do not hold it yet,
or with ``rqt_fresh`` (``demo_manager.py --rqt-fresh``), rqt is started with
``--perspective-file``, which imports it as the hidden perspective ``@demo.perspective``;
after that rqt is started on that perspective by name, so it keeps the geometry and settings it
saved when it exited (see ``marine_simulation.demo_perspective`` for how rqt names it). One line
in the log says which way rqt was started. rqt runs on the operator's normal settings, never
on the wiped-per-start home CAMP gets. ``--lock-perspective`` is not used (the menu is needed to
rearrange the plugins, and the close button is how the operator closes the window). The window
is not placed: rqt restores its own geometry per perspective.

The group is optional display: a missing ``rqt`` is a message, never a failed demo.
"""

import shutil

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import ExecuteProcess
from launch.actions import LogInfo
from launch.actions import OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch.substitutions import PathJoinSubstitution
from launch.substitutions import TextSubstitution
from launch_ros.substitutions import FindPackageShare
from marine_simulation import demo_perspective
from marine_simulation import roster


def launch_setup(context, *args, **kwargs):
    """Return the rqt process and the line saying how it starts, or a message without rqt."""
    perspective_file = LaunchConfiguration('rqt_perspective_file').perform(context).strip()
    if not perspective_file:
        raise ValueError('rqt_perspective_file needs a path, not an empty string')
    fresh = roster.parse_bool(LaunchConfiguration('rqt_fresh').perform(context), 'rqt_fresh')
    rqt = shutil.which('rqt')
    if rqt is None:
        return [LogInfo(msg='rqt is not installed (sudo apt install ros-<distro>-rqt), '
                            'so the coverage window is not started; the demo goes on without it.')]
    arguments, how = demo_perspective.rqt_arguments(perspective_file, fresh)
    # rqt caches its discovered plugin list in its settings, so a plugin package built after the
    # first rqt start never shows in the Plugins menu until a forced rediscovery (seen 2026-10-19
    # with rqt_ping_profile after rolker/rqt_operator_tools#114 was built). It costs a second or
    # two at start.
    return [LogInfo(msg=how),
            ExecuteProcess(cmd=[rqt, '--force-discover'] + arguments, output='screen',
                           emulate_tty=True, name='rqt')]


def generate_launch_description():
    share = FindPackageShare('marine_simulation')
    return LaunchDescription([
        DeclareLaunchArgument(
            'rqt_perspective_file',
            default_value=PathJoinSubstitution([share, 'config', 'demo.perspective']),
            description='rqt perspective file: Survey Coverage and one Ping Profile per boat.'),
        DeclareLaunchArgument(
            'rqt_fresh', default_value=TextSubstitution(text='false'),
            description='true: import the perspective file again, replacing the stored one '
                        '(a first start).'),
        OpaqueFunction(function=launch_setup),
    ])
