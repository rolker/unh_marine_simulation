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

"""Tests of the joystick watchdog's state machine, driven with fake Joy messages."""

import json

from marine_simulation import watchdog_core as wc
import pytest

REST = ([0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0], [0] * 11)     # an Xbox pad, triggers at rest 1.0


def touched(throttle=0.8):
    axes = list(REST[0])
    axes[1] = throttle
    return axes, list(REST[1])


class Boat:
    """A watchdog core with a fake clock, a recorded output log and a fake mission."""

    def __init__(self, **params):
        self.now = 1000.0
        self.out = []
        self.log = []
        self.sent = []
        self.core = wc.WatchdogCore(wc.Params(**params), self.now, self.mission, self.log.append)
        self.core.on_area(self.now)
        self.core.on_tf(self.now, True)

    def mission(self, generation):
        ids = ['b_s%d/b_s%d_l%03d' % (generation, generation, n) for n in range(3)]
        text = 'replace_task mission_plan generation%d' % generation
        self.sent.append(text)
        return text, 'b_s%d' % generation, ids

    def do(self, actions):
        self.out += actions
        return actions

    def run(self, seconds, joy=REST, step=0.1, heartbeat='follow'):
        """Advance time; send ``joy`` every step (None: no pad) and a heartbeat each second."""
        end = self.now + seconds
        while self.now < end - 1e-9:
            self.now += step
            if joy is not None:
                self.do(self.core.on_joy(self.now, *joy))
            if heartbeat == 'follow' and int(self.now * 10) % 10 == 0 and \
                    self.core.desired_mode() is not None:
                self.core.on_heartbeat(self.now, self.core.desired_mode())
            self.do(self.core.tick(self.now))

    def take(self):
        out, self.out = self.out, []
        return out

    def tasks(self, gen, done=(), failed=()):
        """Feed mission_manager's report of generation ``gen``: every line, ``done`` finished."""
        rows = [('b_s%d' % gen, False, '')]
        for n in range(3):
            tid = 'b_s%d/b_s%d_l%03d' % (gen, gen, n)
            status = 'outcome: failed' if n in failed else ''
            rows.append((tid, n in done or n in failed, status))
        self.do(self.core.on_tasks(self.now, rows))


def test_an_idle_pad_hands_the_boat_to_autonomy_after_the_timeout():
    b = Boat(idle_timeout=30.0)
    b.run(29.0)
    assert b.core.state == wc.MANUAL and b.take() == []
    b.run(2.0)
    assert b.core.state == wc.AUTONOMOUS and b.core.reason == wc.REASON_IDLE
    out = b.take()
    assert out[0] == ('mode', 'autonomous')
    assert [k for k, _ in out].count('command') == 1
    assert b.sent == ['replace_task mission_plan generation1']


def test_the_first_active_message_hands_back_in_that_callback_manual_first():
    b = Boat(idle_timeout=5.0)
    b.run(8.0)
    b.tasks(1)
    b.take()
    assert b.core.state == wc.AUTONOMOUS and b.core.mission_state == wc.RUNNING
    b.now += 0.1
    actions = b.core.on_joy(b.now, *touched())
    assert actions == [('mode', 'manual'), ('command', 'clear_tasks')]
    assert b.core.state == wc.MANUAL and b.core.mission_state == wc.NOT_LOADED


def test_handing_over_again_sends_the_whole_section_from_the_first_line():
    b = Boat(idle_timeout=5.0)
    b.run(8.0)
    b.tasks(1, done=(0, 1))
    b.now += 0.1
    b.core.on_joy(b.now, *touched())
    b.take()
    b.run(7.0)
    assert b.core.state == wc.AUTONOMOUS
    assert b.sent == ['replace_task mission_plan generation1',
                      'replace_task mission_plan generation2']
    b.tasks(2)
    assert b.core.snapshot(b.now)['lines_done'] == 0       # nothing is carried over


def test_a_boat_without_a_pad_surveys_after_the_grace():
    b = Boat(missing_pad_grace=10.0)
    b.run(9.0, joy=None)
    assert b.core.state == wc.BOOT
    b.run(2.0, joy=None)
    assert b.core.state == wc.AUTONOMOUS and b.core.reason == wc.REASON_PAD_MISSING
    assert b.take()[0] == ('mode', 'autonomous')


def test_a_pad_that_stops_sending_hands_the_boat_to_autonomy():
    b = Boat(pad_lost_timeout=3.0, idle_timeout=100.0)
    b.run(5.0)
    assert b.core.state == wc.MANUAL
    b.run(3.5, joy=None)
    assert b.core.state == wc.AUTONOMOUS and b.core.reason == wc.REASON_PAD_MISSING


def test_a_pad_plugged_in_later_does_not_take_a_boat_that_surveys():
    b = Boat(missing_pad_grace=2.0)
    b.run(5.0, joy=None)
    assert b.core.state == wc.AUTONOMOUS
    b.take()
    b.run(5.0, joy=REST)            # appears, untouched, triggers at rest 1.0
    assert b.core.state == wc.AUTONOMOUS


def test_touching_a_late_pad_takes_the_boat():
    b = Boat(missing_pad_grace=2.0)
    b.run(5.0, joy=None)
    b.run(1.0, joy=REST)
    b.take()
    b.now += 0.1
    assert ('mode', 'manual') in b.core.on_joy(b.now, *touched())
    assert b.core.state == wc.MANUAL


def test_autorepeat_copies_of_an_untouched_pad_are_never_activity():
    b = Boat(idle_timeout=10.0)
    b.run(9.0, joy=([0.0, 0.0, -1.0, 0.0, 0.0, -1.0, 0.0, 0.0], [0] * 11))   # other rest values
    assert b.core.snapshot(b.now)['idle_s'] >= 8.9


@pytest.mark.parametrize('axes, buttons', [
    ([0.0, 0.06, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0], [0] * 11),             # a stick just past 0.05
    ([0.0, 0.0, 1.0, 0.0, 0.0, 0.5, 0.0, 0.0], [0] * 11),              # a trigger pulled
    ([0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0], [0] * 11),              # the d-pad
    ([0.0] * 2 + [1.0] + [0.0] * 5, [1] + [0] * 10),                   # a button
])
def test_anything_beyond_the_threshold_or_any_button_is_activity(axes, buttons):
    b = Boat(idle_timeout=5.0)
    b.run(8.0)
    b.take()
    b.now += 0.1
    assert ('mode', 'manual') in b.core.on_joy(b.now, axes, buttons)


def test_a_small_wobble_below_the_threshold_is_not_activity():
    b = Boat(idle_timeout=5.0)
    b.run(1.0)
    b.now += 0.1
    b.core.on_joy(b.now, [0.0, 0.04, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0], [0] * 11)
    assert b.core.snapshot(b.now)['idle_s'] >= 1.0      # the clock was not reset


def test_a_held_stick_keeps_the_boat_manual():
    b = Boat(idle_timeout=5.0)
    b.run(1.0)
    b.run(20.0, joy=touched(0.7))          # constant, never moving: far from rest
    assert b.core.state == wc.MANUAL


def test_the_mission_waits_for_the_map_frame_and_then_for_the_command_gap():
    b = Boat(missing_pad_grace=1.0, tf_settle=3.0)
    b.core.on_tf(b.now, False)
    b.run(6.0, joy=None)
    assert b.core.state == wc.AUTONOMOUS and b.sent == []      # no frame: no plan
    b.core.on_tf(b.now, True)
    b.run(2.0, joy=None)
    assert b.sent == []                                        # not settled yet
    b.run(2.0, joy=None)
    assert len(b.sent) == 1


def test_no_area_is_a_state_and_the_boat_stays_manual_until_there_is_one():
    b = Boat(missing_pad_grace=1.0)
    b.core.has_area = False
    b.core.mission_state = wc.NO_AREA
    b.run(3.0, joy=None)
    assert b.core.snapshot(b.now)['mission'] == wc.NO_AREA and b.sent == []
    assert ('mode', 'autonomous') not in b.take()
    assert b.core.desired_mode() == 'manual'
    b.core.on_area(b.now)
    b.run(1.0, joy=None)
    assert len(b.sent) == 1
    assert b.core.desired_mode() == 'autonomous'
    assert ('mode', 'autonomous') in b.take()       # told when there is a section to run


def test_a_plan_that_cannot_be_made_says_so_and_does_not_spin():
    b = Boat(missing_pad_grace=1.0)

    def refuse(generation):
        raise ValueError('too small')

    b.core.mission = refuse
    b.run(5.0, joy=None)
    snap = b.core.snapshot(b.now)
    assert snap['mission'] == wc.NO_AREA and snap['area_error'] == 'too small'


def test_an_unacknowledged_section_is_resent_with_a_new_generation_and_flagged():
    b = Boat(missing_pad_grace=1.0, resend_period=30.0, unavailable_after=70.0)
    b.run(95.0, joy=None)
    assert len(b.sent) >= 3 and b.sent[1] == 'replace_task mission_plan generation2'
    assert b.core.snapshot(b.now)['navigator_unavailable'] is True
    b.tasks(len(b.sent))
    assert b.core.mission_state == wc.RUNNING
    assert b.core.snapshot(b.now)['navigator_unavailable'] is False


def test_feedback_of_an_earlier_send_is_not_taken_for_the_current_one():
    b = Boat(missing_pad_grace=1.0, resend_period=30.0)
    b.run(35.0, joy=None)
    assert len(b.sent) == 2
    b.tasks(1, done=(0, 1, 2))            # the first send's ids, all done
    assert b.core.mission_state == wc.LOADING


def test_done_lines_are_latched_and_an_empty_or_partial_report_changes_nothing():
    b = Boat(missing_pad_grace=1.0)
    b.run(3.0, joy=None)
    b.tasks(1, done=(0,))
    b.do(b.core.on_tasks(b.now, []))
    b.do(b.core.on_tasks(b.now, [('b_s1', False, '')]))
    b.tasks(1)                            # a stale list that forgot line 0
    assert b.core.snapshot(b.now)['lines_done'] == 1
    assert b.core.mission_state == wc.RUNNING


def test_a_complete_section_repeats_after_the_delay():
    b = Boat(missing_pad_grace=1.0, repeat_delay=10.0)
    b.run(3.0, joy=None)
    b.tasks(1, done=(0, 1), failed=(2,))
    assert b.core.mission_state == wc.COMPLETE
    assert b.core.snapshot(b.now)['lines_failed'] == 1
    b.run(8.0, joy=None)
    assert len(b.sent) == 1
    b.run(5.0, joy=None)
    assert len(b.sent) == 2 and b.core.mission_state == wc.LOADING


def test_hold_leaves_a_complete_section_alone():
    b = Boat(missing_pad_grace=1.0, on_complete='hold', repeat_delay=1.0)
    b.run(3.0, joy=None)
    b.tasks(1, done=(0, 1, 2))
    b.run(60.0, joy=None)
    assert len(b.sent) == 1 and b.core.mission_state == wc.COMPLETE


def test_a_silent_mission_manager_gets_the_section_again():
    b = Boat(missing_pad_grace=1.0, tasks_silence=20.0)
    b.run(3.0, joy=None)
    b.tasks(1)
    b.run(25.0, joy=None)
    assert len(b.sent) == 2


def test_a_helm_that_comes_back_in_manual_is_told_again():
    b = Boat(missing_pad_grace=1.0)
    b.run(3.0, joy=None)
    b.take()
    b.core.on_heartbeat(b.now, 'manual')          # helm_manager respawned, initial mode manual
    b.run(3.0, joy=None, heartbeat=None)
    assert ('mode', 'autonomous') in b.take()


def test_a_standby_helm_is_respected_until_the_pad_is_touched():
    b = Boat(missing_pad_grace=1.0)
    b.run(3.0, joy=None)
    b.take()
    b.core.on_heartbeat(b.now, 'standby')
    b.run(10.0, joy=None, heartbeat=None)
    assert ('mode', 'autonomous') not in b.take()


def test_the_state_is_json_with_the_numbers_the_self_test_reads():
    b = Boat(missing_pad_grace=1.0)
    b.run(3.0, joy=None)
    b.tasks(1, done=(1,))
    data = json.loads(b.core.snapshot_json(b.now))
    assert data['state'] == wc.AUTONOMOUS and data['reason'] == wc.REASON_PAD_MISSING
    assert (data['lines_total'], data['lines_done'], data['generation']) == (3, 1, 1)


@pytest.mark.parametrize('name, value', [
    ('idle_timeout', 0.0), ('missing_pad_grace', -1.0), ('on_complete', 'maybe'),
    ('activity_threshold', -0.1), ('repeat_delay', -1.0)])
def test_bad_parameters_are_refused(name, value):
    with pytest.raises(ValueError, match=name):
        wc.Params(**{name: value}).validate()


def test_an_area_that_cannot_be_split_is_asked_once_not_every_tick():
    b = Boat(missing_pad_grace=1.0)
    calls = []

    def refuse(generation):
        calls.append(generation)
        raise ValueError('too small')

    b.core.mission = refuse
    b.run(10.0, joy=None)                           # a hundred ticks
    assert len(calls) == 1
    b.core.on_area(b.now)                           # a new area is tried again
    b.run(2.0, joy=None)
    assert len(calls) == 2


def test_takeover_clears_a_plan_mission_manager_may_still_hold():
    b = Boat(idle_timeout=5.0)
    b.run(8.0)                                      # the section is sent, unacknowledged
    assert len(b.sent) == 1
    b.core.on_area(b.now)                           # the area changed: NOT_LOADED again
    assert b.core.mission_state == wc.NOT_LOADED
    b.now += 0.1
    actions = b.core.on_joy(b.now, *touched())
    assert actions == [('mode', 'manual'), ('command', 'clear_tasks')]
    b.now += 0.1
    b.core.on_joy(b.now, *REST)
    b.run(7.0)                                      # autonomous again, sent again
    b.take()
    b.now += 0.1
    assert ('command', 'clear_tasks') in b.core.on_joy(b.now, *touched())


def test_takeover_of_a_boat_that_never_sent_anything_clears_nothing():
    b = Boat(missing_pad_grace=1.0)
    b.core.has_area = False
    b.run(3.0, joy=None)
    b.now += 0.1
    b.core.on_joy(b.now, *REST)
    b.now += 0.1
    assert b.core.on_joy(b.now, *touched()) == [('mode', 'manual')]


def test_a_standby_helm_is_not_overridden_by_the_idle_timeout():
    b = Boat(idle_timeout=5.0)
    b.run(1.0)
    b.core.on_heartbeat(b.now, 'standby')
    b.run(15.0, heartbeat=None)
    assert b.core.state == wc.AUTONOMOUS
    out = b.take()
    assert ('mode', 'autonomous') not in out and b.sent == []
    b.now += 0.1
    assert ('mode', 'manual') in b.core.on_joy(b.now, *touched())


@pytest.mark.parametrize('held', [0, 3, 10])
def test_a_button_held_as_the_pad_appears_takes_the_boat(held):
    b = Boat(missing_pad_grace=2.0)
    b.run(5.0, joy=None)
    b.take()
    buttons = [0] * 11
    buttons[held] = 1
    b.now += 0.1
    assert ('mode', 'manual') in b.core.on_joy(b.now, list(REST[0]), buttons)
    assert b.core.state == wc.MANUAL


def test_a_button_held_on_a_pad_that_was_already_there_stays_activity():
    b = Boat(idle_timeout=5.0)
    b.run(1.0)
    buttons = [1] + [0] * 10
    b.run(20.0, joy=(REST[0], buttons))
    assert b.core.state == wc.MANUAL                # held: never idle


def test_a_stick_held_through_a_short_joy_gap_is_not_the_new_rest():
    b = Boat(idle_timeout=100.0, pad_lost_timeout=3.0, missing_pad_grace=100.0)
    b.run(1.0)
    b.run(6.0, joy=None)                            # the pad dropped out: autonomous
    assert b.core.state == wc.AUTONOMOUS
    b.take()
    b.now += 0.1
    assert ('mode', 'manual') in b.core.on_joy(b.now, *touched(0.7))


def test_a_pad_gone_for_long_gets_a_new_rest_state():
    b = Boat(idle_timeout=100.0, pad_lost_timeout=3.0, missing_pad_grace=100.0)
    b.run(1.0)
    b.run(wc.BASELINE_KEEP_SECONDS + 5.0, joy=None)
    b.take()
    b.run(2.0, joy=touched(0.7))                    # a different pad, resting off-centre
    assert b.core.state == wc.AUTONOMOUS


def test_the_navigator_flipping_unavailable_and_back_is_logged():
    b = Boat(missing_pad_grace=1.0, resend_period=30.0, unavailable_after=70.0)
    b.run(80.0, joy=None)
    assert any('has not taken the section' in line for line in b.log)
    b.tasks(len(b.sent))
    b.run(1.0, joy=None)
    assert any('answering again' in line for line in b.log)


def test_a_section_whose_every_line_failed_backs_off_before_repeating():
    b = Boat(missing_pad_grace=1.0, repeat_delay=10.0, failed_repeat_delay=100.0)
    b.run(3.0, joy=None)
    b.tasks(1, failed=(0, 1, 2))
    assert b.core.mission_state == wc.COMPLETE
    b.run(50.0, joy=None)
    assert len(b.sent) == 1
    b.run(55.0, joy=None)
    assert len(b.sent) == 2
