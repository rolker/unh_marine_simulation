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
A lifecycle node that speaks the real ``lifecycle_msgs`` services and misbehaves on request.

Used in-process by the rclpy tests and as a process by the launch-level tests
(``python3 fake_lifecycle_node.py --name x --lose-reply-on 1 --autostart``).
"""

import argparse
import sys
import threading
import time

from fakes import FakeNode
from launch_manager_proto import lifecycle_core as core
from launch_manager_proto.lifecycle_rclpy import transition_id
from lifecycle_msgs.msg import State
from lifecycle_msgs.srv import ChangeState, GetState
import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

_IDS = {
    core.UNCONFIGURED: State.PRIMARY_STATE_UNCONFIGURED,
    core.INACTIVE: State.PRIMARY_STATE_INACTIVE,
    core.ACTIVE: State.PRIMARY_STATE_ACTIVE,
    core.FINALIZED: State.PRIMARY_STATE_FINALIZED,
    'configuring': State.TRANSITION_STATE_CONFIGURING,
    'cleaningup': State.TRANSITION_STATE_CLEANINGUP,
    'activating': State.TRANSITION_STATE_ACTIVATING,
    'deactivating': State.TRANSITION_STATE_DEACTIVATING,
}
_BY_ID = {transition_id(name): name for name in
          (core.CONFIGURE, core.CLEANUP, core.ACTIVATE, core.DEACTIVATE)}


class FakeLifecycleNode(Node):
    """Serve get_state/change_state from a ``FakeNode`` model; hold lost replies back."""

    def __init__(self, name: str, namespace: str = '', hold: float = 3.0, **faults):
        super().__init__(name, namespace=namespace)
        self.model = FakeNode(**faults)
        self.hold = hold
        group = ReentrantCallbackGroup()
        self.create_service(GetState, '~/get_state', self._get_state, callback_group=group)
        self.create_service(ChangeState, '~/change_state', self._change_state,
                            callback_group=group)

    def _get_state(self, request, response):
        state = self.model.state_at(time.monotonic())
        response.current_state.id = _IDS[state]
        response.current_state.label = state
        return response

    def _change_state(self, request, response):
        name = _BY_ID[request.transition.id]
        outcome, lost = self.model.request(name, time.monotonic())
        if lost:
            time.sleep(self.hold)       # the reply comes after the client gave up
        response.success = outcome == 'ok'
        return response


def main(argv=None):
    """Run one fake lifecycle node until interrupted."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', required=True)
    parser.add_argument('--namespace', default='')
    parser.add_argument('--lose-reply-on', type=int, nargs='*', default=[])
    parser.add_argument('--ignore-request-on', type=int, nargs='*', default=[])
    parser.add_argument('--autostart', action='store_true',
                        help='configure and activate once, like LifecycleNode(autostart=True)')
    parser.add_argument('--hold', type=float, default=3.0)
    args = parser.parse_args(argv)
    rclpy.init()
    node = FakeLifecycleNode(
        args.name, args.namespace, hold=args.hold, lose_reply_on=tuple(args.lose_reply_on),
        ignore_request_on=tuple(args.ignore_request_on), duration=0.1)
    if args.autostart:
        def autostart():
            time.sleep(0.5)
            node.model.request(core.CONFIGURE, time.monotonic())
            time.sleep(0.3)
            node.model.request(core.ACTIVATE, time.monotonic())
        threading.Thread(target=autostart, daemon=True).start()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
