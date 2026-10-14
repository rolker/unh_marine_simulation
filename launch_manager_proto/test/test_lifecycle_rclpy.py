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

"""Convergence through real lifecycle services: a stock node and fault-injecting fakes."""

import time

from fake_lifecycle_node import FakeLifecycleNode
from launch_manager_proto import lifecycle_core as core
from launch_manager_proto import lifecycle_rclpy
from lifecycle_msgs.msg import State, Transition
import pytest
import rclpy
from rclpy.lifecycle import Node as StockLifecycleNode
from rclpy_support import ConvergeDriver, init_ros, Spinner


@pytest.fixture(scope='module', autouse=True)
def ros():
    init_ros()
    yield
    rclpy.shutdown()


def test_state_and_transition_ids_match_lifecycle_msgs():
    for name, state_id in (
            (core.UNCONFIGURED, State.PRIMARY_STATE_UNCONFIGURED),
            (core.INACTIVE, State.PRIMARY_STATE_INACTIVE),
            (core.ACTIVE, State.PRIMARY_STATE_ACTIVE),
            (core.FINALIZED, State.PRIMARY_STATE_FINALIZED)):
        assert lifecycle_rclpy.state_name(state_id) == name
    assert {n: lifecycle_rclpy.state_name(i) for n, i in (
        ('configuring', 10), ('cleaningup', 11), ('shuttingdown', 12),
        ('activating', 13), ('deactivating', 14), ('errorprocessing', 15))} == {
        n: n for n in core.TRANSITIONAL}
    assert lifecycle_rclpy.transition_id(core.CONFIGURE) == Transition.TRANSITION_CONFIGURE
    assert lifecycle_rclpy.transition_id(core.ACTIVATE) == Transition.TRANSITION_ACTIVATE


def test_a_stock_rclpy_lifecycle_node_is_converged_to_active():
    stock = StockLifecycleNode('lmp_stock', namespace='/t1')
    driver = ConvergeDriver(['/t1/lmp_stock'])
    with Spinner(stock, driver.node):
        assert driver.wait(driver.converger.all_on_target), driver.converger.report()
        assert driver.converger.report()[0].state == core.ACTIVE
    stock.destroy_node()
    driver.node.destroy_node()


def test_discovery_finds_lifecycle_nodes_and_filters_by_regex():
    one = FakeLifecycleNode('lmp_disc_a', namespace='/t2')
    two = FakeLifecycleNode('lmp_disc_b', namespace='/t3')
    probe = rclpy.create_node('lmp_probe')
    with Spinner(one, two, probe):
        end = time.monotonic() + 10
        found = []
        while time.monotonic() < end and len(found) < 2:
            found = lifecycle_rclpy.discover_lifecycle_nodes(probe, r'^/t[23]/lmp_disc')
            time.sleep(0.1)
        assert found == ['/t2/lmp_disc_a', '/t3/lmp_disc_b']
        assert lifecycle_rclpy.discover_lifecycle_nodes(probe, r'^/t3/') == ['/t3/lmp_disc_b']
    for node in (one, two, probe):
        node.destroy_node()


def test_lost_configure_reply_still_reaches_active():
    # Issue 96: the node configures, the reply never reaches the manager.
    fake = FakeLifecycleNode('lmp_lost', namespace='/t4', hold=3.0, lose_reply_on=(1,),
                             duration=0.1)
    driver = ConvergeDriver(['/t4/lmp_lost'])
    with Spinner(fake, driver.node):
        assert driver.wait(driver.converger.all_on_target), driver.converger.report()
        assert fake.model.received == ['configure', 'activate']
    fake.destroy_node()
    driver.node.destroy_node()


def test_ignored_request_is_retried():
    fake = FakeLifecycleNode('lmp_ignored', namespace='/t5', hold=1.5, ignore_request_on=(1,),
                             duration=0.1)
    driver = ConvergeDriver(['/t5/lmp_ignored'])
    with Spinner(fake, driver.node):
        assert driver.wait(driver.converger.all_on_target), driver.converger.report()
        assert fake.model.received == ['configure', 'configure', 'activate']
    fake.destroy_node()
    driver.node.destroy_node()


def test_exhausted_budget_ends_failed_with_a_reason():
    fake = FakeLifecycleNode('lmp_dead', namespace='/t6', hold=1.2,
                             ignore_request_on=tuple(range(1, 50)), duration=0.1)
    driver = ConvergeDriver(['/t6/lmp_dead'])
    with Spinner(fake, driver.node):
        assert driver.wait(lambda: driver.converger.report()[0].status == core.FAILED,
                           timeout=40.0), driver.converger.report()
        report = driver.converger.report()[0]
        assert report.attempts == 4 and 'configure' in report.reason
    fake.destroy_node()
    driver.node.destroy_node()


def test_two_boats_converge_in_parallel_despite_a_lost_reply():
    nodes = [FakeLifecycleNode('lmp_x', namespace='/t7', lose_reply_on=(1,), hold=3.0),
             FakeLifecycleNode('lmp_x', namespace='/t8'),
             FakeLifecycleNode('lmp_y', namespace='/t8', lose_reply_on=(2,), hold=3.0)]
    driver = ConvergeDriver(['/t7/lmp_x', '/t8/lmp_x', '/t8/lmp_y'])
    with Spinner(*nodes, driver.node):
        assert driver.wait(driver.converger.all_on_target), driver.converger.report()
    for node in nodes:
        node.destroy_node()
    driver.node.destroy_node()


def test_node_that_appears_after_the_manager_is_picked_up():
    driver = ConvergeDriver(['/t9/lmp_late'])
    late = None
    with Spinner(driver.node) as spinner:
        time.sleep(1.0)
        assert driver.converger.report()[0].status in (core.UNKNOWN_STATUS, core.WAITING)
        late = FakeLifecycleNode('lmp_late', namespace='/t9')
        spinner.executor.add_node(late)
        assert driver.wait(driver.converger.all_on_target), driver.converger.report()
    late.destroy_node()
    driver.node.destroy_node()
