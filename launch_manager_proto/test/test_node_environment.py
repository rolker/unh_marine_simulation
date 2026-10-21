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

"""``run_manager(node_environment=...)``: set for the manager's own node, gone for the groups."""

import os

from launch_manager_proto import manager
import pytest


class _Stop(Exception):
    pass


@pytest.fixture
def seen(monkeypatch):
    """Replace rclpy and the node: record the environment each sees, then stop the run."""
    record = {}
    monkeypatch.setattr(manager.rclpy, 'init',
                        lambda **kw: record.setdefault('init', dict(os.environ)))

    def node(*args, **kwargs):
        record['node'] = dict(os.environ)
        raise _Stop()

    monkeypatch.setattr(manager, 'ManagerNode', node)
    monkeypatch.setattr(manager.rclpy, 'ok', lambda: False)
    return record


def test_the_variable_is_set_while_the_context_and_node_are_made_and_gone_after(
        seen, monkeypatch):
    monkeypatch.delenv('ROS_SUPER_CLIENT', raising=False)
    with pytest.raises(_Stop):
        manager.run_manager(object(), {'ROS_SUPER_CLIENT': 'TRUE'})
    assert seen['init']['ROS_SUPER_CLIENT'] == 'TRUE'
    assert seen['node']['ROS_SUPER_CLIENT'] == 'TRUE'
    assert 'ROS_SUPER_CLIENT' not in os.environ


def test_a_value_the_caller_already_had_is_restored(seen, monkeypatch):
    monkeypatch.setenv('ROS_SUPER_CLIENT', 'FALSE')
    with pytest.raises(_Stop):
        manager.run_manager(object(), {'ROS_SUPER_CLIENT': 'TRUE'})
    assert os.environ['ROS_SUPER_CLIENT'] == 'FALSE'


def test_without_node_environment_nothing_is_touched(seen, monkeypatch):
    monkeypatch.delenv('ROS_SUPER_CLIENT', raising=False)
    with pytest.raises(_Stop):
        manager.run_manager(object())
    assert 'ROS_SUPER_CLIENT' not in seen['node']
