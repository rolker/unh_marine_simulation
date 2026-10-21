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
One boat's nav2 stack with the servers composed into one container (issue 116).

Stands in for ``ben_project11``'s ``nav2_bringup_launch.py`` on the demo boats, with composition:
ten processes of nav2 per boat (the nine servers, the lifecycle manager) become one container,
beside ``manda_coverage``, which is not a registered component and stays its own process. The
same nodes with the same parameters and remappings as the non-composed bring-up
(``marine_simulation.demo_nav.COMPOSED_NODES``, checked against ``ben_project11`` by a test),
so the lifecycle node names, namespaces and the lifecycle manager's node list are the same and
nothing that reads them changes. ``ben_project11``'s own composed branch is not used: it
composes an extra ``bt_navigator``, leaves out ``manda_coverage`` and remaps differently.

Include it inside the group that sets the boat's environment (the namespace push is done here;
``PushROSNamespace`` of the boat itself must not be in scope) so everything the group sets
(``bond_timeout``, the ZeroMQ port environment) reaches the container too.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import GroupAction
from launch.actions import SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration
from launch.substitutions import TextSubstitution
from launch_ros.actions import LifecycleNode
from launch_ros.actions import LoadComposableNodes
from launch_ros.actions import Node
from launch_ros.actions import PushROSNamespace
from launch_ros.actions import SetParameter
from launch_ros.descriptions import ComposableNode
from launch_ros.descriptions import ParameterFile
from launch_ros.substitutions import FindPackageShare
from marine_simulation import demo_nav
from nav2_common.launch import ReplaceString
from nav2_common.launch import RewrittenYaml


def composed_nodes(configured_params, log_level, autostart, lifecycle_nodes):
    """Return the ``ComposableNode`` of every server and of the lifecycle manager."""
    nodes = [
        ComposableNode(package=package, plugin=plugin, name=name,
                       parameters=[configured_params], remappings=list(remappings))
        for package, plugin, name, remappings in demo_nav.COMPOSED_NODES]
    nodes.append(ComposableNode(
        package='nav2_lifecycle_manager', plugin=demo_nav.LIFECYCLE_MANAGER_PLUGIN,
        name=demo_nav.LIFECYCLE_MANAGER_NAME,
        parameters=[{'autostart': autostart, 'node_names': lifecycle_nodes}]))
    return nodes


def generate_launch_description():
    namespace = LaunchConfiguration('namespace')
    use_sim_time = LaunchConfiguration('use_sim_time')
    params_file = LaunchConfiguration('params_file')
    autostart = LaunchConfiguration('autostart')
    log_level = LaunchConfiguration('log_level')

    # the same two steps as ben_project11's bring-up and navigation launch files
    params_file = ReplaceString(
        source_file=params_file,
        replacements={'<robot_namespace>': ('/', namespace), '<tf_prefix>': (namespace,)})
    configured_params = ParameterFile(
        RewrittenYaml(source_file=params_file, root_key=namespace, param_rewrites={},
                      convert_types=True),
        allow_substs=True)

    # the lifecycle manager's list: every lifecycle node of the stack, as the non-composed
    # bring-up gives it (the names are the demo_nav ones)
    lifecycle_nodes = list(demo_nav.NAV2_SERVERS)

    group = GroupAction([
        PushROSNamespace(namespace),
        SetParameter('use_sim_time', use_sim_time),
        Node(name=demo_nav.CONTAINER_NAME, package='rclcpp_components',
             executable='component_container_isolated',
             parameters=[configured_params, {'autostart': autostart}],
             arguments=['--ros-args', '--log-level', log_level],
             output='screen', emulate_tty=True),
        LoadComposableNodes(
            target_container=[TextSubstitution(text='/'), namespace,
                              TextSubstitution(text='/' + demo_nav.CONTAINER_NAME)],
            composable_node_descriptions=composed_nodes(
                configured_params, log_level, autostart, lifecycle_nodes)),
        LifecycleNode(
            package='manda_coverage', executable='manda_coverage_action_server',
            name='manda_coverage', namespace='', output='screen',
            parameters=[configured_params],
            arguments=['--ros-args', '--log-level', log_level],
            remappings=list(demo_nav.COMPOSED_SEPARATE['manda_coverage']),
            emulate_tty=True),
    ])
    return LaunchDescription([
        SetEnvironmentVariable('RCUTILS_LOGGING_BUFFERED_STREAM', '1'),
        DeclareLaunchArgument('namespace', default_value='ben',
                              description='Top-level namespace of the boat.'),
        DeclareLaunchArgument('use_sim_time', default_value='false',
                              description='Use the simulation clock if true.'),
        DeclareLaunchArgument(
            'params_file',
            default_value=[FindPackageShare('ben_project11'), '/config/nav2_params.yaml'],
            description='Full path to the nav2 parameters file (with <robot_namespace> '
                        'and <tf_prefix> placeholders).'),
        DeclareLaunchArgument('autostart', default_value='true',
                              description='Bring the stack up on its own.'),
        DeclareLaunchArgument('log_level', default_value='info', description='log level'),
        group,
    ])
