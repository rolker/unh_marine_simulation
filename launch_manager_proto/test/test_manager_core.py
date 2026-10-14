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

"""The manager's logic against a fake runner, fake graph and virtual clock."""

import copy
import re

from fakes import FakeBackend, FakeClock, FakeNode
from launch_manager_proto import config
from launch_manager_proto import lifecycle_core as core
from launch_manager_proto import manager_core as mc
import pytest

DATA = {
    'manager': {'name': 'm', 'default_profile': 'demo', 'exit_when_all_stopped': True,
                'converge': {'settle': 0.0, 'backoff': [0.2], 'max_attempts': 3,
                             'reply_timeout': 1.0, 'poll_period': 0.1}},
    'groups': {
        'boats': {'launch': {'package': 'p', 'file': 'b.py'},
                  'follows': ['camp'], 'lifecycle': {'match': '^/b', 'expect': 2},
                  'ready': {'timeout': 20}},
        'camp': {'launch': {'package': 'c', 'file': 'c.py'}, 'requires': ['boats'],
                 'restart': 'never'},
        'scorer': {'launch': {'package': 's', 'file': 's.py'}, 'follows': ['camp'],
                   'lifecycle': {'nodes': ['/score']}},
    },
    'profiles': {'demo': ['boats', 'camp', 'scorer'], 'boats': ['boats'], 'none': []},
}


class FakeRunner(mc.Runner):
    """Records starts and stops; the test plays the part of the launch processes."""

    def __init__(self, scoped):
        self.supports_scoped_stop = scoped
        self.started = []
        self.stopped = []
        self.stopped_all = 0
        self.core = None
        self.pids = 100

    def start(self, spec):
        self.started.append(spec.name)

    def stop(self, name):
        self.stop_calls = getattr(self, 'stop_calls', 0) + 1
        if name not in self.stopped:
            self.stopped.append(name)

    def stop_all(self):
        self.stopped_all += 1

    def group_stopped(self, name):
        self.cleaned = getattr(self, 'cleaned', []) + [name]

    def launch_process(self, group, name='proc'):
        self.pids += 1
        self.core.on_process_started(group, self.pids, name)
        return self.pids

    def finish_stop(self, group):
        for pid in [p for p, g in self.pids_of(group)]:
            self.core.on_process_exited(group, pid, 'proc', -2)

    def pids_of(self, group):
        return [(p, group) for p in list(self.core._groups[group].alive)]


class FakeServices(mc.Services):
    """A graph made of the fake nodes."""

    def __init__(self, clock, nodes):
        self.clock = clock
        self.nodes = nodes
        self.backend = FakeBackend(clock, nodes)
        self.config = core.ConvergeConfig(settle=0.0, backoff=(0.2,), max_attempts=3,
                                          reply_timeout=1.0, poll_period=0.1)

    def discover(self, pattern):
        return sorted(n for n in self.nodes if re.search(pattern, n))

    def node_visible(self, name):
        return name in self.nodes

    def make_converger(self, target):
        return core.LifecycleConverger(self.backend, self.clock, self.config, target=target)

    def pump(self):
        self.backend.pump()

    def forget(self, names):
        self.forgotten = getattr(self, 'forgotten', []) + list(names)


class World:
    """A manager core wired to the fakes, with helpers to move virtual time."""

    def __init__(self, scoped=True, data=None, nodes=None):
        self.clock = FakeClock()
        self.nodes = nodes if nodes is not None else {
            '/b1/x': FakeNode(), '/b2/x': FakeNode(), '/score': FakeNode()}
        self.runner = FakeRunner(scoped)
        self.services = FakeServices(self.clock, self.nodes)
        self.logs = []
        spec = config.parse_config(copy.deepcopy(data or DATA))
        self.core = mc.ManagerCore(spec, self.runner, self.services, self.clock,
                                   self.logs.append)
        self.runner.core = self.core

    def run(self, seconds, until=None, dt=0.1):
        end = self.clock.now + seconds
        while self.clock.now < end:
            self.clock.now += dt
            self.services.backend.pump()
            self.core.tick()
            self.services.backend.pump()
            if until and until():
                return True
        return until() if until else None

    def state(self, name):
        return self.core.group_state(name)

    def boot(self):
        """Begin, launch every group's process as soon as it is started, run to all READY."""
        self.core.begin()
        launched = set()

        def step():
            for g in self.runner.started:
                if g not in launched:
                    launched.add(g)
                    self.runner.launch_process(g)
            return all(self.state(g) == mc.READY for g in ('boats', 'camp', 'scorer'))
        assert self.run(60, until=step), self.core.status()


def test_begin_writes_the_default_profile_and_derives_profile_actual():
    w = World()
    w.core.begin()
    assert {n: w.core.desired(n) for n in ('boats', 'camp', 'scorer')} == {
        'boats': mc.DESIRED_RUNNING, 'camp': mc.DESIRED_RUNNING, 'scorer': mc.DESIRED_RUNNING}
    assert w.core.profile_actual() == 'demo'


def test_dependents_wait_for_requires_then_everything_reaches_ready():
    w = World()
    w.core.begin()
    w.run(0.5)
    assert w.state('camp') == mc.BLOCKED
    assert w.core.status()['groups'][1]['blocked_by'] == ['boats']
    assert 'waiting for boats' in w.core.status()['groups'][1]['detail']
    assert w.runner.started == ['boats', 'scorer']        # camp is held back
    w.boot()
    assert w.runner.started == ['boats', 'scorer', 'camp']
    assert w.core.status()['profile_actual'] == 'demo'


def test_boats_not_ready_until_expected_lifecycle_nodes_are_active():
    w = World(nodes={'/b1/x': FakeNode(), '/score': FakeNode()})   # only one of two boats
    w.core.begin()
    w.run(2)
    w.runner.launch_process('boats')
    w.run(10)
    assert w.state('boats') == mc.STARTING
    assert '1 of 2 expected lifecycle nodes seen' in w.core.status()['groups'][0]['detail']


def test_ready_timeout_fails_the_group_with_a_reason():
    w = World(nodes={'/b1/x': FakeNode(), '/score': FakeNode()})
    w.core.begin()
    w.run(1)
    w.runner.launch_process('boats')
    w.run(30)
    assert w.state('boats') == mc.FAILED
    assert 'not ready after 20 s' in w.core.status()['groups'][0]['detail']
    assert w.state('camp') == mc.BLOCKED        # dependents point at the cause
    assert 'boats (FAILED)' in w.core.status()['groups'][1]['detail']


def test_lost_replies_in_a_group_still_end_ready():
    nodes = {'/b1/x': FakeNode(lose_reply_on=(1,)), '/b2/x': FakeNode(lose_reply_on=(2,)),
             '/score': FakeNode()}
    w = World(nodes=nodes)
    w.boot()
    assert nodes['/b1/x'].received == ['configure', 'activate']


def test_failed_lifecycle_node_fails_the_group_and_names_the_node():
    nodes = {'/b1/x': FakeNode(ignore_request_on=tuple(range(1, 20))), '/b2/x': FakeNode(),
             '/score': FakeNode()}
    w = World(nodes=nodes)
    w.core.begin()
    w.run(1)
    w.runner.launch_process('boats')
    assert w.run(40, until=lambda: w.state('boats') == mc.FAILED)
    detail = w.core.status()['groups'][0]['detail']
    assert '/b1/x' in detail and 'FAILED' in detail
    assert any('group boats FAILED' in line and '/b1/x' in line for line in w.logs)
    assert w.core.status()['groups'][0]['lifecycle']['nodes']['/b1/x']['attempts'] == 3


def test_node_that_drifts_after_ready_degrades_then_recovers():
    w = World()
    w.boot()
    w.nodes['/b1/x'].state = core.INACTIVE
    w.run(0.5)
    w.run(10, until=lambda: w.state('boats') == mc.READY)
    assert w.state('boats') == mc.READY
    assert w.nodes['/b1/x'].received[-1] == 'activate'


def test_closing_camp_stops_the_followers_and_the_manager_finishes():
    w = World()
    w.boot()
    camp_pid = list(w.core._groups['camp'].alive)[0]
    w.core.on_process_exited('camp', camp_pid, 'camp', 0)
    assert w.core.desired('camp') == mc.DESIRED_STOPPED and w.state('camp') == mc.STOPPED
    w.run(1)
    assert w.core.desired('boats') == mc.DESIRED_STOPPED
    assert w.core.desired('scorer') == mc.DESIRED_STOPPED
    assert w.runner.stopped == ['boats', 'scorer']
    assert not w.core.finished
    w.runner.finish_stop('boats')
    w.runner.finish_stop('scorer')
    w.run(1)
    assert w.core.finished
    assert w.core.profile_actual() == 'none'


def test_closing_camp_without_scoped_stop_uses_stop_all():
    w = World(scoped=False)
    w.boot()
    camp_pid = list(w.core._groups['camp'].alive)[0]
    w.core.on_process_exited('camp', camp_pid, 'camp', 0)
    w.run(1)
    assert w.runner.stopped_all == 1 and w.runner.stopped == []
    w.runner.finish_stop('boats')
    w.runner.finish_stop('scorer')
    w.run(1)
    assert w.core.finished


def test_camp_crash_is_failed_and_does_not_cascade():
    w = World()
    w.boot()
    camp_pid = list(w.core._groups['camp'].alive)[0]
    w.core.on_process_exited('camp', camp_pid, 'camp', 139)
    w.run(1)
    assert w.state('camp') == mc.FAILED
    assert 'code 139' in w.core.status()['groups'][1]['detail']
    assert w.core.desired('boats') == mc.DESIRED_RUNNING and w.state('boats') == mc.READY


def test_clean_exit_of_one_process_among_many_is_a_note_not_a_failure():
    w = World()
    w.boot()
    extra = w.runner.launch_process('boats', 'xacro')
    w.core.on_process_exited('boats', extra, 'xacro', 0)
    w.run(1)
    assert w.state('boats') == mc.READY
    assert 'xacro exited(0)' in w.core.status()['groups'][0]['detail']


def test_nonzero_exit_of_one_process_marks_the_group_failed_and_keeps_the_first_cause():
    w = World()
    w.boot()
    extra = w.runner.launch_process('boats', 'sonar')
    w.core.on_process_exited('boats', extra, 'sonar', 1)
    other = w.runner.launch_process('boats', 'other')
    w.core.on_process_exited('boats', other, 'other', 2)
    assert w.state('boats') == mc.FAILED
    assert 'sonar' in w.core.status()['groups'][0]['detail']


def test_clean_exit_of_an_on_failure_group_is_failed_not_silent():
    data = copy.deepcopy(DATA)
    data['groups']['camp']['restart'] = 'on-failure'
    w = World(data=data)
    w.boot()
    camp_pid = list(w.core._groups['camp'].alive)[0]
    w.core.on_process_exited('camp', camp_pid, 'camp', 0)
    assert w.state('camp') == mc.FAILED
    assert w.core.desired('boats') == mc.DESIRED_RUNNING


def test_commands_set_profile_start_stop_and_acks_are_idempotent():
    w = World()
    w.boot()
    ack = w.core.handle_command({'request_id': 'r1', 'type': 'STOP', 'groups': ['camp']})
    assert ack['result'] == mc.ACCEPTED
    assert w.core.desired('camp') == mc.DESIRED_STOPPED
    assert w.core.profile_actual() == 'custom'
    again = w.core.handle_command({'request_id': 'r1', 'type': 'START', 'groups': ['camp']})
    assert again == ack and w.core.desired('camp') == mc.DESIRED_STOPPED   # repeat is a no-op
    w.core.handle_command({'request_id': 'r2', 'type': 'SET_PROFILE', 'profile': 'demo'})
    assert w.core.desired('camp') == mc.DESIRED_RUNNING and w.core.profile_actual() == 'demo'
    assert [a['request_id'] for a in w.core.status()['acks']] == ['r1', 'r2']


@pytest.mark.parametrize('message,needle', [
    ({'type': 'STOP', 'groups': ['camp']}, 'request_id'),
    ({'request_id': 'a', 'type': 'FLY'}, 'type must be'),
    ({'request_id': 'b', 'type': 'SET_PROFILE', 'profile': 'zzz'}, 'unknown profile'),
    ({'request_id': 'c', 'type': 'START', 'groups': []}, 'non-empty list'),
    ({'request_id': 'd', 'type': 'START', 'groups': ['ghost']}, 'unknown group'),
    ({'request_id': 'e', 'type': 'CLEAR_FAILURE', 'groups': ['camp']}, 'not FAILED'),
    ('nonsense', 'request_id'),
])
def test_bad_commands_are_rejected_with_a_reason(message, needle):
    w = World()
    ack = w.core.handle_command(message)
    assert ack['result'] == mc.REJECTED and needle in ack['detail']


def test_ack_ring_keeps_the_last_eight():
    w = World()
    for i in range(12):
        w.core.handle_command({'request_id': 'r%d' % i, 'type': 'START', 'groups': ['camp']})
    ids = [a['request_id'] for a in w.core.status()['acks']]
    assert ids == ['r%d' % i for i in range(4, 12)]


def test_per_group_stop_is_rejected_without_scoped_stop_but_stop_everything_works():
    w = World(scoped=False)
    w.boot()
    ack = w.core.handle_command({'request_id': 'x', 'type': 'STOP', 'groups': ['camp']})
    assert ack['result'] == mc.REJECTED and 'scoped stop' in ack['detail']
    assert w.core.desired('camp') == mc.DESIRED_RUNNING
    ack = w.core.handle_command(
        {'request_id': 'y', 'type': 'STOP', 'groups': ['boats', 'camp', 'scorer']})
    assert ack['result'] == mc.ACCEPTED
    w.run(1)
    assert w.runner.stopped_all == 1
    ack = w.core.handle_command({'request_id': 'z', 'type': 'SET_PROFILE', 'profile': 'none'})
    assert ack['result'] == mc.ACCEPTED


def test_set_profile_to_a_subset_needs_scoped_stop():
    w = World(scoped=False)
    w.boot()
    ack = w.core.handle_command({'request_id': 'p', 'type': 'SET_PROFILE', 'profile': 'boats'})
    assert ack['result'] == mc.REJECTED
    w2 = World(scoped=True)
    w2.boot()
    ack = w2.core.handle_command({'request_id': 'p', 'type': 'SET_PROFILE', 'profile': 'boats'})
    assert ack['result'] == mc.ACCEPTED
    w2.run(1)
    assert w2.runner.stopped == ['camp', 'scorer']


def test_clear_failure_stops_the_group_and_start_tries_again():
    w = World(nodes={'/b1/x': FakeNode(), '/score': FakeNode()})
    w.core.begin()
    w.run(1)
    w.runner.launch_process('boats')
    w.run(30)
    assert w.state('boats') == mc.FAILED
    ack = w.core.handle_command({'request_id': 'c', 'type': 'START', 'groups': ['boats']})
    assert ack['result'] == mc.REJECTED and 'CLEAR_FAILURE' in ack['detail']
    ack = w.core.handle_command({'request_id': 'd', 'type': 'CLEAR_FAILURE', 'groups': ['boats']})
    assert ack['result'] == mc.ACCEPTED
    w.run(0.5)
    assert w.state('boats') == mc.STOPPING
    w.runner.finish_stop('boats')
    w.nodes['/b2/x'] = FakeNode()
    w.run(1)
    assert w.state('boats') == mc.STOPPED
    w.core.handle_command({'request_id': 'e', 'type': 'START', 'groups': ['boats']})
    w.run(1)
    assert w.state('boats') == mc.STARTING


def test_stopping_a_group_suspends_its_converger():
    w = World()
    w.boot()
    conv = w.core._groups['boats'].converger
    w.core.handle_command({'request_id': 's', 'type': 'STOP', 'groups': ['boats']})
    w.run(0.5)
    assert w.state('boats') == mc.STOPPING
    sent = len(w.services.backend.sent)
    w.nodes['/b1/x'].state = core.INACTIVE          # would be repaired if still converging
    w.run(5)
    assert len(w.services.backend.sent) == sent
    assert all(r.status == core.SUSPENDED for r in conv.report())


def test_exit_flag_off_means_never_finished():
    data = copy.deepcopy(DATA)
    data['manager']['exit_when_all_stopped'] = False
    w = World(data=data)
    w.core.begin()
    w.core.handle_command({'request_id': 'n', 'type': 'SET_PROFILE', 'profile': 'none'})
    w.run(1)
    assert not w.core.finished


def test_restarting_a_group_uses_a_fresh_converger():
    w = World()
    w.boot()
    first = w.core._groups['boats'].converger
    w.core.handle_command({'request_id': 'a', 'type': 'STOP', 'groups': ['boats']})
    w.run(0.5)
    w.runner.finish_stop('boats')
    w.run(0.5)
    assert w.state('boats') == mc.STOPPED
    w.core.handle_command({'request_id': 'b', 'type': 'START', 'groups': ['boats']})
    w.run(0.5)
    assert w.state('boats') == mc.STARTING
    assert w.core._groups['boats'].converger is not first


def test_a_launch_that_cannot_be_injected_fails_the_group_with_the_reason():
    w = World()
    original = w.runner.start

    def refuse(spec):
        if spec.name == 'boats':
            raise FileNotFoundError('boats has no launch file b.py')
        original(spec)
    w.runner.start = refuse
    w.core.begin()
    w.run(1)
    assert w.state('boats') == mc.FAILED
    assert 'cannot start: boats has no launch file' in w.core.status()['groups'][0]['detail']


def test_a_stopped_group_reports_no_lifecycle_nodes_and_its_clients_are_forgotten():
    w = World()
    w.boot()
    w.core.handle_command({'request_id': 'q', 'type': 'STOP', 'groups': ['boats']})
    w.run(0.5)
    w.runner.finish_stop('boats')
    w.run(0.5)
    entry = [g for g in w.core.status()['groups'] if g['name'] == 'boats'][0]
    assert entry['state'] == mc.STOPPED and entry['lifecycle']['nodes'] == {}
    assert sorted(w.services.forgotten) == ['/b1/x', '/b2/x']


def test_the_runner_is_told_when_a_group_has_stopped_so_it_can_drop_its_handlers():
    w = World()
    w.boot()
    w.core.handle_command({'request_id': 'k', 'type': 'STOP', 'groups': ['boats']})
    w.run(0.5)
    w.runner.finish_stop('boats')
    w.run(0.5)
    assert w.runner.cleaned == ['boats']


def test_exits_during_a_shutdown_are_not_failures():
    w = World()
    w.boot()
    w.core.on_shutdown()
    for pid in list(w.core._groups['boats'].alive):
        w.core.on_process_exited('boats', pid, 'x', -2)
    for pid in list(w.core._groups['scorer'].alive):
        w.core.on_process_exited('scorer', pid, 'x', 0)
    w.run(0.5)
    assert w.state('boats') != mc.FAILED and w.state('scorer') != mc.FAILED
