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

"""Unit tests for the convergence core, on a fake backend and a virtual clock."""

from fakes import FakeBackend, FakeClock, FakeNode, run
from launch_manager_proto import lifecycle_core as core
import pytest


def make(nodes, target=core.ACTIVE, **config):
    clock = FakeClock()
    backend = FakeBackend(clock, nodes)
    conv = core.LifecycleConverger(backend, clock, core.ConvergeConfig(**config), target=target)
    for name in nodes:
        conv.add_node(name)
    return conv, backend


def status(conv, name='/a'):
    return [r for r in conv.report() if r.name == name][0]


@pytest.mark.parametrize('target,start,expected', [
    (core.ACTIVE, core.UNCONFIGURED, ['configure', 'activate']),
    (core.ACTIVE, core.INACTIVE, ['activate']),
    (core.ACTIVE, core.ACTIVE, []),
    (core.INACTIVE, core.UNCONFIGURED, ['configure']),
    (core.INACTIVE, core.ACTIVE, ['deactivate']),
    (core.INACTIVE, core.INACTIVE, []),
    (core.UNCONFIGURED, core.ACTIVE, ['deactivate', 'cleanup']),
    (core.UNCONFIGURED, core.INACTIVE, ['cleanup']),
    (core.UNCONFIGURED, core.UNCONFIGURED, []),
])
def test_every_hop_to_every_target(target, start, expected):
    nodes = {'/a': FakeNode(start)}
    conv, backend = make(nodes, target=target)
    run(conv, backend, 30, until=conv.all_on_target)
    assert conv.all_on_target()
    assert nodes['/a'].received == expected


def test_next_transition_table_is_total_for_settled_states():
    for target in core.TARGETS:
        for state in (core.UNCONFIGURED, core.INACTIVE, core.ACTIVE):
            hop = core.next_transition(target, state)
            assert (hop is None) == (state == target)


def test_bad_target_rejected():
    with pytest.raises(ValueError):
        core.LifecycleConverger(FakeBackend(FakeClock(), {}), FakeClock(), target='running')


def test_nothing_is_sent_to_a_node_already_on_target():
    nodes = {'/a': FakeNode(core.ACTIVE)}
    conv, backend = make(nodes)
    run(conv, backend, 20)
    assert backend.sent == []
    assert status(conv).status == core.ON_TARGET


def test_settle_delay_lets_autostart_go_first():
    nodes = {'/a': FakeNode(core.UNCONFIGURED)}
    conv, backend = make(nodes, settle=2.0)
    run(conv, backend, 1.5)
    assert backend.sent == []
    assert status(conv).status == core.WAITING
    run(conv, backend, 3.0)
    assert backend.sent[0] == ('/a', 'configure')


def test_autostart_in_progress_is_never_interrupted():
    node = FakeNode(core.UNCONFIGURED, duration=3.0)
    nodes = {'/a': node}
    conv, backend = make(nodes, settle=0.0)
    # autostart configured the node a moment before the manager looks
    node.request('configure', backend.clock.now)
    run(conv, backend, 1.0)
    assert status(conv).state == 'configuring'
    assert backend.sent == []          # in flight: neither on target nor drift
    run(conv, backend, 30, until=conv.all_on_target)
    assert conv.all_on_target()
    assert node.received == ['configure', 'activate']


def test_two_writers_back_to_back_end_on_target():
    node = FakeNode(core.INACTIVE, duration=0.5)
    nodes = {'/a': node}
    conv, backend = make(nodes, settle=0.0)
    node.request('activate', backend.clock.now)       # autostart's activate
    run(conv, backend, 30, until=conv.all_on_target)
    assert conv.all_on_target()
    assert node.received == ['activate']              # the manager never added a second


def test_inflight_beyond_timeout_is_stuck_and_still_silent():
    node = FakeNode(core.UNCONFIGURED, duration=1000.0)
    nodes = {'/a': node}
    conv, backend = make(nodes, settle=0.0, inflight_timeout=5.0)
    node.request('configure', backend.clock.now)
    run(conv, backend, 4.0)
    assert status(conv).status == core.WAITING
    run(conv, backend, 4.0)
    assert status(conv).status == core.STUCK
    assert backend.sent == []


def test_unknown_never_commands_and_missing_is_reported():
    nodes = {'/a': FakeNode(core.UNCONFIGURED, hidden_until=1e9)}
    conv, backend = make(nodes, appear_timeout=10.0)
    run(conv, backend, 5)
    assert status(conv).status == core.UNKNOWN_STATUS
    run(conv, backend, 10)
    assert status(conv).status == core.MISSING
    assert backend.sent == []
    assert conv.any_failed()


def test_node_that_appears_late_is_converged():
    nodes = {'/a': FakeNode(core.UNCONFIGURED, hidden_until=105.0)}
    conv, backend = make(nodes, settle=0.5)
    run(conv, backend, 40, until=conv.all_on_target)
    assert conv.all_on_target()


def test_lost_configure_reply_is_detected_by_the_state_moving():
    # The bug record #96: the node configured, its reply never arrived.
    node = FakeNode(core.UNCONFIGURED, lose_reply_on=(1,))
    nodes = {'/a': node}
    conv, backend = make(nodes, settle=0.0)
    run(conv, backend, 60, until=conv.all_on_target)
    assert conv.all_on_target()
    assert node.received == ['configure', 'activate']   # configure sent exactly once
    assert not conv.any_failed()


def test_lost_activate_reply_too():
    node = FakeNode(core.UNCONFIGURED, lose_reply_on=(1, 2))
    nodes = {'/a': node}
    conv, backend = make(nodes, settle=0.0)
    run(conv, backend, 60, until=conv.all_on_target)
    assert conv.all_on_target()
    assert node.received == ['configure', 'activate']


def test_request_that_never_arrived_is_retried_after_backoff():
    node = FakeNode(core.UNCONFIGURED, ignore_request_on=(1,))
    nodes = {'/a': node}
    conv, backend = make(nodes, settle=0.0, backoff=(1.0,))
    run(conv, backend, 60, until=conv.all_on_target)
    assert conv.all_on_target()
    assert node.received == ['configure', 'configure', 'activate']


def test_refused_transition_counts_as_an_attempt_and_is_retried():
    node = FakeNode(core.UNCONFIGURED, refuse_on=(1, 2))
    nodes = {'/a': node}
    conv, backend = make(nodes, settle=0.0, backoff=(0.5,))
    run(conv, backend, 60, until=conv.all_on_target)
    assert conv.all_on_target()
    assert node.received.count('configure') == 3


def test_budget_exhausted_is_failed_and_stops_sending():
    node = FakeNode(core.UNCONFIGURED, ignore_request_on=tuple(range(1, 50)))
    nodes = {'/a': node}
    conv, backend = make(nodes, settle=0.0, backoff=(0.2,), max_attempts=3, reply_timeout=1.0)
    run(conv, backend, 60)
    rep = status(conv)
    assert rep.status == core.FAILED
    assert rep.attempts == 3
    assert 'configure' in rep.reason
    assert node.received == ['configure'] * 3
    sent = len(backend.sent)
    run(conv, backend, 30)
    assert len(backend.sent) == sent       # sticky: nothing more is sent


def test_failure_is_sticky_until_cleared_then_converges():
    node = FakeNode(core.UNCONFIGURED, ignore_request_on=(1, 2))
    nodes = {'/a': node}
    conv, backend = make(nodes, settle=0.0, backoff=(0.2,), max_attempts=2, reply_timeout=1.0)
    run(conv, backend, 30)
    assert status(conv).status == core.FAILED
    conv.clear_failures()
    run(conv, backend, 60, until=conv.all_on_target)
    assert conv.all_on_target()


def test_counters_reset_once_on_target():
    node = FakeNode(core.UNCONFIGURED, ignore_request_on=(1,))
    nodes = {'/a': node}
    conv, backend = make(nodes, settle=0.0, backoff=(0.2,), reply_timeout=1.0)
    run(conv, backend, 60, until=conv.all_on_target)
    assert status(conv).attempts == 0


def test_drift_is_repaired_after_reaching_target():
    node = FakeNode(core.UNCONFIGURED)
    nodes = {'/a': node}
    conv, backend = make(nodes, settle=0.0)
    run(conv, backend, 30, until=conv.all_on_target)
    node.state = core.INACTIVE        # something deactivated it
    run(conv, backend, 30, until=conv.all_on_target)
    assert conv.all_on_target()
    assert node.received[-1] == 'activate'


def test_finalized_is_reported_not_commanded():
    nodes = {'/a': FakeNode(core.FINALIZED)}
    conv, backend = make(nodes, settle=0.0)
    run(conv, backend, 10)
    assert status(conv).status == core.FINALIZED_STATUS
    assert backend.sent == []
    assert conv.any_failed()


def test_several_nodes_converge_independently():
    nodes = {
        '/a': FakeNode(core.UNCONFIGURED, lose_reply_on=(1,)),
        '/b': FakeNode(core.INACTIVE),
        '/c': FakeNode(core.ACTIVE),
    }
    conv, backend = make(nodes, settle=0.0)
    run(conv, backend, 60, until=conv.all_on_target)
    assert conv.all_on_target()
    assert nodes['/c'].received == []


def test_suspend_stops_all_traffic_and_resume_starts_fresh():
    nodes = {'/a': FakeNode(core.UNCONFIGURED)}
    conv, backend = make(nodes, settle=0.0)
    conv.suspend()
    run(conv, backend, 10)
    assert backend.sent == []
    assert status(conv).status == core.SUSPENDED
    conv.resume()
    run(conv, backend, 40, until=conv.all_on_target)
    assert conv.all_on_target()


def test_suspend_during_a_pending_read_ignores_its_answer():
    nodes = {'/a': FakeNode(core.UNCONFIGURED)}
    conv, backend = make(nodes, settle=0.0)
    conv.tick()                       # a read is now in flight
    conv.suspend()
    run(conv, backend, 10)            # its answer arrives while suspended
    assert backend.sent == []


def test_set_target_changes_direction_and_clears_failures():
    nodes = {'/a': FakeNode(core.ACTIVE)}
    conv, backend = make(nodes, settle=0.0)
    run(conv, backend, 5)
    conv.set_target(core.INACTIVE)
    run(conv, backend, 30, until=conv.all_on_target)
    assert nodes['/a'].state_at(backend.clock.now) == core.INACTIVE


def test_all_on_target_is_false_with_no_nodes():
    conv, _ = make({})
    assert not conv.all_on_target()


def test_late_reply_after_giving_up_is_ignored():
    node = FakeNode(core.UNCONFIGURED, lose_reply_on=(1,))
    nodes = {'/a': node}
    conv, backend = make(nodes, settle=0.0)
    run(conv, backend, 60, until=conv.all_on_target)
    # the stale REPLY_TIMEOUT callback arrives long after: must not raise or regress
    run(conv, backend, 10)
    assert conv.all_on_target()
