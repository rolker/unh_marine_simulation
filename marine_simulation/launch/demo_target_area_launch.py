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
Publish the demo's target survey area, for the launch manager's ``target_area`` group.

The scorer (``coverage_assessment``) assesses coverage against this area, so its group
``requires`` this one. The node is long running: it publishes once, latched, and keeps the
publisher alive so a scorer that starts or restarts later still receives the area.
"""

import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch.substitutions import TextSubstitution
from marine_simulation import demo_support


def launch_setup(context, *args, **kwargs):
    """Return the publisher node; refuse a target file that is not there."""
    target_file = LaunchConfiguration('target_area_file').perform(context)
    if target_file:
        target_file = os.path.abspath(os.path.expanduser(target_file))
        demo_support.require_file(target_file, 'target_area_file')
    return [demo_support.target_area_node(target_file)]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'target_area_file', default_value=TextSubstitution(text=''),
            description='Saved CAMP .json holding the target survey area (default: the '
                        'installed demo polygon).'),
        OpaqueFunction(function=launch_setup),
    ])
