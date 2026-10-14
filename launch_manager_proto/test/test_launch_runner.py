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


def tagged_env():
    """Return an environment carrying the group tag, as every group process has."""
    return dict(os.environ, **{manager.GROUP_ENV: 'g'})


def wait_for_up(proc):
    assert proc.stdout.readline().strip() == 'up'


def test_leftovers_that_obey_sigint_are_stopped_first():
    child = subprocess.Popen(
        [sys.executable, '-c', 'import time; print("up", flush=True); time.sleep(60)'],
        env=tagged_env(), stdout=subprocess.PIPE, text=True)
    wait_for_up(child)
    run = runner()
    run._pids = {'g': {child.pid}}
    began = time.monotonic()
    assert run.terminate_leftovers(patience=((signal.SIGINT, 5.0),)) == [child.pid]
    assert time.monotonic() - began < 5.0
    with pytest.raises(ProcessLookupError):
        os.kill(child.pid, 0)


def test_leftovers_that_ignore_sigint_and_sigterm_are_killed():
    child = subprocess.Popen([sys.executable, '-c', IGNORES_EVERYTHING],
                             stdout=subprocess.PIPE, text=True, env=tagged_env())
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
    done = subprocess.Popen([sys.executable, '-c', 'pass'], env=tagged_env())
    done.wait()
    run._pids = {'g': {done.pid}}
    assert run.terminate_leftovers() == []


def test_stop_targets_each_pid_once_and_forgets_exited_ones():
    run = runner()
    emitted = []
    run._service.emit_event = emitted.append
    run._pids = {'a': {11, 12}, 'b': {21}}
    run.stop('a')
    assert len(emitted) == 2
    run.stop('a')                  # called again on the next tick: nothing new
    assert len(emitted) == 2
    run._pids['a'].add(13)              # a process that was still starting up
    run.stop('a')
    assert len(emitted) == 3
    assert all(type(e).__name__ == 'ShutdownProcess' for e in emitted)


def test_process_events_are_attributed_by_the_environment_tag():
    run = runner()
    assert len(run.base_description().entities) == 3

    class Event:
        """The few fields of a process event the handlers read."""

        def __init__(self, env, pid, code=None):
            self.env, self.pid, self.process_name, self.returncode = env, pid, 'n', code
            self.action = object()

    run._on_started(Event({manager.GROUP_ENV: 'boats'}, 5), None)
    run._on_started(Event({'OTHER': '1'}, 6), None)           # not ours: ignored
    run._on_started(Event(None, 7), None)                     # no environment at all
    run._on_exited(Event({manager.GROUP_ENV: 'boats'}, 5, 0), None)
    assert [e[:3] for e in run.events] == [('started', 'boats', 5), ('exited', 'boats', 5)]
    assert [e[5] for e in run.events] == [False, False]
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


def test_change_state_handlers_of_a_lifecycle_group_are_not_registered():
    from launch.event_handlers import OnProcessStart
    from launch_ros.events.lifecycle import ChangeState
    context = FakeContext()

    class Service:
        pass

    service = Service()
    service.context = context
    run = manager.LaunchRunner(service)
    run._sole_writer.add('boats')                 # what start() does for a lifecycle group
    chain = launch.EventHandler(matcher=lambda event: isinstance(event, ChangeState),
                                entities=[])
    other = OnProcessStart(on_start=lambda *args: None)
    context.environment[manager.GROUP_ENV] = 'boats'
    context.register_event_handler(chain)
    context.register_event_handler(other)
    assert context.registered == [other] and run.suppressed == 1
    context.environment[manager.GROUP_ENV] = 'camp'         # no lifecycle section: untouched
    context.register_event_handler(chain)
    assert chain in context.registered and run.suppressed == 1
    del context.environment[manager.GROUP_ENV]
    context.register_event_handler(chain)                   # outside any group: untouched
    assert context.registered.count(chain) == 2


def test_start_marks_only_lifecycle_groups_as_sole_writer(monkeypatch):
    from launch_manager_proto.config import LifecycleSpec
    monkeypatch.setattr(manager, 'group_description', lambda spec: launch.LaunchDescription([]))
    context = FakeContext()

    class Service:
        pass

    service = Service()
    service.context = context
    service.emit_event = lambda event: None
    run = manager.LaunchRunner(service)
    monkeypatch.setattr(manager.LaunchSession, 'from_service',
                        lambda *args: __import__('contextlib').nullcontext())
    run.start(GroupSpec(name='boats', package=None, file='x', lifecycle=LifecycleSpec(
        nodes=['/a'])))
    run.start(GroupSpec(name='camp', package=None, file='y'))
    run.close()
    assert run._sole_writer == {'boats'}


class FakeAction:
    """An ExecuteProcess action as far as will_respawn looks at it."""

    def __init__(self, respawn, limit=-1, retries=0):
        self._ExecuteLocal__respawn = respawn
        self._ExecuteLocal__respawn_max_retries = limit
        self._ExecuteLocal__respawn_retries = retries


def test_will_respawn_reads_launchs_private_fields_and_fails_safe():
    assert manager.will_respawn(FakeAction(True)) is True
    assert manager.will_respawn(FakeAction(False)) is False
    assert manager.will_respawn(FakeAction(True, limit=3, retries=2)) is True
    assert manager.will_respawn(FakeAction(True, limit=3, retries=3)) is False
    assert manager.will_respawn(object()) is False        # no such fields: assume not
    real = launch.actions.ExecuteProcess(cmd=['true'], respawn=True)
    assert manager.will_respawn(real) is True
    assert manager.will_respawn(launch.actions.ExecuteProcess(cmd=['true'])) is False


def test_a_pid_that_no_longer_carries_the_group_tag_is_never_signalled():
    stranger = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                                env={k: v for k, v in os.environ.items()
                                     if k != manager.GROUP_ENV})
    try:
        run = runner()
        run._pids = {'g': {stranger.pid}}        # as if the pid had been recycled
        assert run.terminate_leftovers(patience=((signal.SIGKILL, 0.5),)) == []
        assert stranger.poll() is None           # still running: nobody touched it
    finally:
        stranger.kill()
        stranger.wait()


def test_shutdown_if_running_does_nothing_before_the_loop_runs():
    service = launch.LaunchService(noninteractive=True)
    assert manager.shutdown_if_running(service) is False


def test_the_group_session_keeps_no_output_or_process_collectors():
    from launch.actions import IncludeLaunchDescription, RegisterEventHandler
    service = launch.LaunchService(noninteractive=True)
    session = manager._GroupSession._create_borrowed(service)
    wrapped = session._wrap_launch_description(launch.LaunchDescription([]))
    kinds = [type(e) for e in wrapped.entities]
    assert kinds == [IncludeLaunchDescription]
    assert RegisterEventHandler not in kinds


def test_a_stopped_groups_holder_thread_ends_and_a_restart_gets_a_new_one(monkeypatch):
    import contextlib
    monkeypatch.setattr(manager, 'group_description', lambda spec: launch.LaunchDescription([]))
    log = []

    @contextlib.contextmanager
    def fake_from_service(service, description):
        log.append('enter')
        try:
            yield object()
        finally:
            log.append('exit')

    monkeypatch.setattr(manager._GroupSession, 'from_service', fake_from_service)
    context = FakeContext()

    class Service:
        pass

    service = Service()
    service.context = context
    run = manager.LaunchRunner(service)
    spec = GroupSpec(name='camp', package=None, file='x')
    run.start(spec)
    deadline = time.monotonic() + 3
    while log != ['enter'] and time.monotonic() < deadline:
        time.sleep(0.02)
    assert log == ['enter']
    run.group_stopped('camp')                  # the group has stopped: its context is released
    deadline = time.monotonic() + 3
    while log != ['enter', 'exit'] and time.monotonic() < deadline:
        time.sleep(0.02)
    assert log == ['enter', 'exit']
    run.start(spec)
    run.close()
    deadline = time.monotonic() + 3
    while len(log) < 4 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert log == ['enter', 'exit', 'enter', 'exit']


def test_a_pid_tagged_for_another_group_is_not_ours():
    other = subprocess.Popen(
        [sys.executable, '-c', 'import time; print("up", flush=True); time.sleep(60)'],
        env=dict(os.environ, **{manager.GROUP_ENV: 'other'}), stdout=subprocess.PIPE, text=True)
    try:
        wait_for_up(other)              # until it has exec'd: before that /proc shows the parent's
        assert manager._has_group_tag(other.pid, 'other') is True
        assert manager._has_group_tag(other.pid, 'g') is False
        assert manager._has_group_tag(other.pid, 'othe') is False       # exact, not a prefix
        run = runner()
        run._pids = {'g': {other.pid}}                                  # attributed to g
        assert run.terminate_leftovers(patience=((signal.SIGKILL, 0.5),)) == []
        assert other.poll() is None
    finally:
        other.kill()
        other.wait()


def test_the_signal_handler_does_not_wait_for_the_services_lock():
    import threading
    service = launch.LaunchService(noninteractive=True)
    handler = manager.make_signal_handler(service)
    lock = service._LaunchService__loop_from_run_thread_lock
    held = threading.Event()
    release = threading.Event()

    def hold():
        with lock:                     # as shutdown() does while it waits for the loop
            held.set()
            release.wait(5)

    thread = threading.Thread(target=hold)
    thread.start()
    held.wait(5)
    finished = threading.Event()
    threading.Thread(target=lambda: (handler(signal.SIGTERM, None), finished.set())).start()
    assert finished.wait(2), 'the handler blocked on the service lock'
    release.set()
    thread.join()


def test_a_signal_before_the_loop_runs_still_ends_the_run():
    service = launch.LaunchService(noninteractive=True)
    manager.make_signal_handler(service)(signal.SIGHUP, None)    # arrives during start-up
    assert service.run(shutdown_when_idle=False) == 0


def test_leaving_a_group_session_never_shuts_the_shared_service_down():
    """The property the holder threads rely on: no collectors, so no shutdown on exit."""
    calls = []

    class Service:
        """Records what the session asks of the shared service."""

        def emit_event(self, event):
            calls.append(('emit', type(event).__name__))

        def shutdown(self):
            calls.append(('shutdown',))

    with manager._GroupSession.from_service(Service(), launch.LaunchDescription([])):
        pass
    assert calls == [('emit', 'IncludeLaunchDescription')]
