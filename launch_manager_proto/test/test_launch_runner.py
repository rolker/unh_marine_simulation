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

"""The launch runner's own bookkeeping: process attribution, leftovers, group descriptions."""

import os
import signal
import subprocess
import sys
import time

import launch
from launch_manager_proto import manager
from launch_manager_proto.config import ArgumentSpec, GroupSpec
import pytest

IGNORES_EVERYTHING = (
    'import signal, time\n'
    'signal.signal(signal.SIGINT, signal.SIG_IGN)\n'
    'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
    'print("up", flush=True)\n'
    'time.sleep(60)\n')


def runner():
    return manager.LaunchRunner(launch.LaunchService(noninteractive=True))


def wait_for_up(proc):
    assert proc.stdout.readline().strip() == 'up'


def test_leftovers_that_obey_sigint_are_stopped_first():
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    run = runner()
    run._pids = {'g': {child.pid}}
    began = time.monotonic()
    assert run.terminate_leftovers(patience=((signal.SIGINT, 5.0),)) == [child.pid]
    assert time.monotonic() - began < 5.0
    with pytest.raises(ProcessLookupError):
        os.kill(child.pid, 0)


def test_leftovers_that_ignore_sigint_and_sigterm_are_killed():
    child = subprocess.Popen([sys.executable, '-c', IGNORES_EVERYTHING],
                             stdout=subprocess.PIPE, text=True)
    wait_for_up(child)
    run = runner()
    run._pids = {'g': {child.pid}}
    run.terminate_leftovers(patience=((signal.SIGINT, 0.5), (signal.SIGTERM, 0.5),
                                      (signal.SIGKILL, 3.0)))
    with pytest.raises(ProcessLookupError):
        os.kill(child.pid, 0)           # gone (the runner reaped it)


def test_no_leftovers_means_no_signals():
    run = runner()
    assert run.terminate_leftovers() == []
    done = subprocess.Popen([sys.executable, '-c', 'pass'])
    done.wait()
    run._pids = {'g': {done.pid}}
    assert run.terminate_leftovers() == []


def test_stop_targets_each_pid_once_and_forgets_exited_ones():
    run = runner()
    emitted = []
    run._service.emit_event = emitted.append
    run._pids = {'a': {11, 12}, 'b': {21}}
    run.stop('a', 5.0)
    assert len(emitted) == 2
    run.stop('a', 5.0)                  # called again on the next tick: nothing new
    assert len(emitted) == 2
    run._pids['a'].add(13)              # a process that was still starting up
    run.stop('a', 5.0)
    assert len(emitted) == 3
    assert all(type(e).__name__ == 'ShutdownProcess' for e in emitted)


def test_process_events_are_attributed_by_the_environment_tag():
    run = runner()
    assert len(run.base_description().entities) == 3

    class Event:
        """The few fields of a process event the handlers read."""

        def __init__(self, env, pid, code=None):
            self.env, self.pid, self.process_name, self.returncode = env, pid, 'n', code

    run._on_started(Event({manager.GROUP_ENV: 'boats'}, 5), None)
    run._on_started(Event({'OTHER': '1'}, 6), None)           # not ours: ignored
    run._on_started(Event(None, 7), None)                     # no environment at all
    run._on_exited(Event({manager.GROUP_ENV: 'boats'}, 5, 0), None)
    assert [e[:3] for e in run.events] == [('started', 'boats', 5), ('exited', 'boats', 5)]
    assert run._pids['boats'] == set()


def test_group_description_passes_declared_defaults_only(monkeypatch):
    monkeypatch.setattr(manager, 'launch_file_path', lambda package, file: '/x/%s' % file)
    spec = GroupSpec(
        name='g', package='p', file='f_launch.py',
        arguments={'flag': ArgumentSpec('flag', 'bool', True),
                   'n': ArgumentSpec('n', 'int', 3)})
    description = manager.group_description(spec)
    group = description.entities[0]
    names = [type(a).__name__ for a in group._GroupAction__actions]
    assert names == ['SetEnvironmentVariable', 'IncludeLaunchDescription']


def test_a_missing_launch_file_is_a_clear_error():
    with pytest.raises(Exception, match='no launch file|not found|not installed|PackageNot'):
        manager.launch_file_path('launch_manager_proto', 'no_such_launch.py')


class FakeContext:
    """Just enough of LaunchContext for the handler bookkeeping."""

    def __init__(self):
        self.environment = {}
        self.registered = []
        self.asyncio_loop = None

    def register_event_handler(self, handler, append=False):
        self.registered.append(handler)

    def unregister_event_handler(self, handler):
        self.registered.remove(handler)


def test_handlers_registered_inside_a_group_are_unregistered_when_it_stops():
    context = FakeContext()

    class Service:
        pass

    service = Service()
    service.context = context
    run = manager.LaunchRunner(service)
    context.environment[manager.GROUP_ENV] = 'boats'
    context.register_event_handler('chain-1')
    context.register_event_handler('chain-2')
    context.environment[manager.GROUP_ENV] = 'scorer'
    context.register_event_handler('scorer-chain')
    del context.environment[manager.GROUP_ENV]
    context.register_event_handler('base')                # outside any group: kept
    assert context.registered == ['chain-1', 'chain-2', 'scorer-chain', 'base']
    run.group_stopped('boats')
    assert context.registered == ['scorer-chain', 'base']
    run.group_stopped('boats')                                   # idempotent
    run.group_stopped('never-started')
    assert context.registered == ['scorer-chain', 'base']


def test_an_on_shutdown_handler_is_never_unregistered_with_its_group():
    from launch.event_handlers import OnShutdown
    context = FakeContext()

    class Service:
        pass

    service = Service()
    service.context = context
    run = manager.LaunchRunner(service)
    keep = OnShutdown(on_shutdown=lambda *a: None)       # launch_ros's adapter handler
    context.environment[manager.GROUP_ENV] = 'boats'
    context.register_event_handler(keep)
    context.register_event_handler('chain')
    run.group_stopped('boats')
    assert context.registered == [keep]
