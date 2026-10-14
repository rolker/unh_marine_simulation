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

"""Fake lifecycle world for the pure-core tests: a clock, node models and a backend."""

from typing import Callable, Dict, List, Optional, Set, Tuple

from launch_manager_proto import lifecycle_core as core

_RESULT = {
    core.CONFIGURE: ('configuring', core.INACTIVE),
    core.ACTIVATE: ('activating', core.ACTIVE),
    core.DEACTIVATE: ('deactivating', core.INACTIVE),
    core.CLEANUP: ('cleaningup', core.UNCONFIGURED),
}
_VALID_FROM = {
    core.CONFIGURE: core.UNCONFIGURED,
    core.ACTIVATE: core.INACTIVE,
    core.DEACTIVATE: core.ACTIVE,
    core.CLEANUP: core.INACTIVE,
}


class FakeClock:
    """A settable clock."""

    def __init__(self):
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class FakeNode:
    """A lifecycle node with scriptable faults (request numbers are 1-based)."""

    def __init__(self, state: str = core.UNCONFIGURED, duration: float = 0.2,
                 lose_reply_on: Tuple[int, ...] = (), ignore_request_on: Tuple[int, ...] = (),
                 refuse_on: Tuple[int, ...] = (), hidden_until: float = 0.0):
        self.state = state
        self.duration = duration
        self.lose_reply_on: Set[int] = set(lose_reply_on)
        self.ignore_request_on: Set[int] = set(ignore_request_on)
        self.refuse_on: Set[int] = set(refuse_on)
        self.hidden_until = hidden_until
        self.requests = 0
        self.received: List[str] = []
        self._busy: Optional[Tuple[float, str]] = None  # (done_at, goal)
        self._busy_state = ''

    def state_at(self, now: float) -> str:
        if self._busy and now >= self._busy[0]:
            self.state = self._busy[1]
            self._busy = None
        if self._busy:
            return self._busy_state
        return self.state

    def request(self, transition: str, now: float) -> Tuple[str, bool]:
        """Return (what happens, reply_lost). what is ok / refused / ignored."""
        self.state_at(now)
        self.requests += 1
        self.received.append(transition)
        if self.requests in self.ignore_request_on:
            return 'ignored', True
        if self._busy or _VALID_FROM[transition] != self.state or \
                self.requests in self.refuse_on:
            return 'refused', self.requests in self.lose_reply_on
        during, goal = _RESULT[transition]
        self._busy = (now + self.duration, goal)
        self._busy_state = during
        return 'ok', self.requests in self.lose_reply_on


class FakeBackend(core.Backend):
    """Delivers callbacks on a virtual timeline, ``latency`` seconds after the call."""

    def __init__(self, clock: FakeClock, nodes: Dict[str, FakeNode], latency: float = 0.05,
                 query_timeout: float = 2.0):
        self.clock = clock
        self.nodes = nodes
        self.latency = latency
        self.query_timeout = query_timeout
        self._due: List[Tuple[float, int, Callable[[], None]]] = []
        self._seq = 0
        self.sent: List[Tuple[str, str]] = []

    def _later(self, delay: float, fn: Callable[[], None]) -> None:
        self._seq += 1
        self._due.append((self.clock.now + delay, self._seq, fn))

    def pump(self) -> None:
        while True:
            ready = sorted(d for d in self._due if d[0] <= self.clock.now)
            if not ready:
                return
            item = ready[0]
            self._due.remove(item)
            item[2]()

    def get_state(self, node: str, callback) -> None:
        model = self.nodes.get(node)
        if model is None or self.clock.now < model.hidden_until:
            self._later(self.query_timeout, lambda: callback(None))
            return
        state_at_request = model.state_at(self.clock.now + self.latency)
        self._later(self.latency, lambda: callback(state_at_request))

    def change_state(self, node: str, transition: str, timeout: float, callback) -> None:
        self.sent.append((node, transition))
        model = self.nodes[node]
        outcome, lost = model.request(transition, self.clock.now)
        if lost:
            self._later(timeout, lambda: callback(core.REPLY_TIMEOUT))
        elif outcome == 'ok':
            self._later(self.latency, lambda: callback(core.REPLY_OK))
        else:
            self._later(self.latency, lambda: callback(core.REPLY_REFUSED))


def run(converger: core.LifecycleConverger, backend: FakeBackend, seconds: float,
        dt: float = 0.1, until: Optional[Callable[[], bool]] = None) -> None:
    """Advance virtual time, ticking the converger, optionally until a condition holds."""
    end = backend.clock.now + seconds
    while backend.clock.now < end:
        backend.clock.now += dt
        backend.pump()
        converger.tick()
        backend.pump()
        if until is not None and until():
            return
