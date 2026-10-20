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
The running manager: the core on an rclpy node, its groups on one shared LaunchService.

Threads: the main thread runs the single ``LaunchService`` (``asserts main thread``, one per
process, ``shutdown_when_idle=False`` so an idle manager is not shut down from under itself).
One rclpy executor thread runs everything else, single threaded, so the core needs no locks.
Process start/exit events arrive on the launch thread and cross to the executor thread through
a queue.

Each group is injected into the shared service with ``LaunchSession.from_service``. That is a
context manager whose exit shuts the whole shared service down, so the context of each group is
held open by a dedicated thread until the manager itself exits.
"""

from collections import deque
import faulthandler
import json
import os
import signal
import threading
import time
from typing import Callable, Deque, Dict, List, Optional, Set, Tuple

from ament_index_python.packages import get_package_share_directory
import launch
from launch.actions import (GroupAction, IncludeLaunchDescription, RegisterEventHandler,
                            SetEnvironmentVariable)
from launch.event_handlers import OnProcessExit, OnProcessStart, OnShutdown
from launch.events.process import ShutdownProcess
from launch.events.process.process_matchers import matches_pid
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch_manager_proto import manager_core as mc
from launch_manager_proto.config import GroupSpec, launch_argument_text, ManagerSpec
from launch_manager_proto.lifecycle_core import LifecycleConverger
from launch_manager_proto.lifecycle_rclpy import discover_lifecycle_nodes, RclpyBackend
from launch_ros.events.lifecycle import ChangeState
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.signals import SignalHandlerOptions
from ros2launch_session import LaunchSession
from std_msgs.msg import String

LOG = launch.logging.get_logger('launch_manager_proto')
GROUP_ENV = 'LAUNCH_MANAGER_GROUP'
TICK_PERIOD = 0.1


class _GroupSession(LaunchSession):
    """
    ``LaunchSession.from_service`` without the output and process collectors.

    ``ros2launch_session`` wraps every injected description in handlers that keep every line
    of output of every process, and every process event, in lists that are never trimmed.
    That is right for a test that lives for minutes; a manager runs for days, and each start
    of each group would add another unbounded copy. The manager tracks what it needs itself.
    (A ``capture_output=False`` option belongs in ros2launch_session.)
    """

    def _wrap_launch_description(self, launch_description):
        return launch.LaunchDescription([
            IncludeLaunchDescription(
                launch.LaunchDescriptionSource(launch_description=launch_description))])


def shutdown_if_running(service: launch.LaunchService) -> bool:
    """
    Shut the launch service down; return False (and do nothing) if its loop is not running yet.

    ``LaunchService.shutdown()`` silently does nothing before ``run()`` has started its loop,
    so a caller that needs the shutdown to have taken effect has to ask.
    """
    if service.context.asyncio_loop is None:
        return False
    service.shutdown()
    return True


def _has_group_tag(pid: int, group: str) -> bool:
    """Return whether ``pid`` still carries exactly the tag of the group it was attributed to."""
    wanted = ('%s=%s' % (GROUP_ENV, group)).encode()
    try:
        with open('/proc/%d/environ' % pid, 'rb') as f:
            return wanted in f.read().split(b'\0')
    except OSError:
        return False


def make_signal_handler(service: launch.LaunchService):
    """
    Return a signal handler that asks the launch service to shut down, without taking a lock.

    It runs on the main thread, which is also the launch loop's thread. ``shutdown()`` holds a
    lock while it waits for that loop, so a handler that called it could deadlock against the
    manager thread doing the same; queueing the ``Shutdown`` event directly cannot. It also
    works before the loop has started: the event waits in the queue and ends the run at once.
    """
    def handler(signum, frame):
        service.context.emit_event_sync(launch.events.Shutdown(
            reason='signal %s' % signal.Signals(signum).name, due_to_sigint=False))
    return handler


def _is_running(pid: int) -> bool:
    """Return whether ``pid`` is still a live process (a child that exited is reaped)."""
    try:
        done, _ = os.waitpid(pid, os.WNOHANG)
        return done == 0
    except ChildProcessError:
        pass            # not our child, or already reaped
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def will_respawn(action) -> bool:
    """
    Return whether ``launch`` is about to restart the process of this action.

    ``respawn=True`` processes come back as new processes of the same
    node name, in ``unconfigured``; that is a repair for the convergence loop, not a failure
    of the group. launch exposes no public way to ask, so the private fields are read, and
    an action that lacks them is treated as not respawning (the safe, loud direction).
    """
    try:
        respawn = getattr(action, '_ExecuteLocal__respawn')
        limit = getattr(action, '_ExecuteLocal__respawn_max_retries')
        retries = getattr(action, '_ExecuteLocal__respawn_retries')
    except AttributeError:
        return False
    return respawn is True and (limit < 0 or retries < limit)


def launch_file_path(package: str, file: str) -> str:
    """Return the installed path of ``<package>/launch/<file>``; raise if it is not there."""
    path = os.path.join(get_package_share_directory(package), 'launch', file)
    if not os.path.isfile(path):
        raise FileNotFoundError('%s has no launch file %s' % (package, file))
    return path


def group_description(spec: GroupSpec) -> launch.LaunchDescription:
    """
    Build the description injected for a group.

    The group's own environment tag is set in a scoped group, so every process the included
    launch file starts carries ``LAUNCH_MANAGER_GROUP=<name>`` and its start/exit events can be
    attributed without guessing from pids or names.
    """
    arguments = {name: launch_argument_text(a.default) for name, a in spec.arguments.items()}
    include = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(
            launch_file_path(spec.package, spec.file) if spec.package else spec.file),
        launch_arguments=arguments.items())
    return launch.LaunchDescription([
        GroupAction([SetEnvironmentVariable(GROUP_ENV, spec.name), include], scoped=True)])


class LaunchRunner(mc.Runner):
    """Runs groups on a shared ``LaunchService`` and reports process events as a queue."""

    def __init__(self, service: launch.LaunchService):
        self._service = service
        self.events: Deque[Tuple[str, str, int, str, Optional[int], bool]] = deque()
        self._releases: Dict[str, List[threading.Event]] = {}
        self._threads: List[threading.Thread] = []
        self._lock = threading.Lock()
        self._pids: Dict[str, Set[int]] = {}
        self._targeted: Set[int] = set()
        self._handlers: Dict[str, List] = {}
        self._sole_writer: Set[str] = set()
        self.suppressed = 0
        self.supports_scoped_stop = True
        self._record_handlers()

    def _record_handlers(self) -> None:
        """
        Watch the event handlers each group's launch description registers.

        Two things are done with them, both because an ``rclpy`` lifecycle node dies on a
        transition request that is invalid for its state (``Transition is not registered``
        escapes the service callback), so a node must never have two writers:

        * In a group with a ``lifecycle`` section the manager is the only writer: launch_ros's
          handler for ``ChangeState`` events is not registered, so the per-package launch
          files' autostart chains still emit their events and nobody acts on them. Left in,
          a chain that was merely slow raced the convergence loop and killed nodes.
        * Every other handler registered while a group is visited carries the group's
          environment tag, and is unregistered when the group has stopped. launch keeps a
          handler until told otherwise and launch_ros subscribes by node name, so a group
          started a second time would have its old chains answer the new processes too
          (found live: a restarted group lost its Python lifecycle nodes).
        """
        context = self._service.context
        original = context.register_event_handler
        probe = ChangeState(lifecycle_node_matcher=lambda action: True, transition_id=1)

        def is_change_state_handler(event_handler) -> bool:
            try:
                return bool(event_handler.matches(probe))
            except Exception:  # noqa: B902  an exotic handler is simply not one of ours
                return False

        def register(event_handler, append=False):
            group = context.environment.get(GROUP_ENV)
            if not group:
                return original(event_handler, append)
            if group in self._sole_writer and is_change_state_handler(event_handler):
                # The manager is the only writer of lifecycle transitions in a group that
                # has a ``lifecycle`` section. launch_ros's own handler for ChangeState
                # events is what turns the per-package launch files' autostart chains into
                # requests; rclpy lifecycle nodes die on a request that is invalid for their
                # state, so a slow chain racing the convergence loop killed them. With the
                # handler gone the chains still emit their events, and nobody acts on them.
                self.suppressed += 1
                return None
            # An OnShutdown handler outlives the group: launch_ros registers the one that
            # stops its ROS adapter thread from whichever group first needs the adapter, and
            # without it the process cannot exit.
            if not isinstance(event_handler, OnShutdown):
                with self._lock:
                    self._handlers.setdefault(group, []).append(event_handler)
            return original(event_handler, append)

        context.register_event_handler = register

    def group_stopped(self, name: str) -> None:
        """Unregister the group's event handlers (on the launch loop) now that it has stopped."""
        with self._lock:
            handlers = self._handlers.pop(name, [])
            releases = self._releases.pop(name, [])
        for event in releases:
            event.set()             # the holder thread leaves its context and ends
        context = self._service.context

        def unregister() -> None:
            for handler in handlers:
                try:
                    context.unregister_event_handler(handler)
                except ValueError:
                    pass            # already gone

        loop = context.asyncio_loop
        if loop is None:
            unregister()            # the service is not running: nothing else touches it
            return
        try:
            loop.call_soon_threadsafe(unregister)
        except RuntimeError as error:   # the loop closed under us: the service is ending
            LOG.warning('could not unregister the handlers of group %s: %s' % (name, error))

    def _on_started(self, event, context) -> None:
        group = (event.env or {}).get(GROUP_ENV)
        if group:
            with self._lock:
                self._pids.setdefault(group, set()).add(event.pid)
            self.events.append(('started', group, event.pid, event.process_name, None, False))

    def _on_exited(self, event, context) -> None:
        group = (event.env or {}).get(GROUP_ENV)
        if group:
            with self._lock:
                self._pids.get(group, set()).discard(event.pid)
                self._targeted.discard(event.pid)
            self.events.append(('exited', group, event.pid, event.process_name, event.returncode,
                                will_respawn(event.action)))

    def _on_shutdown(self, event, context) -> None:
        self.events.append(('shutdown', '', 0, '', None, False))

    def base_description(self) -> launch.LaunchDescription:
        """Return the handlers that watch every process of every group."""
        return launch.LaunchDescription([
            RegisterEventHandler(OnProcessStart(on_start=self._on_started)),
            RegisterEventHandler(OnProcessExit(on_exit=self._on_exited)),
            RegisterEventHandler(OnShutdown(on_shutdown=self._on_shutdown)),
        ])

    def start(self, spec: GroupSpec) -> None:
        description = group_description(spec)
        if spec.lifecycle is not None:
            self._sole_writer.add(spec.name)

        release = threading.Event()
        with self._lock:
            self._releases.setdefault(spec.name, []).append(release)

        def hold() -> None:
            # The context stays open until the group has stopped (or the manager exits):
            # leaving it earlier would make from_service shut the shared service down.
            with _GroupSession.from_service(self._service, description):
                release.wait()

        thread = threading.Thread(target=hold, name='group-%s' % spec.name, daemon=True)
        thread.start()
        self._threads = [t for t in self._threads if t.is_alive()] + [thread]

    def stop(self, name: str) -> None:
        """
        Stop only this group: one ``ShutdownProcess`` per attributed pid, once each.

        ``launch`` escalates SIGINT, SIGTERM, SIGKILL per process by itself. The core calls
        this every tick while the group is stopping, so a process that was still starting up
        when the stop was first requested is caught on a later call.
        """
        with self._lock:
            pids = [p for p in sorted(self._pids.get(name, ())) if p not in self._targeted]
            self._targeted.update(pids)
        for pid in pids:
            try:
                self._service.emit_event(ShutdownProcess(process_matcher=matches_pid(pid)))
            except Exception as error:  # noqa: B902  the loop may be closing; try again next tick
                LOG.warning('could not ask launch to stop pid %d: %s' % (pid, error))
                with self._lock:
                    self._targeted.discard(pid)

    def stop_all(self) -> None:
        self._service.shutdown()

    def close(self) -> None:
        """Let the group threads leave their contexts and make sure no process outlives us."""
        with self._lock:
            events = [e for group in self._releases.values() for e in group]
        for event in events:
            event.set()
        deadline = time.monotonic() + 5.0       # one budget for all, not five seconds each
        for thread in self._threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        self.terminate_leftovers()

    def terminate_leftovers(self, patience=((signal.SIGINT, 8.0), (signal.SIGTERM, 4.0),
                                            (signal.SIGKILL, 2.0))) -> List[int]:
        """
        Stop any group process still running; return the pids that needed a signal.

        ``launch`` answers SIGTERM by cancelling its run and orphaning every process ("using
        SIGTERM can result in orphaned processes"), and systemd stops a unit with SIGTERM. The
        runner knows which pids it attributed to groups, so it finishes the job itself, in
        launch's own order: SIGINT, then SIGTERM, then SIGKILL.
        """
        with self._lock:
            owner = {pid: group for group, pids in self._pids.items() for pid in pids}

        def ours(pid: int) -> bool:
            return _is_running(pid) and _has_group_tag(pid, owner[pid])

        remaining = [p for p in sorted(owner) if ours(p)]
        signalled = list(remaining)
        for sig, wait in patience:
            for pid in remaining:
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pass
            end = time.monotonic() + wait
            while remaining and time.monotonic() < end:
                time.sleep(0.1)
                remaining = [p for p in remaining if ours(p)]
            if not remaining:
                break
        return signalled


class RclpyServices(mc.Services):
    """Graph access for the core, on the manager's node."""

    def __init__(self, node: Node, backend: RclpyBackend, spec: ManagerSpec,
                 log: Callable[[str], None]):
        self._node = node
        self._backend = backend
        self._spec = spec
        self._log = log

    def discover(self, pattern: str, exclude: Optional[str] = None) -> List[str]:
        return discover_lifecycle_nodes(self._node, pattern, exclude)

    def node_visible(self, name: str) -> bool:
        for node_name, namespace in self._node.get_node_names_and_namespaces():
            full = namespace.rstrip('/') + '/' + node_name
            if full == name:
                return True
        return False

    def make_converger(self, target: str) -> LifecycleConverger:
        return LifecycleConverger(self._backend, time.monotonic, self._spec.converge,
                                  target=target, log=self._log)

    def pump(self) -> None:
        self._backend.expire()

    def forget(self, names: List[str]) -> None:
        for name in names:
            self._backend.forget(name)


class ManagerNode(Node):
    """Publishes ``~/status``, takes ``~/command`` and ticks the core."""

    def __init__(self, spec: ManagerSpec, runner: LaunchRunner,
                 on_finished: Callable[[], bool]):
        super().__init__(spec.name)
        self.spec = spec
        self._runner = runner
        self._on_finished = on_finished
        self.backend = RclpyBackend(self, query_timeout=spec.converge.query_timeout)
        self.core = mc.ManagerCore(
            spec, runner, RclpyServices(self, self.backend, spec, self._log), time.monotonic,
            self._log)
        self._status_pub = self.create_publisher(String, '~/status', 10)
        self.create_subscription(String, '~/command', self._on_command, 10)
        self._last_published = ''
        self._last_publish_time = 0.0
        self._finished = False
        self.core.begin()
        self.create_timer(TICK_PERIOD, self._tick)

    def _log(self, text: str) -> None:
        logger = self.get_logger()
        (logger.error if 'FAILED' in text else logger.info)(text)

    def _on_command(self, message: String) -> None:
        try:
            try:
                parsed = json.loads(message.data)
            except (ValueError, RecursionError):
                parsed = None
            ack = self.core.handle_command(parsed)
            if not ack['request_id']:
                self.get_logger().warning('ignored a command without a usable request_id')
            self._publish(force=True)
        except Exception as error:  # noqa: B902  one bad message must not end the executor
            self.get_logger().error('command handling failed: %r' % (error,))

    def _drain(self) -> None:
        events = self._runner.events
        while events:
            kind, group, pid, name, code, respawning = events.popleft()
            if kind == 'shutdown':
                self.core.on_shutdown()
            elif kind == 'started':
                self.core.on_process_started(group, pid, name)
            else:
                self.core.on_process_exited(group, pid, name, code, respawning)

    def _tick(self) -> None:
        try:
            self._drain()
            self.core.tick()
            self._publish()
        except Exception as error:  # noqa: B902  the next tick may succeed; never end the thread
            self.get_logger().error('tick failed: %r' % (error,))
            return
        if self.core.finished and not self._finished:
            # The launch loop may not be running yet; keep asking until the shutdown is taken.
            if self._on_finished():
                self._finished = True
                self.get_logger().info('every group is stopped: the manager is done')

    def _publish(self, force: bool = False) -> None:
        snapshot = self.core.status()
        stable = json.dumps(
            {k: ([{kk: vv for kk, vv in g.items() if kk != 'state_since'}
                  for g in v] if k == 'groups' else v) for k, v in snapshot.items()},
            sort_keys=True)
        now = time.monotonic()
        if not force and stable == self._last_published and \
                now - self._last_publish_time < self.spec.status_period:
            return
        self._last_published = stable
        self._last_publish_time = now
        message = String()
        message.data = json.dumps(snapshot, sort_keys=True)
        self._status_pub.publish(message)


def run_manager(spec: ManagerSpec) -> int:
    """Run the manager until every group has stopped or it is interrupted; return an exit code."""
    service = launch.LaunchService(noninteractive=True)
    runner = LaunchRunner(service)
    service.include_launch_description(runner.base_description())
    # rclpy's own SIGINT handler would replace launch's, and ctrl-c would then stop nothing.
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = ManagerNode(spec, runner, on_finished=lambda: shutdown_if_running(service))
    executor = SingleThreadedExecutor()
    executor.add_node(node)

    def spin() -> None:
        try:
            executor.spin()
        except Exception as error:  # noqa: B902  a dead executor means nothing is managed
            LOG.error('the manager thread died (%r): shutting down' % (error,))
            shutdown_if_running(service)

    spinner = threading.Thread(target=spin, name='rclpy', daemon=True)
    spinner.start()
    # `kill -USR1 <pid>` prints every thread's stack to stderr (a hung shutdown is diagnosable).
    faulthandler.register(signal.SIGUSR1, all_threads=True)
    # launch records a SIGTERM handler but leaves the OS disposition at its default, so a
    # plain `kill` (what systemd sends) ends the process at once and orphans every group, and
    # a closed terminal (SIGHUP) does the same. A Python-level handler makes the signal
    # arrive and queues a Shutdown event, like ctrl-c. launch's own SIGTERM handler also runs
    # and cancels the run task, so on SIGTERM the orderly stop can be cut short: whatever is
    # still running afterwards is stopped by pid in close() below.
    handler = make_signal_handler(service)
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, handler)
    try:
        return service.run(shutdown_when_idle=False)
    finally:
        runner.events.append(('shutdown', '', 0, '', None, False))   # the core must know
        runner.close()
        executor.shutdown()
        spinner.join(timeout=5.0)
        if spinner.is_alive():
            LOG.warning('the manager thread did not stop; leaving its node undestroyed')
        else:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
