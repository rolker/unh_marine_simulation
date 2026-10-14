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
Groups, desired state and the profile: the manager's logic, with no ROS or launch imports.

Per-group desired state (``RUNNING`` / ``STOPPED``) is the single source of truth. A profile
writes desired state once; ``profile_actual`` is derived. The loop in ``tick()`` converges the
observed group state toward desired state and never "restarts" anything: a stop is a desired
state that became ``STOPPED``, so a stop is never mistaken for a failure.

The world is reached through three small interfaces so the whole thing is tested with fakes:

* ``Runner`` starts a group's launch description and stops it.
* ``Services`` discovers lifecycle nodes, checks node presence and builds convergers.
* The runner reports process events back through ``on_process_started`` / ``on_process_exited``.
"""

from typing import Callable, Dict, List, Optional

from launch_manager_proto import lifecycle_core as core
from launch_manager_proto.config import GroupSpec, ManagerSpec

DESIRED_RUNNING = 'RUNNING'
DESIRED_STOPPED = 'STOPPED'

STOPPED = 'STOPPED'
BLOCKED = 'BLOCKED'
STARTING = 'STARTING'
READY = 'READY'
DEGRADED = 'DEGRADED'
FAILED = 'FAILED'
STOPPING = 'STOPPING'

ACCEPTED = 'ACCEPTED'
REJECTED = 'REJECTED'

COMMAND_TYPES = ('SET_PROFILE', 'START', 'STOP', 'CLEAR_FAILURE')
SCHEMA = 1
ACK_RING = 8
DISCOVER_PERIOD = 2.0
_BAD_NODE_STATUS = (core.FAILED, core.FINALIZED_STATUS, core.MISSING)
_NO_SCOPED_STOP = ('scoped stop is not supported by this runner: stop everything or leave '
                   'the group running')


class Runner:
    """Starts and stops launch groups; reports process events to the core."""

    supports_scoped_stop = False

    def start(self, spec: GroupSpec) -> None:
        """Inject the group's launch description."""
        raise NotImplementedError

    def stop(self, name: str) -> None:
        """Stop only this group's processes (when ``supports_scoped_stop``)."""
        raise NotImplementedError

    def stop_all(self) -> None:
        """Stop every group at once."""
        raise NotImplementedError

    def group_stopped(self, name: str) -> None:
        """Tell the runner a group has fully stopped: drop whatever it kept for it."""


class Services:
    """Access to the ROS graph for readiness and lifecycle."""

    def discover(self, pattern: str) -> List[str]:
        """Return lifecycle node names matching ``pattern``."""
        raise NotImplementedError

    def node_visible(self, name: str) -> bool:
        """Return whether a node of this fully qualified name is in the graph."""
        raise NotImplementedError

    def make_converger(self, target: str) -> core.LifecycleConverger:
        """Build a converger for one group."""
        raise NotImplementedError

    def pump(self) -> None:
        """Run any periodic housekeeping (expire overdue service calls)."""

    def forget(self, names: List[str]) -> None:
        """Drop what is cached for lifecycle nodes that belong to a group that stopped."""


class _Group:
    """Runtime state of one group."""

    def __init__(self, spec: GroupSpec, now: float):
        self.spec = spec
        self.desired = DESIRED_STOPPED
        self.state = STOPPED
        self.detail = ''
        self.state_since = now
        self.blocked_by: List[str] = []
        self.alive: Dict[int, str] = {}
        self.started_at = 0.0
        self.ever_ready = False
        self.converger: Optional[core.LifecycleConverger] = None
        self.last_discovery = 0.0
        self.left_by_exit = False
        self.notes: List[str] = []


class ManagerCore:
    """The manager's state machine."""

    def __init__(self, spec: ManagerSpec, runner: Runner, services: Services,
                 clock: Callable[[], float], log: Optional[Callable[[str], None]] = None):
        self.spec = spec
        self._runner = runner
        self._services = services
        self._clock = clock
        self._log = log or (lambda text: None)
        now = clock()
        self._groups: Dict[str, _Group] = {n: _Group(g, now) for n, g in spec.groups.items()}
        self._acks: List[dict] = []
        self._stop_all_issued = False
        self._began = False
        self._shutting_down = False

    # -- queries ---------------------------------------------------------------------------

    def group_state(self, name: str) -> str:
        return self._groups[name].state

    def desired(self, name: str) -> str:
        return self._groups[name].desired

    def profile_actual(self) -> str:
        running = {n for n, g in self._groups.items() if g.desired == DESIRED_RUNNING}
        for name, members in self.spec.profiles.items():
            if set(members) == running:
                return name
        return 'custom'

    @property
    def finished(self) -> bool:
        """Whether the manager should exit: configured to, and every group is at rest."""
        return (self.spec.exit_when_all_stopped and self._began and all(
            g.desired == DESIRED_STOPPED and g.state == STOPPED and not g.alive
            for g in self._groups.values()))

    # -- starting up ------------------------------------------------------------------------

    def begin(self) -> None:
        """Converge to the default profile (the only thing a fresh start ever does)."""
        self._write_profile(self.spec.default_profile)
        self._began = True

    def _write_profile(self, name: str) -> None:
        members = set(self.spec.profiles[name])
        for group_name, group in self._groups.items():
            group.desired = DESIRED_RUNNING if group_name in members else DESIRED_STOPPED

    # -- events from the runner ------------------------------------------------------------

    def on_process_started(self, group: str, pid: int, name: str) -> None:
        g = self._groups.get(group)
        if g is not None:
            g.alive[pid] = name

    def on_shutdown(self) -> None:
        """Note that the launch service is going down: exits from now on are expected."""
        self._shutting_down = True

    def on_process_exited(self, group: str, pid: int, name: str, returncode: int,
                          respawning: bool = False) -> None:
        """
        Record a process exit.

        ``respawning`` means launch is restarting it: the group is not failed and not closed,
        its lifecycle node comes back unconfigured and the convergence loop repairs it, which
        is the gap ``LifecycleNode(autostart=True)`` leaves (it acts once, at launch time).
        """
        g = self._groups.get(group)
        if g is None:
            return
        g.alive.pop(pid, None)
        if self._shutting_down or g.state in (STOPPING, FAILED) or g.desired == DESIRED_STOPPED:
            return  # a requested stop, or the first cause is already on record
        if respawning:
            g.notes.append('process %s exited(%d), launch is respawning it' % (name, returncode))
            del g.notes[:-5]
            return
        now = self._clock()
        if not g.alive:
            if returncode == 0 and g.spec.restart == 'never':
                g.desired = DESIRED_STOPPED
                g.left_by_exit = True
                self._set(g, STOPPED, 'exited(0): closed by the operator', now)
                self._drop_converger(g)
                self._log('group %s exited cleanly; treating it as closed' % group)
            elif returncode == 0:
                self._fail(g, 'every process exited cleanly but the group should keep running '
                              '(restart is not implemented)', now)
            else:
                self._fail(g, 'process %s exited with code %d' % (name, returncode), now)
        elif returncode != 0:
            self._fail(g, 'process %s exited with code %d' % (name, returncode), now)
        else:
            g.notes.append('process %s exited(0)' % name)
            del g.notes[:-5]

    # -- commands --------------------------------------------------------------------------

    def handle_command(self, message) -> dict:
        """Apply one ``~/command`` message and return its ack (also kept in the ring)."""
        request_id = message.get('request_id') if isinstance(message, dict) else None
        if not isinstance(request_id, str) or not request_id:
            return {'request_id': '', 'result': REJECTED,
                    'detail': 'request_id must be a non-empty string'}
        for ack in self._acks:
            if ack['request_id'] == request_id:
                return ack
        result, detail = self._execute(message)
        ack = {'request_id': request_id, 'result': result, 'detail': detail}
        self._acks.append(ack)
        del self._acks[:-ACK_RING]
        self._log('command %s %s: %s %s' % (request_id, message.get('type'), result, detail))
        return ack

    def _execute(self, message: dict):
        kind = message.get('type')
        if kind not in COMMAND_TYPES:
            return REJECTED, 'type must be one of %s' % ', '.join(COMMAND_TYPES)
        if kind == 'SET_PROFILE':
            profile = message.get('profile')
            if profile not in self.spec.profiles:
                return REJECTED, 'unknown profile %r' % (profile,)
            members = set(self.spec.profiles[profile])
            wanted = {n: (DESIRED_RUNNING if n in members else DESIRED_STOPPED)
                      for n in self._groups}
            problem = self._check_change(wanted)
            if problem:
                return REJECTED, problem
            self._write_profile(profile)
            return ACCEPTED, 'profile %s written' % profile
        names = message.get('groups')
        if not isinstance(names, list) or not names or not all(
                isinstance(n, str) for n in names):
            return REJECTED, 'groups must be a non-empty list of group names'
        unknown = [n for n in names if n not in self._groups]
        if unknown:
            return REJECTED, 'unknown group(s): %s' % ', '.join(unknown)
        if kind == 'START':
            failed = [n for n in names if self._groups[n].state == FAILED]
            if failed:
                return REJECTED, '%s is FAILED: CLEAR_FAILURE first' % ', '.join(failed)
            for n in names:
                self._groups[n].desired = DESIRED_RUNNING
            return ACCEPTED, 'start %s' % ', '.join(names)
        if kind == 'CLEAR_FAILURE':
            not_failed = [n for n in names if self._groups[n].state != FAILED]
            if not_failed:
                return REJECTED, '%s is not FAILED' % ', '.join(not_failed)
        wanted = {n: g.desired for n, g in self._groups.items()}
        wanted.update({n: DESIRED_STOPPED for n in names})
        problem = self._check_change(wanted)
        if problem:
            return REJECTED, problem
        for n in names:
            self._groups[n].desired = DESIRED_STOPPED
        return ACCEPTED, '%s %s' % ('clear failure of' if kind == 'CLEAR_FAILURE' else 'stop',
                                    ', '.join(names))

    def _check_change(self, wanted: Dict[str, str]) -> Optional[str]:
        """Return why this desired-state change cannot be carried out, or None."""
        if self._runner.supports_scoped_stop:
            return None
        if all(d == DESIRED_STOPPED for d in wanted.values()):
            return None
        for name, desired in wanted.items():
            g = self._groups[name]
            has_work = g.alive and (g.desired == DESIRED_RUNNING or g.state == FAILED)
            if desired == DESIRED_STOPPED and has_work:
                return '%s: %s' % (name, _NO_SCOPED_STOP)
        return None

    # -- the loop --------------------------------------------------------------------------

    def tick(self) -> None:
        """Advance every group one step."""
        now = self._clock()
        self._services.pump()
        self._apply_follows(now)
        for group in self._groups.values():
            self._step(group, now)

    def _apply_follows(self, now: float) -> None:
        closed = [n for n, g in self._groups.items() if g.left_by_exit]
        if not closed:
            return
        for name in closed:
            self._groups[name].left_by_exit = False
        affected = set()
        frontier = list(closed)
        while frontier:
            leader = frontier.pop()
            for name, g in self._groups.items():
                if leader in g.spec.follows and name not in affected \
                        and g.desired == DESIRED_RUNNING:
                    affected.add(name)
                    frontier.append(name)
        for name in sorted(affected):
            self._groups[name].desired = DESIRED_STOPPED
            self._log('group %s follows %s, which closed: stopping it'
                      % (name, ', '.join(closed)))

    def _step(self, g: _Group, now: float) -> None:
        if g.desired == DESIRED_STOPPED:
            self._step_stopped(g, now)
            return
        if g.state == FAILED:
            self._tick_converger(g)
            return
        if g.state == STOPPING:
            if not g.alive:
                self._drop_converger(g)
                self._set(g, STOPPED, '', now)
            elif self._runner.supports_scoped_stop:
                self._runner.stop(g.spec.name)
            return
        if g.state in (STOPPED, BLOCKED):
            self._step_idle(g, now)
            return
        self._step_running(g, now)

    def _step_stopped(self, g: _Group, now: float) -> None:
        if g.alive:
            if g.state != STOPPING:
                self._begin_stop(g, now)
            elif self._runner.supports_scoped_stop:
                self._runner.stop(g.spec.name)
        elif g.state != STOPPED:
            self._drop_converger(g)
            self._set(g, STOPPED, '', now)
            if all(x.desired == DESIRED_STOPPED and not x.alive for x in self._groups.values()):
                self._stop_all_issued = False

    def _begin_stop(self, g: _Group, now: float) -> None:
        self._suspend(g)
        if self._runner.supports_scoped_stop:
            self._runner.stop(g.spec.name)
        else:
            everything_stopped = all(x.desired == DESIRED_STOPPED for x in self._groups.values())
            if not everything_stopped:
                self._fail(g, _NO_SCOPED_STOP, now)
                return
            if not self._stop_all_issued:
                self._stop_all_issued = True
                self._runner.stop_all()
        self._set(g, STOPPING, 'stopping', now)

    def _step_idle(self, g: _Group, now: float) -> None:
        blockers = [r for r in g.spec.requires if self._groups[r].state != READY]
        if blockers:
            g.blocked_by = blockers
            detail = 'waiting for ' + ', '.join(
                '%s (%s)' % (b, self._groups[b].state) for b in blockers)
            self._set(g, BLOCKED, detail, now)
            return
        g.blocked_by = []
        g.started_at = now
        g.ever_ready = False
        g.alive.clear()
        g.left_by_exit = False
        g.notes = []
        if g.spec.lifecycle is not None:
            g.converger = self._services.make_converger(g.spec.lifecycle.target)
            for node_name in g.spec.lifecycle.nodes:
                g.converger.add_node(node_name)
        self._set(g, STARTING, 'launch injected', now)
        try:
            self._runner.start(g.spec)
        except Exception as error:  # noqa: B902  any failure to start is the group's failure
            self._fail(g, 'cannot start: %s' % error, now)

    def _step_running(self, g: _Group, now: float) -> None:
        self._tick_converger(g, discover=True)
        reasons = self._not_ready_reasons(g)
        bad = [r for r in (g.converger.report() if g.converger else [])
               if r.status in _BAD_NODE_STATUS]
        if bad:
            first = bad[0]
            self._fail(g, 'lifecycle node %s %s: %s' % (first.name, first.status, first.reason),
                       now)
            return
        if not reasons:
            if g.state != READY:
                self._log('group %s is READY' % g.spec.name)
            g.ever_ready = True
            self._set(g, READY, '; '.join(g.notes), now)
            return
        detail = '; '.join(reasons)
        if g.ever_ready:
            self._set(g, DEGRADED, detail, now)
        elif now - g.started_at > g.spec.ready_timeout:
            self._fail(g, 'not ready after %.0f s: %s' % (g.spec.ready_timeout, detail), now)
        else:
            self._set(g, STARTING, detail, now)

    def _not_ready_reasons(self, g: _Group) -> List[str]:
        reasons = []
        if not g.alive:
            reasons.append('no process started yet')
        life = g.spec.lifecycle
        if life is not None and g.converger is not None:
            seen = g.converger.node_names()
            if len(seen) < life.expect:
                reasons.append('%d of %d expected lifecycle nodes seen' % (len(seen), life.expect))
            for report in g.converger.report():
                if report.status != core.ON_TARGET:
                    reasons.append('%s %s (%s)' % (report.name, report.state,
                                                   report.reason or report.status))
        for name in g.spec.ready_nodes:
            if not self._services.node_visible(name):
                reasons.append('node %s not visible' % name)
        for required in g.spec.requires:
            if self._groups[required].state != READY:
                reasons.append('requires %s: %s' % (required, self._groups[required].state))
        return reasons

    def _tick_converger(self, g: _Group, discover: bool = False) -> None:
        conv = g.converger
        if conv is None:
            return
        life = g.spec.lifecycle
        now = self._clock()
        if discover and life.match and now - g.last_discovery >= DISCOVER_PERIOD:
            g.last_discovery = now
            for node_name in self._services.discover(life.match):
                conv.add_node(node_name)
        conv.tick()

    def _suspend(self, g: _Group) -> None:
        if g.converger is not None:
            g.converger.suspend()

    def _drop_converger(self, g: _Group) -> None:
        """Forget the last run: a stopped group has no lifecycle nodes and no live handlers."""
        self._runner.group_stopped(g.spec.name)
        if g.converger is not None:
            self._services.forget(g.converger.node_names())
            g.converger = None

    def _fail(self, g: _Group, detail: str, now: float) -> None:
        if g.state != FAILED:
            self._log('group %s FAILED: %s' % (g.spec.name, detail))
        self._set(g, FAILED, detail, now)

    def _set(self, g: _Group, state: str, detail: str, now: float) -> None:
        if g.state != state:
            g.state = state
            g.state_since = now
        g.detail = detail

    # -- reporting -------------------------------------------------------------------------

    def status(self) -> dict:
        """Return the full snapshot published on ``~/status``."""
        groups = []
        for name, g in self._groups.items():
            entry = {
                'name': name, 'desired': g.desired, 'state': g.state, 'detail': g.detail,
                'state_since': g.state_since, 'blocked_by': list(g.blocked_by),
                'processes': len(g.alive), 'description': g.spec.description,
            }
            if g.spec.lifecycle is not None:
                nodes = {}
                if g.converger is not None:
                    for r in g.converger.report():
                        nodes[r.name] = {'state': r.state, 'status': r.status,
                                         'attempts': r.attempts, 'last_result': r.last_result,
                                         'reason': r.reason}
                entry['lifecycle'] = {'target': g.spec.lifecycle.target, 'nodes': nodes}
            groups.append(entry)
        return {
            'schema': SCHEMA, 'manager': self.spec.name, 'profile_actual': self.profile_actual(),
            'profiles_available': sorted(self.spec.profiles), 'groups': groups,
            'acks': list(self._acks),
        }
