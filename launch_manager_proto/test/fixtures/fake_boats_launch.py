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

"""Launch file for the launch-level tests: fake lifecycle nodes standing in for the boats."""

import os
import sys

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.substitutions import LaunchConfiguration

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE = os.path.join(os.path.dirname(HERE), 'fake_lifecycle_node.py')


def generate_launch_description():
    token = LaunchConfiguration('token')
    return LaunchDescription([
        DeclareLaunchArgument('token', default_value='x'),
        DeclareLaunchArgument('guard', default_value='false'),
        # one boat loses its first configure reply, as in the bug record
        ExecuteProcess(cmd=[sys.executable, FAKE, '--name', 'sonar', '--namespace',
                            ['/fb1_', token], '--lose-reply-on', '1', '--hold', '4'],
                       output='screen'),
        ExecuteProcess(cmd=[sys.executable, FAKE, '--name', 'sonar', '--namespace',
                            ['/fb2_', token], '--autostart'], output='screen'),
        ExecuteProcess(cmd=[sys.executable, FAKE, '--name', 'helm', '--namespace',
                            ['/fb2_', token], '--lose-reply-on', '2', '--hold', '4'],
                       output='screen'),
    ])
