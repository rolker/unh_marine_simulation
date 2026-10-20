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

"""The rclpy side of the convergence core: lifecycle service clients and graph discovery."""

import re
import time
from typing import Callable, Dict, List, Optional

from launch_manager_proto import lifecycle_core as core
from lifecycle_msgs.msg import State, Transition
from lifecycle_msgs.srv import ChangeState, GetState

_STATE_NAMES = {
    State.PRIMARY_STATE_UNCONFIGURED: core.UNCONFIGURED,
    State.PRIMARY_STATE_INACTIVE: core.INACTIVE,
    State.PRIMARY_STATE_ACTIVE: core.ACTIVE,
    State.PRIMARY_STATE_FINALIZED: core.FINALIZED,
    State.TRANSITION_STATE_CONFIGURING: 'configuring',
    State.TRANSITION_STATE_CLEANINGUP: 'cleaningup',
    State.TRANSITION_STATE_SHUTTINGDOWN: 'shuttingdown',
    State.TRANSITION_STATE_ACTIVATING: 'activating',
    State.TRANSITION_STATE_DEACTIVATING: 'deactivating',
    State.TRANSITION_STATE_ERRORPROCESSING: 'errorprocessing',
}
_TRANSITION_IDS = {
    core.CONFIGURE: Transition.TRANSITION_CONFIGURE,
    core.CLEANUP: Transition.TRANSITION_CLEANUP,
    core.ACTIVATE: Transition.TRANSITION_ACTIVATE,
    core.DEACTIVATE: Transition.TRANSITION_DEACTIVATE,
}


def state_name(state_id: int) -> str:
    """Return the core's name for a ``lifecycle_msgs/State`` id (``unknown`` if unlisted)."""
    return _STATE_NAMES.get(state_id, core.UNKNOWN)


def transition_id(name: str) -> int:
    """Return the ``lifecycle_msgs/Transition`` id for a core transition name."""
    return _TRANSITION_IDS[name]


def discover_lifecycle_nodes(node, pattern: Optional[str] = None,
                             exclude: Optional[str] = None) -> List[str]:
    """
    Return the fully qualified names of lifecycle nodes visible in the graph.

    A lifecycle node is one that serves both ``get_state`` and ``change_state`` with the
    ``lifecycle_msgs`` types. ``pattern`` is a regular expression searched in the name; a node
    whose name also matches ``exclude`` (searched the same way) is left out.
    """
    services = dict(node.get_service_names_and_types())
    regex = re.compile(pattern) if pattern else None
    excluded = re.compile(exclude) if exclude else None
    found = []
    for name, types in services.items():
        if not name.endswith('/get_state') or 'lifecycle_msgs/srv/GetState' not in types:
            continue
        base = name[:-len('/get_state')]
        if 'lifecycle_msgs/srv/ChangeState' not in services.get(base + '/change_state', []):
            continue
        if excluded is not None and excluded.search(base):
            continue
        if regex is None or regex.search(base):
            found.append(base)
    return sorted(found)


class _Pending:
    """A call awaiting its answer, with the deadline after which it counts as lost."""

    def __init__(self, deadline, client, future, on_timeout):
        self.deadline = deadline
        self.client = client
        self.future = future
        self.on_timeout = on_timeout


class RclpyBackend(core.Backend):
    """
    Lifecycle service clients on an rclpy node, with explicit per-call deadlines.

    ``expire()`` must be called regularly (the manager calls it from its tick): a call whose
    answer is overdue is reported as no answer and its late reply, if one ever comes, is
    dropped. Callbacks run on the executor thread that spins ``node``.
    """

    def __init__(self, node, query_timeout: float = 2.0,
                 monotonic: Callable[[], float] = time.monotonic):
        self._node = node
        self._query_timeout = query_timeout
        self._monotonic = monotonic
        self._get: Dict[str, object] = {}
        self._change: Dict[str, object] = {}
        self._pending: List[_Pending] = []

    def _client(self, cache, name: str, srv_type, suffix: str):
        client = cache.get(name)
        if client is None:
            client = self._node.create_client(srv_type, name + suffix)
            cache[name] = client
        return client

    def forget(self, name: str) -> None:
        """Drop the clients of a node that is gone for good."""
        for cache in (self._get, self._change):
            client = cache.pop(name, None)
            if client is not None:
                self._node.destroy_client(client)

    def close(self) -> None:
        for name in list(self._get) + list(self._change):
            self.forget(name)

    def _call(self, client, request, timeout: float, on_result, on_timeout) -> None:
        if not client.service_is_ready():
            on_timeout()
            return
        future = client.call_async(request)
        entry = _Pending(self._monotonic() + timeout, client, future, on_timeout)
        self._pending.append(entry)

        def done(fut) -> None:
            if entry not in self._pending:
                return  # already reported as overdue
            self._pending.remove(entry)
            try:
                response = fut.result()
            except Exception:  # noqa: B902  a failed call is "no answer", not a crash
                response = None
            if response is None:
                on_timeout()
            else:
                on_result(response)

        future.add_done_callback(done)

    def expire(self) -> None:
        """Report overdue calls as unanswered and forget their pending requests."""
        now = self._monotonic()
        for entry in [p for p in self._pending if p.deadline <= now]:
            self._pending.remove(entry)
            try:
                entry.client.remove_pending_request(entry.future)
            except Exception:  # noqa: B902  best effort, the client may already be gone
                pass
            entry.on_timeout()

    def get_state(self, node: str, callback) -> None:
        client = self._client(self._get, node, GetState, '/get_state')
        self._call(client, GetState.Request(), self._query_timeout,
                   lambda response: callback(state_name(response.current_state.id)),
                   lambda: callback(None))

    def change_state(self, node: str, transition: str, timeout: float, callback) -> None:
        client = self._client(self._change, node, ChangeState, '/change_state')
        request = ChangeState.Request()
        request.transition.id = transition_id(transition)
        self._call(client, request, timeout,
                   lambda response: callback(core.REPLY_OK if response.success
                                             else core.REPLY_REFUSED),
                   lambda: callback(core.REPLY_TIMEOUT))
