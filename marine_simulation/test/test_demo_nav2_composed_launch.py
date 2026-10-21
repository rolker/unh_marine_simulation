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

"""Tests of launch/demo_nav2_composed_launch.py: one boat's nav2 servers in one container (116)."""

import importlib.util
import pathlib

from launch import LaunchContext
from launch.actions import GroupAction
from launch_ros.actions import LifecycleNode, LoadComposableNodes, Node, PushROSNamespace
from marine_simulation import demo_nav
import pytest
import yaml

LAUNCH = pathlib.Path(__file__).resolve().parents[1] / 'launch' / 'demo_nav2_composed_launch.py'
_spec = importlib.util.spec_from_file_location('demo_nav2_composed_launch', LAUNCH)
composed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(composed)


@pytest.fixture(scope='module')
def stack():
    """Return the entities of the launch's one group."""
    description = composed.generate_launch_description()
    (group,) = [e for e in description.entities if isinstance(e, GroupAction)]
    return group.get_sub_entities()


def _text(parts):
    """Return the text of a name that is a plain string or a list of text substitutions."""
    if isinstance(parts, str):
        return parts
    return ''.join(p.perform(LaunchContext()) if hasattr(p, 'perform') else p for p in parts)


def _loaded(stack):
    (loader,) = [e for e in stack if isinstance(e, LoadComposableNodes)]
    return loader, loader._LoadComposableNodes__composable_node_descriptions


def test_the_boats_namespace_is_pushed_before_the_container_and_the_nodes(stack):
    kinds = [type(e) for e in stack]
    push = kinds.index(PushROSNamespace)
    assert push < kinds.index(Node) < kinds.index(LoadComposableNodes)
    assert push < kinds.index(LifecycleNode)


def test_one_isolated_container_with_the_name_the_loader_targets(stack):
    (container,) = [e for e in stack if type(e) is Node]
    assert _text(container._Node__node_name) == demo_nav.CONTAINER_NAME
    assert container.node_package == 'rclcpp_components'
    assert container.node_executable == 'component_container_isolated'
    loader, _ = _loaded(stack)
    context = LaunchContext()
    context.launch_configurations['namespace'] = 'bluefin'
    target = ''.join(p.perform(context) for p in loader._LoadComposableNodes__target_container)
    assert target == demo_nav.container_name('bluefin')


def test_every_server_but_manda_coverage_is_loaded_with_its_remappings(stack):
    _, nodes = _loaded(stack)
    loaded = {}
    for node in nodes[:-1]:
        remaps = {(_text(src), _text(dst)) for src, dst in node.remappings or []}
        loaded[_text(node.node_name)] = (_text(node.package), _text(node.node_plugin), remaps)
    assert loaded == {name: (package, plugin, set(remaps))
                      for package, plugin, name, remaps in demo_nav.COMPOSED_NODES}


def test_the_lifecycle_manager_is_the_last_component_with_the_whole_list(stack):
    _, nodes = _loaded(stack)
    manager = nodes[-1]
    assert _text(manager.node_name) == demo_nav.LIFECYCLE_MANAGER_NAME
    assert _text(manager.node_plugin) == demo_nav.LIFECYCLE_MANAGER_PLUGIN
    (parameters,) = manager.parameters
    values = {_text(k): v for k, v in parameters.items()}
    assert [yaml.safe_load(_text(n)) for n in values['node_names']] == list(demo_nav.NAV2_SERVERS)


def test_manda_coverage_stays_its_own_lifecycle_node(stack):
    (node,) = [e for e in stack if isinstance(e, LifecycleNode)]
    assert node.node_package == 'manda_coverage'
    assert node.node_executable == 'manda_coverage_action_server'
    assert _text(node._Node__node_name) == 'manda_coverage'


def test_the_arguments_are_the_ones_the_boats_launch_passes():
    declared = {e.name for e in composed.generate_launch_description().entities
                if hasattr(e, 'default_value')}
    assert {'namespace', 'params_file'} <= declared
