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
The joystick watchdog's decisions: who drives a demo boat, and what it does on its own.

A boat is driven by its pad while somebody touches it. When nobody has for ``idle_timeout``
seconds, or there is no pad, the boat switches to ``autonomous`` and runs the survey of its
section; the first touch of the pad hands it back to ``manual`` at once and stops the survey.
Handing it over again restarts the whole section from its first line (a deliberate
simplification: nothing is paused or resumed).

This module is a state machine with no ROS in it. Time is passed in (seconds, any epoch), inputs
arrive through the ``on_*`` methods, and every method returns the actions the caller must
perform, as a list of ``(kind, text)``: ``('mode', 'manual' | 'autonomous')`` is a String for
``<boat>/piloting_mode`` and ``('command', text)`` one for ``<boat>/marine/mission_manager/
command``. Nothing here reads a clock or a topic, so the tests drive it with fake Joy messages.
"""

import dataclasses
import json
from typing import Callable, List, Optional, Sequence, Tuple

Action = Tuple[str, str]

# controller states
BOOT = 'BOOT'                  # no pad seen yet, not yet past the missing-pad grace
MANUAL = 'MANUAL'              # a pad is there; the boat is the pad's
AUTONOMOUS = 'AUTONOMOUS'      # the boat surveys its section

# mission states (only while AUTONOMOUS)
NOT_LOADED = 'NOT_LOADED'
LOADING = 'LOADING'            # sent, waiting for mission_manager to report the tasks
RUNNING = 'RUNNING'
COMPLETE = 'COMPLETE'
NO_AREA = 'NO_AREA'            # nothing to survey: no area has arrived (or it cannot be split)

BASELINE_KEEP_SECONDS = 60.0   # a pad back within this keeps the rest state it had
STARTUP_CLEAR_DELAY = 1.0      # s after start before the clear_tasks that empties a predecessor's
CLEAR_REPEATS = 2              # extra clear_tasks after the first (the topic is volatile)

REASON_IDLE = 'idle'
REASON_PAD_MISSING = 'pad_missing'


@dataclasses.dataclass
class Params:
    """The watchdog's parameters (the demo values are in ``config/demo_params.yaml``)."""

    idle_timeout: float = 30.0          # s without activity before the boat surveys
    missing_pad_grace: float = 10.0     # s after start without any Joy message
    pad_lost_timeout: float = 3.0       # s of Joy silence that mean the pad is gone
    activity_threshold: float = 0.05    # axis distance from the pad's rest that counts
    tf_settle: float = 3.0              # s the boat's map frame must have been there
    command_gap: float = 2.0            # s between commands (mission_manager reads depth 1)
    resend_period: float = 15.0         # s without an acknowledgement before sending again
    unavailable_after: float = 120.0    # s without one before the state says so
    tasks_silence: float = 60.0         # s of silence from a running mission before a re-send
    reconcile_after: float = 2.0        # s the heartbeat may disagree before a re-publish
    reconcile_period: float = 1.0       # s between re-publishes
    on_complete: str = 'repeat'         # 'repeat' sends the section again, 'hold' stays
    repeat_delay: float = 10.0          # s between the end of a section and its repeat
    failed_repeat_delay: float = 120.0  # s before repeating a section whose every line failed

    def validate(self) -> None:
        """Raise ``ValueError`` for a value the machine cannot work with."""
        positive = ('idle_timeout', 'missing_pad_grace', 'pad_lost_timeout', 'command_gap',
                    'resend_period', 'unavailable_after', 'tasks_silence', 'reconcile_after',
                    'reconcile_period')
        for name in positive:
            if not getattr(self, name) > 0.0:
                raise ValueError('%s must be greater than zero' % name)
        for name in ('activity_threshold', 'tf_settle', 'repeat_delay', 'failed_repeat_delay'):
            if not getattr(self, name) >= 0.0:
                raise ValueError('%s must not be negative' % name)
        if self.on_complete not in ('repeat', 'hold'):
            raise ValueError("on_complete must be 'repeat' or 'hold'")


def is_active(axes: Sequence[float], buttons: Sequence[int], baseline_axes: Sequence[float],
              previous_axes: Sequence[float], previous_buttons: Sequence[int],
              threshold: float) -> bool:
    """
    Return whether a Joy message shows somebody touching the pad.

    Any button that is pressed or that differs from the previous message (a button counts
    whatever the learned rest state is: one held when the pad appeared is still input), any axis
    farther than ``threshold`` from its rest value, or any axis that moved more than
    ``threshold`` since the previous message. Rest is the first message after the pad appeared,
    so trigger rest values need no knowledge; a held stick is far from rest, and the autorepeat
    copies of an untouched pad never differ from either.
    """
    if any(buttons) or list(buttons) != list(previous_buttons):
        return True
    for axis, rest, before in zip(axes, baseline_axes, previous_axes):
        if abs(axis - rest) > threshold or abs(axis - before) > threshold:
            return True
    return len(axes) != len(baseline_axes) or len(axes) != len(previous_axes)


class WatchdogCore:
    """
    The state machine of one boat.

    ``mission`` is called as ``mission(generation, nonce)`` when a section is to be sent and
    returns ``(command text, set task id, [line task ids])``, or raises ``ValueError`` when the
    area cannot be surveyed (the state then says ``NO_AREA``). ``generation`` and ``nonce``
    make the task ids of every send unique, so feedback of an earlier send is never taken for
    the current one. ``nonce`` is the instance's (a process that is restarted starts again at
    generation 1, and mission_manager may still report the ids of the instance before it), so
    the caller must put it into the ids. A new instance also assumes its predecessor left a
    mission loaded: it sends ``clear_tasks`` shortly after it starts, or at the first touch of
    the pad, whichever comes first.
    """

    def __init__(self, params: Params, start: float,
                 mission: Callable[[int, str], Tuple[str, str, List[str]]],
                 log: Callable[[str], None] = lambda text: None, nonce: str = ''):
        params.validate()
        self.p = params
        self.mission = mission
        self.log = log
        self.nonce = nonce
        self.start = start
        self.state = BOOT
        self.reason = ''
        self.mission_state = NOT_LOADED
        self.generation = 0
        self.has_area = False
        self.area_error = ''
        self._set_id = ''
        self._line_ids: List[str] = []
        self._done = set()
        self._failed = set()
        self._seen_at = 0.0
        self._sent_at: Optional[float] = None
        self._first_sent_at: Optional[float] = None
        self._last_command = -1e9
        self._completed_at: Optional[float] = None
        # the pad
        self._last_joy: Optional[float] = None
        self._baseline: Optional[tuple] = None
        self._previous: Optional[tuple] = None
        self._last_activity: Optional[float] = None
        # the helm and the frame
        self._heartbeat_mode: Optional[str] = None
        self._mismatch_since: Optional[float] = None
        self._last_publish = -1e9
        self._yielded = False
        self._tf_since: Optional[float] = None
        self._announce = False
        # a command went out that mission_manager may still hold; a restarted watchdog cannot
        # know what its predecessor left there
        self._may_be_loaded = True
        self._startup_clear = True        # the clear_tasks of the start has not gone out yet
        self._clears_left = 0             # repeats of a clear_tasks still to send
        self._next_clear = 0.0
        self._unavailable_logged = False
        self.changes = 0            # bumped on every change a state message should carry

    # -- inputs ------------------------------------------------------------------------------

    def on_joy(self, now: float, axes: Sequence[float], buttons: Sequence[int]) -> List[Action]:
        """Take a Joy message; hand the boat back to the pad when it shows activity."""
        axes, buttons = tuple(axes), tuple(buttons)
        present = self.pad_present(now)
        gap = None if self._last_joy is None else now - self._last_joy
        self._last_joy = now
        appeared = not present
        # The first message after the pad appeared is its rest state, but a pad that came back
        # after a short gap keeps the rest state it had: a stick held through a dropout is
        # input, not a new rest.
        keep = (self._baseline is not None and gap is not None and gap < BASELINE_KEEP_SECONDS
                and len(axes) == len(self._baseline[0]))
        fresh = self._baseline is None or (appeared and not keep)
        if fresh:
            self._baseline = (axes, buttons)
            self._previous = (axes, buttons)
        if appeared:
            self._last_activity = now           # the pad was seen just now, touched or not
        if fresh:
            active = any(buttons)               # axes have no rest value to compare with yet
        else:
            active = is_active(axes, buttons, self._baseline[0], self._previous[0],
                               self._previous[1], self.p.activity_threshold)
        self._previous = (axes, buttons)
        if not active:
            if self.state == BOOT:
                self._to(MANUAL, '', now)
            return []
        self._last_activity = now
        self._yielded = False
        if self.state == AUTONOMOUS:
            return self._take_over(now)
        actions: List[Action] = []
        if self.state == BOOT:
            self._to(MANUAL, '', now)
            if self._startup_clear:
                actions = self._clear(now)
        return actions

    def on_heartbeat(self, now: float, mode: str) -> List[Action]:
        """Take the helm's reported piloting mode."""
        if mode == 'standby' and self._heartbeat_mode != 'standby' and not self._expects(mode):
            self._yielded = True
            self.log('helm_manager reports standby; staying out until the pad is touched')
        elif mode != 'standby':
            self._yielded = False
        self._heartbeat_mode = mode
        return []

    def on_tasks(self, now: float, tasks: Sequence[Tuple[str, bool, str]]) -> List[Action]:
        """Take the mission tasks mission_manager reports: ``(id, done, status)`` each."""
        if not tasks or self.state != AUTONOMOUS or self.mission_state in (NOT_LOADED, NO_AREA):
            return []
        by_id = {t[0]: t for t in tasks}
        wanted = [self._set_id] + self._line_ids
        if not all(i in by_id for i in wanted):
            return []
        self._seen_at = now
        for line in self._line_ids:
            _, done, status = by_id[line]
            if done:
                self._done.add(line)               # monotonic: a stale list never undoes it
                if 'fail' in (status or '').lower():
                    self._failed.add(line)
        if self.mission_state == LOADING:
            self._first_sent_at = None      # taken: the next wait for the navigator starts anew
            self._mission_state(RUNNING)
            self.log('mission %s is running (%d lines)' % (self._set_id, len(self._line_ids)))
        if self.mission_state == RUNNING and len(self._done) == len(self._line_ids):
            self._mission_state(COMPLETE)
            self._completed_at = now
            self.log('section %s complete (%d lines, %d failed)'
                     % (self._set_id, len(self._line_ids), len(self._failed)))
        return []

    def on_area(self, now: float) -> List[Action]:
        """Note that the area to survey changed: a section already sent is replaced."""
        if self.state == AUTONOMOUS and self.mission_state not in (NOT_LOADED, NO_AREA):
            self.log('the target area changed; sending the section again')
        self.has_area = True
        self.area_error = ''
        if self.mission_state in (NO_AREA, LOADING, RUNNING, COMPLETE):
            self._mission_state(NOT_LOADED)
        return []

    def on_tf(self, now: float, ready: bool) -> None:
        """Note whether the boat's map frame exists (mission_manager needs it to place a plan)."""
        if not ready:
            self._tf_since = None
        elif self._tf_since is None:
            self._tf_since = now

    # -- the clock ----------------------------------------------------------------------------

    def tick(self, now: float) -> List[Action]:
        """Decide what time alone causes; call it a few times a second."""
        actions: List[Action] = []
        if self.state == BOOT and now - self.start >= self.p.missing_pad_grace:
            self._to(AUTONOMOUS, REASON_PAD_MISSING, now)
            self.log('no pad after %g s: the boat surveys by itself' % self.p.missing_pad_grace)
        elif self.state == MANUAL:
            if not self.pad_present(now):
                self._to(AUTONOMOUS, REASON_PAD_MISSING, now)
                self.log('the pad stopped sending: the boat surveys by itself')
            elif now - (now if self._last_activity is None else self._last_activity) \
                    >= self.p.idle_timeout:
                self._to(AUTONOMOUS, REASON_IDLE, now)
                self.log('nobody touched the pad for %g s: the boat surveys by itself'
                         % self.p.idle_timeout)
        actions += self._clear_tick(now)
        sent: List[Action] = []
        if self.state == AUTONOMOUS:
            sent = self._autonomous_tick(now)
        if self._announce:
            # a decision of the clock is told to the helm at once, not after the reconcile wait
            # (unless the helm is in standby: that is respected until the pad is touched). The
            # section is planned first, so an area that cannot be split is never announced as
            # autonomous.
            self._announce = False
            if not self._yielded and self.desired_mode() is not None:
                self._last_publish = now
                actions.append(('mode', self.desired_mode()))
        actions += sent
        actions += self._reconcile(now)
        unavailable = self.navigator_unavailable(now)
        if unavailable != self._unavailable_logged:
            self._unavailable_logged = unavailable
            self.changes += 1
            self.log('the navigator has not taken the section for %g s; still trying'
                     % self.p.unavailable_after if unavailable else
                     'the navigator is answering again')
        return actions

    # -- queries ------------------------------------------------------------------------------

    def pad_present(self, now: float) -> bool:
        """Return whether Joy messages are arriving (the driver repeats an untouched pad)."""
        return self._last_joy is not None and now - self._last_joy < self.p.pad_lost_timeout

    def desired_mode(self) -> Optional[str]:
        """
        Return the piloting mode the watchdog wants, or ``None`` before it has decided.

        With nothing to survey (``NO_AREA``) the boat stays ``manual`` even in the autonomous
        state: ``autonomous`` is announced when there is a section to run.
        """
        if self.state == AUTONOMOUS and self.mission_state == NO_AREA:
            return 'manual'
        return {MANUAL: 'manual', AUTONOMOUS: 'autonomous'}.get(self.state)

    def snapshot(self, now: float) -> dict:
        """Return the state as a plain dict (the node publishes it as JSON)."""
        return {
            'state': self.state, 'reason': self.reason, 'mission': self.mission_state,
            'generation': self.generation, 'set': self._set_id,
            'lines_total': len(self._line_ids), 'lines_done': len(self._done),
            'lines_failed': len(self._failed),
            'pad_present': self.pad_present(now),
            'idle_s': round(now - self._last_activity, 1) if self._last_activity is not None
            and self.pad_present(now) else None,
            'helm_mode': self._heartbeat_mode,
            'navigator_unavailable': self.navigator_unavailable(now),
            'has_area': self.has_area, 'area_error': self.area_error,
        }

    def navigator_unavailable(self, now: float) -> bool:
        """Return whether a section has been sent for too long without being taken."""
        return (self.mission_state == LOADING and self._first_sent_at is not None
                and now - self._first_sent_at >= self.p.unavailable_after)

    def snapshot_json(self, now: float) -> str:
        """Return ``snapshot`` as JSON text."""
        return json.dumps(self.snapshot(now), sort_keys=True)

    # -- internals ----------------------------------------------------------------------------

    def _expects(self, mode: str) -> bool:
        return self.desired_mode() == mode

    def _to(self, state: str, reason: str, now: float) -> None:
        if (state, reason) != (self.state, self.reason):
            self.state, self.reason = state, reason
            self.changes += 1
        if state == AUTONOMOUS:
            self._mission_state(NOT_LOADED if self.has_area else NO_AREA)
            self._mismatch_since = None
            self._announce = not self._yielded
            self._clears_left = 0       # no repeat may clear a section the boat is about to send

    def _mission_state(self, state: str) -> None:
        if state != self.mission_state:
            if self.state == AUTONOMOUS and (state == NO_AREA) != (self.mission_state == NO_AREA):
                self._announce = True       # the mode the helm should have just changed
            self.mission_state = state
            self.changes += 1

    def _take_over(self, now: float) -> List[Action]:
        """Hand back after a touch while autonomous: manual first, then stop the survey."""
        actions: List[Action] = [('mode', 'manual')]
        if self._may_be_loaded or self.mission_state in (LOADING, RUNNING, COMPLETE):
            actions += self._clear(now)
        self._to(MANUAL, '', now)
        self._mission_state(NOT_LOADED)
        self._reset_mission()
        self._mismatch_since = None
        self._last_publish = now
        self.log('the pad was touched: the boat is back in manual and the survey is cleared')
        return actions

    def _clear(self, now: float) -> List[Action]:
        """Return a ``clear_tasks`` and schedule its repeats (the topic is volatile)."""
        self._last_command = now
        self._may_be_loaded = False
        self._startup_clear = False
        self._clears_left = CLEAR_REPEATS
        self._next_clear = now + self.p.command_gap
        return [('command', 'clear_tasks')]

    def _clear_tick(self, now: float) -> List[Action]:
        """Send the start-up clear, and the repeats of a clear, while the boat is not surveying."""
        if self.state == AUTONOMOUS:
            return []
        if self._startup_clear and now - self.start >= min(
                STARTUP_CLEAR_DELAY, self.p.missing_pad_grace / 2.0):
            self.log('clearing what an earlier instance may have left in mission_manager')
            return self._clear(now)
        if self._clears_left > 0 and now >= self._next_clear:
            self._clears_left -= 1
            self._next_clear = now + self.p.command_gap
            self._last_command = now
            return [('command', 'clear_tasks')]
        return []

    def _reset_mission(self) -> None:
        self._line_ids, self._set_id = [], ''
        self._done, self._failed = set(), set()
        self._sent_at = self._first_sent_at = self._completed_at = None

    def _autonomous_tick(self, now: float) -> List[Action]:
        actions: List[Action] = []
        if self.mission_state == NO_AREA:
            return actions      # waits for on_area: an area that cannot be split is not retried
        if self._yielded:
            return actions      # the helm is in standby: nothing to send until the pad is touched
        if self.mission_state == COMPLETE:
            delay = self.p.failed_repeat_delay if self._failed and \
                len(self._failed) >= len(self._line_ids) else self.p.repeat_delay
            completed = now if self._completed_at is None else self._completed_at
            if self.p.on_complete == 'repeat' and now - completed >= delay:
                self.log('repeating the section')
                self._mission_state(NOT_LOADED)
            return actions
        if self.mission_state == RUNNING and now - self._seen_at >= self.p.tasks_silence:
            self.log('mission_manager has been silent for %g s; sending the section again'
                     % self.p.tasks_silence)
            self._mission_state(NOT_LOADED)
        if self.mission_state == LOADING and self._sent_at is not None \
                and now - self._sent_at >= self.p.resend_period:
            self._mission_state(NOT_LOADED)
        if self.mission_state == NOT_LOADED:
            actions += self._send(now)
        return actions

    def _send(self, now: float) -> List[Action]:
        if self._tf_since is None or now - self._tf_since < self.p.tf_settle:
            return []           # mission_manager dies on a plan sent before the map frame exists
        if now - self._last_command < self.p.command_gap:
            return []
        try:
            command, set_id, lines = self.mission(self.generation + 1, self.nonce)
        except ValueError as error:
            self.area_error = str(error)
            self._mission_state(NO_AREA)
            self._reset_mission()
            self.log('cannot plan the section: %s' % error)
            # an earlier section may still be loaded: the new area replaced it
            return self._clear(now) if self._may_be_loaded else []
        self.generation += 1
        self._set_id, self._line_ids = set_id, list(lines)
        self._done, self._failed = set(), set()
        if self._first_sent_at is None:
            self._first_sent_at = now
        self._sent_at = now
        self._last_command = now
        self._may_be_loaded = True
        self._mission_state(LOADING)
        self.log('sending section %s (%d lines)' % (set_id, len(lines)))
        return [('command', command)]

    def _reconcile(self, now: float) -> List[Action]:
        want = self.desired_mode()
        if want is None or self._yielded:
            return []
        if self._heartbeat_mode == want:
            self._mismatch_since = None
            return []
        if self._mismatch_since is None:
            self._mismatch_since = now
        waited = now - self._mismatch_since
        # before the first heartbeat the helm may simply not be up yet: ask now and then
        period = self.p.reconcile_period if self._heartbeat_mode is not None \
            else max(self.p.reconcile_period, 5.0)
        if waited >= self.p.reconcile_after and now - self._last_publish >= period:
            self._last_publish = now
            return [('mode', want)]
        return []
