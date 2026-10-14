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
Lifecycle convergence core: observe, compare, step toward the target, never command blindly.

This module has no ROS dependency. It is driven by ticks and talks to the world through a
``Backend`` (see ``lifecycle_rclpy.py`` for the rclpy one), so every scenario, including a
lost ``change_state`` reply, is unit tested with a fake backend and a fake clock.

The rules, from the launch manager design ("converge, do not command"):

* Decisions are made from ``get_state`` reads only. A ``change_state`` reply is advisory: a
  lost reply is detected because the state moved, not because the reply arrived.
* ``configuring`` / ``activating`` and the other transitional states are in flight: neither
  on target nor drift. Nothing is sent into them.
* ``unknown`` (no answer) never causes a command, because nothing can be compared.
* A bounded retry ladder: a failed attempt waits a backoff, re-reads, and re-sends only if
  the node is still off target; ``max_attempts`` per from-state, then the node is ``FAILED``.

Why a request is never sent from a stale read: ``rclpy.lifecycle`` nodes do not answer a
transition that is invalid for their current state with ``success=false``; the exception
escapes the service callback and the process dies (seen live: ``Transition is not registered``).
So a redundant request, from this loop racing a launch file's ``autostart``, kills a Python
node. The loop therefore (1) leaves a node alone until its state has been unchanged for
``settle`` seconds, which lets an autostart chain in progress finish, and (2) re-reads
immediately before every request and sends only if the node is still where it was.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

UNCONFIGURED = 'unconfigured'
INACTIVE = 'inactive'
ACTIVE = 'active'
FINALIZED = 'finalized'
UNKNOWN = 'unknown'
TRANSITIONAL = frozenset(
    ('configuring', 'cleaningup', 'shuttingdown', 'activating', 'deactivating',
     'errorprocessing'))
TARGETS = (UNCONFIGURED, INACTIVE, ACTIVE)

CONFIGURE = 'configure'
CLEANUP = 'cleanup'
ACTIVATE = 'activate'
DEACTIVATE = 'deactivate'

# Transition results the backend reports to ``change_state`` callbacks.
REPLY_OK = 'ok'
REPLY_REFUSED = 'refused'
REPLY_TIMEOUT = 'timeout'

# Per-node status in a report.
ON_TARGET = 'ON_TARGET'
CONVERGING = 'CONVERGING'
WAITING = 'WAITING'
STUCK = 'STUCK'
FAILED = 'FAILED'
FINALIZED_STATUS = 'FINALIZED'
MISSING = 'MISSING'
UNKNOWN_STATUS = 'UNKNOWN'
SUSPENDED = 'SUSPENDED'

# next hop: (target, observed) -> transition
_HOPS = {
    (ACTIVE, UNCONFIGURED): CONFIGURE,
    (ACTIVE, INACTIVE): ACTIVATE,
    (INACTIVE, ACTIVE): DEACTIVATE,
    (INACTIVE, UNCONFIGURED): CONFIGURE,
    (UNCONFIGURED, ACTIVE): DEACTIVATE,
    (UNCONFIGURED, INACTIVE): CLEANUP,
}


def next_transition(target: str, observed: str) -> Optional[str]:
    """Return the single transition that moves ``observed`` toward ``target``, or None."""
    return _HOPS.get((target, observed))


@dataclass
class ConvergeConfig:
    """Timing and budget knobs of the convergence loop (seconds)."""

    poll_period: float = 0.5
    query_timeout: float = 2.0
    reply_timeout: float = 5.0
    inflight_timeout: float = 15.0
    appear_timeout: float = 30.0
    settle: float = 2.0
    backoff: Sequence[float] = (0.5, 1.0, 2.0, 5.0, 5.0)
    max_attempts: int = 5


class Backend:
    """What the core needs from the world; callbacks may fire during or after the call."""

    def get_state(self, node: str, callback: Callable[[Optional[str]], None]) -> None:
        """Read the node's state; call back with its name or None if no answer came."""
        raise NotImplementedError

    def change_state(self, node: str, transition: str, timeout: float,
                     callback: Callable[[str], None]) -> None:
        """Request a transition; call back with REPLY_OK, REPLY_REFUSED or REPLY_TIMEOUT."""
        raise NotImplementedError


@dataclass
class NodeReport:
    """What the manager says about one node."""

    name: str
    target: str
    state: str
    status: str
    attempts: int = 0
    last_result: str = ''
    reason: str = ''


@dataclass
class _Node:
    name: str
    created: float
    observed: str = UNKNOWN
    ever_seen: bool = False
    first_seen: float = 0.0
    state_since: float = 0.0
    query_pending: bool = False
    next_query: float = 0.0
    # in-flight transition bookkeeping
    sent_at: Optional[float] = None
    from_state: str = ''
    transition: str = ''
    reply: Optional[str] = None
    reply_at: Optional[float] = None
    attempts: Dict[str, int] = field(default_factory=dict)
    backoff_until: float = 0.0
    confirm_state: str = ''
    confirm_at: float = 0.0
    failed: bool = False
    status: str = UNKNOWN_STATUS
    last_result: str = ''
    reason: str = ''

    def total_attempts(self) -> int:
        return max(self.attempts.values(), default=0)


class LifecycleConverger:
    """Drive a set of lifecycle nodes to a target state, one safe hop at a time."""

    def __init__(self, backend: Backend, clock: Callable[[], float],
                 config: Optional[ConvergeConfig] = None, target: str = ACTIVE,
                 log: Optional[Callable[[str], None]] = None):
        if target not in TARGETS:
            raise ValueError('lifecycle target must be one of %s, got %r' % (TARGETS, target))
        self._backend = backend
        self._clock = clock
        self.config = config or ConvergeConfig()
        self._target = target
        self._log = log or (lambda text: None)
        self._nodes: Dict[str, _Node] = {}
        self._suspended = False

    # -- membership and control --------------------------------------------------------

    @property
    def target(self) -> str:
        return self._target

    def set_target(self, target: str) -> None:
        """Change the target; this also clears failures, because the question changed."""
        if target not in TARGETS:
            raise ValueError('lifecycle target must be one of %s, got %r' % (TARGETS, target))
        self._target = target
        self.clear_failures()

    def add_node(self, name: str) -> None:
        if name not in self._nodes:
            self._nodes[name] = _Node(name=name, created=self._clock())

    def remove_node(self, name: str) -> None:
        self._nodes.pop(name, None)

    def node_names(self) -> List[str]:
        return sorted(self._nodes)

    def suspend(self) -> None:
        """Stop reading and commanding (the group is stopping or stopped)."""
        self._suspended = True

    def resume(self) -> None:
        """Start again from a clean slate: nodes of a restarted group are new processes."""
        self._suspended = False
        now = self._clock()
        for node in self._nodes.values():
            self._reset(node, now)

    def clear_failures(self) -> None:
        now = self._clock()
        for node in self._nodes.values():
            if node.failed:
                self._reset(node, now)

    def _reset(self, node: _Node, now: float) -> None:
        node.failed = False
        node.attempts.clear()
        node.sent_at = None
        node.reply = None
        node.reply_at = None
        node.backoff_until = 0.0
        node.confirm_state = ''
        node.reason = ''
        node.last_result = ''
        node.created = now
        node.ever_seen = False
        node.observed = UNKNOWN
        node.status = UNKNOWN_STATUS

    # -- the loop ------------------------------------------------------------------------

    def tick(self) -> None:
        """Issue due reads. Everything else happens when a read comes back."""
        if self._suspended:
            return
        now = self._clock()
        for node in list(self._nodes.values()):
            if node.failed or node.query_pending or now < node.next_query:
                continue
            self._query(node, now)

    def _query(self, node: _Node, now: float) -> None:
        node.query_pending = True
        issued = now

        def done(state: Optional[str]) -> None:
            self._on_state(node.name, issued, state)

        self._backend.get_state(node.name, done)

    def _on_state(self, name: str, issued: float, state: Optional[str]) -> None:
        node = self._nodes.get(name)
        if node is None:
            return
        node.query_pending = False
        if self._suspended:
            return
        now = self._clock()
        node.next_query = now + self.config.poll_period
        if state is None:
            node.observed = UNKNOWN if not node.ever_seen else node.observed
            if not node.ever_seen:
                node.status = (MISSING if now - node.created > self.config.appear_timeout
                               else UNKNOWN_STATUS)
                if node.status == MISSING:
                    node.reason = 'not visible after %.0f s' % self.config.appear_timeout
            else:
                node.status = UNKNOWN_STATUS
                node.reason = 'no answer to get_state'
            return
        if not node.ever_seen:
            node.ever_seen = True
            node.first_seen = now
            node.state_since = now
            node.observed = state
        elif state != node.observed:
            node.observed = state
            node.state_since = now
        self._decide(node, issued, now)

    def _decide(self, node: _Node, issued: float, now: float) -> None:
        state = node.observed
        if state == self._target:
            self._on_target(node)
            return
        if state in TRANSITIONAL:
            if now - node.state_since > self.config.inflight_timeout:
                node.status = STUCK
                node.reason = 'in %s for %.0f s' % (state, now - node.state_since)
            else:
                node.status = WAITING
                node.reason = 'in flight: %s' % state
            return
        if state == FINALIZED:
            node.status = FINALIZED_STATUS
            node.reason = 'node is finalized; its process must be replaced'
            return

        if node.sent_at is not None and not self._resolve_pending(node, issued, now):
            return
        if now < node.backoff_until:
            node.status = WAITING
            node.reason = 'retry in %.1f s' % (node.backoff_until - now)
            return
        quiet_since = max(node.first_seen, node.state_since)
        if now - quiet_since < self.config.settle:
            node.confirm_state = ''
            node.status = WAITING
            node.reason = "settling (a launch file's autostart gets the first move)"
            return
        transition = next_transition(self._target, state)
        if transition is None:
            node.status = WAITING
            node.reason = 'no transition from %s toward %s' % (state, self._target)
            return
        if node.confirm_state != state or issued < node.confirm_at:
            # Look again right now; send only if the node is still exactly here.
            node.confirm_state = state
            node.confirm_at = now
            node.next_query = now
            node.status = WAITING
            node.reason = 'confirming %s before %s' % (state, transition)
            return
        node.confirm_state = ''
        self._send(node, transition, state, now)

    def _on_target(self, node: _Node) -> None:
        node.attempts.clear()
        node.sent_at = None
        node.reply = None
        node.backoff_until = 0.0
        node.status = ON_TARGET
        node.reason = ''

    def _resolve_pending(self, node: _Node, issued: float, now: float) -> bool:
        """
        Judge the outstanding request against a fresh read; True when free to act again.

        The state moved off ``from_state``: the transition happened, whatever the reply said.
        Still on ``from_state``: that is a failed attempt, but only once the request is
        resolved (reply in, or ``reply_timeout`` passed) and this read was issued after that.
        """
        if node.observed != node.from_state:
            node.last_result = ('%s done (reply %s)' % (node.transition, node.reply or 'lost'))
            node.sent_at = None
            node.reply = None
            return True
        resolved_at = node.reply_at
        if resolved_at is None:
            deadline = node.sent_at + self.config.reply_timeout
            if now < deadline:
                node.status = CONVERGING
                node.reason = 'waiting for %s reply' % node.transition
                return False
            resolved_at = deadline
        if issued < resolved_at:
            node.status = CONVERGING
            node.reason = 'verifying %s' % node.transition
            return False
        # Resolved and the state is unchanged: one failed attempt.
        why = {
            REPLY_OK: 'reply said success but the node stayed %s' % node.from_state,
            REPLY_REFUSED: 'transition refused',
        }.get(node.reply, 'no reply and the node stayed %s' % node.from_state)
        used = node.attempts.get(node.from_state, 0) + 1
        node.attempts[node.from_state] = used
        node.last_result = '%s attempt %d failed: %s' % (node.transition, used, why)
        node.sent_at = None
        node.reply = None
        if used >= self.config.max_attempts:
            node.failed = True
            node.status = FAILED
            node.reason = '%s failed %d times: %s' % (node.transition, used, why)
            self._log('%s: FAILED, %s' % (node.name, node.reason))
            return False
        backoff = self.config.backoff
        node.backoff_until = now + (backoff[min(used - 1, len(backoff) - 1)] if backoff else 0.0)
        return True

    def _send(self, node: _Node, transition: str, state: str, now: float) -> None:
        node.sent_at = now
        node.from_state = state
        node.transition = transition
        node.reply = None
        node.reply_at = None
        node.status = CONVERGING
        node.reason = 'sent %s from %s' % (transition, state)
        sent_at = node.sent_at
        self._log('%s: sending %s from %s (attempt %d)' % (
            node.name, transition, state, node.attempts.get(state, 0) + 1))

        def replied(result: str) -> None:
            current = self._nodes.get(node.name)
            if current is None or current.sent_at != sent_at:
                return  # a reply to a request we have already given up on
            if result == REPLY_TIMEOUT:
                return  # resolved by our own clock
            current.reply = result
            current.reply_at = self._clock()

        self._backend.change_state(node.name, transition, self.config.reply_timeout, replied)

    # -- reporting -----------------------------------------------------------------------

    def report(self) -> List[NodeReport]:
        out = []
        for name in sorted(self._nodes):
            node = self._nodes[name]
            status = SUSPENDED if self._suspended else node.status
            out.append(NodeReport(
                name=name, target=self._target, state=node.observed, status=status,
                attempts=node.total_attempts(), last_result=node.last_result,
                reason=node.reason))
        return out

    def all_on_target(self) -> bool:
        """Return True when there is at least one node and every node is on target."""
        return bool(self._nodes) and all(
            n.status == ON_TARGET and n.observed == self._target for n in self._nodes.values())

    def any_failed(self) -> bool:
        return any(n.failed or n.status in (FINALIZED_STATUS, MISSING)
                   for n in self._nodes.values())
