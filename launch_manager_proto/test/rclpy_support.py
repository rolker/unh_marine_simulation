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

"""Shared helpers for the tests that need a running ROS graph on a private domain."""

import os
import random
import threading
import time

from launch_manager_proto import lifecycle_core as core
from launch_manager_proto.lifecycle_rclpy import RclpyBackend
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node


def private_domain() -> int:
    """Pick a random ROS_DOMAIN_ID above 100 (and not 42 or 88) for this process."""
    domain = int(os.environ.get('LMP_TEST_DOMAIN', random.randint(101, 232)))
    os.environ['ROS_DOMAIN_ID'] = str(domain)
    os.environ.setdefault('ROS_AUTOMATIC_DISCOVERY_RANGE', 'LOCALHOST')
    return domain


FAST = core.ConvergeConfig(
    poll_period=0.1, query_timeout=1.0, reply_timeout=1.0, settle=0.2,
    backoff=(0.2, 0.2, 0.2), max_attempts=4, inflight_timeout=5.0, appear_timeout=10.0)


class Spinner:
    """Spin a set of nodes on a background executor thread."""

    def __init__(self, *nodes):
        self.executor = MultiThreadedExecutor(num_threads=6)
        for node in nodes:
            self.executor.add_node(node)
        self.thread = threading.Thread(target=self.executor.spin, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.executor.shutdown()
        self.thread.join(timeout=5.0)


class ConvergeDriver:
    """A manager-side node ticking a converger over the real backend."""

    def __init__(self, names, config=FAST, target=core.ACTIVE, name='lmp_driver'):
        self.node = Node(name)
        self.backend = RclpyBackend(self.node, query_timeout=config.query_timeout)
        self.converger = core.LifecycleConverger(
            self.backend, time.monotonic, config, target=target)
        for n in names:
            self.converger.add_node(n)
        self.node.create_timer(0.05, self._tick)

    def _tick(self):
        self.backend.expire()
        self.converger.tick()

    def wait(self, predicate, timeout=30.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if predicate():
                return True
            time.sleep(0.05)
        return False


def init_ros():
    private_domain()
    if not rclpy.ok():
        rclpy.init()
