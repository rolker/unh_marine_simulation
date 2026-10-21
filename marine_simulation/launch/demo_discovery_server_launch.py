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
Run the Fast DDS discovery server of the demo, for the launch manager's ``discovery`` group.

Every demo process finds the others through this one server (``ROS_DISCOVERY_SERVER``, set by
``demo_manager.py --discovery-server``) instead of announcing itself to every other participant
on the computer. The server is the first member of that list (id 0), listens on this host only
and is stopped with its group.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import ExecuteProcess
from launch.actions import OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch.substitutions import TextSubstitution
from marine_simulation import demo_support


def launch_setup(context, *args, **kwargs):
    """Return the server process; refuse a port that is not a port number."""
    text = LaunchConfiguration('port').perform(context)
    if not text.isdigit() or not 1024 <= int(text) <= 65535:
        raise RuntimeError('port %r is not a port number from 1024 to 65535' % text)
    return [ExecuteProcess(cmd=demo_support.discovery_server_command(int(text)),
                           name='fastdds_discovery_server', output='screen')]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'port', default_value=TextSubstitution(
                text=str(demo_support.DISCOVERY_SERVER_BASE_PORT)),
            description='UDP port of the server: 11811 + the ROS domain id of the demo.'),
        OpaqueFunction(function=launch_setup),
    ])
