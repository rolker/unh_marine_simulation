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

``rqt --perspective demo`` switches to the perspective named ``demo`` and creates it when it
does not exist yet. Perspectives are kept by rqt in the operator's own settings
(``ros.org/rqt_gui.ini``) and written when rqt exits, so rqt runs on the operator's normal
settings, never on the wiped-per-start home CAMP gets: the Survey Coverage plugin added once by
hand comes back on every later start. ``--lock-perspective`` is not used (the menu is needed to
add the plugin, and the close button is how the operator closes the window). The window is not
placed: rqt restores its own geometry per perspective.

The group is optional display: a missing ``rqt`` is a message, never a failed demo.
"""

import shutil

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import ExecuteProcess
from launch.actions import LogInfo
from launch.actions import OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch.substitutions import TextSubstitution


def launch_setup(context, *args, **kwargs):
    """Return the rqt process, or a message when rqt is not installed."""
    perspective = LaunchConfiguration('rqt_perspective').perform(context).strip()
    if not perspective:
        raise ValueError('rqt_perspective needs a name, not an empty string')
    rqt = shutil.which('rqt')
    if rqt is None:
        return [LogInfo(msg='rqt is not installed (sudo apt install ros-<distro>-rqt), '
                            'so the coverage window is not started; the demo goes on without it.')]
    return [ExecuteProcess(cmd=[rqt, '--perspective', perspective], output='screen',
                           emulate_tty=True, name='rqt')]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('rqt_perspective', default_value=TextSubstitution(text='demo'),
                              description='rqt perspective to start (created when new).'),
        OpaqueFunction(function=launch_setup),
    ])
