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
import json
import os
import threading
import time
from typing import Callable, Deque, Dict, List, Optional, Set, Tuple

from ament_index_python.packages import get_package_share_directory
import launch
from launch.actions import (GroupAction, IncludeLaunchDescription, RegisterEventHandler,
                            SetEnvironmentVariable)
from launch.event_handlers import OnProcessExit, OnProcessStart
from launch.events.process import ShutdownProcess
from launch.events.process.process_matchers import matches_pid
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch_manager_proto import manager_core as mc
from launch_manager_proto.config import GroupSpec, launch_argument_text, ManagerSpec
from launch_manager_proto.lifecycle_core import LifecycleConverger
from launch_manager_proto.lifecycle_rclpy import discover_lifecycle_nodes, RclpyBackend
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from ros2launch_session import LaunchSession
from std_msgs.msg import String

GROUP_ENV = 'LAUNCH_MANAGER_GROUP'
TICK_PERIOD = 0.1


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
        self.events: Deque[Tuple[str, str, int, str, Optional[int]]] = deque()
        self._release = threading.Event()
        self._threads: List[threading.Thread] = []
        self._lock = threading.Lock()
        self._pids: Dict[str, Set[int]] = {}
        self._targeted: Set[int] = set()
        self.supports_scoped_stop = True

    def base_description(self) -> launch.LaunchDescription:
        """Return the handlers that watch every process of every group."""
        def started(event, context):
            group = (event.env or {}).get(GROUP_ENV)
            if group:
                with self._lock:
                    self._pids.setdefault(group, set()).add(event.pid)
                self.events.append(('started', group, event.pid, event.process_name, None))

        def exited(event, context):
            group = (event.env or {}).get(GROUP_ENV)
            if group:
                with self._lock:
                    self._pids.get(group, set()).discard(event.pid)
                    self._targeted.discard(event.pid)
                self.events.append(
                    ('exited', group, event.pid, event.process_name, event.returncode))

        return launch.LaunchDescription([
            RegisterEventHandler(OnProcessStart(on_start=started)),
            RegisterEventHandler(OnProcessExit(on_exit=exited)),
        ])

    def start(self, spec: GroupSpec) -> None:
        description = group_description(spec)

        def hold() -> None:
            with LaunchSession.from_service(self._service, description):
                self._release.wait()

        thread = threading.Thread(target=hold, name='group-%s' % spec.name, daemon=True)
        thread.start()
        self._threads.append(thread)

    def stop(self, name: str, timeout: float) -> None:
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
            self._service.emit_event(ShutdownProcess(process_matcher=matches_pid(pid)))

    def stop_all(self) -> None:
        self._service.shutdown()

    def close(self) -> None:
        """Let the group threads leave their contexts (the service is going down anyway)."""
        self._release.set()
        for thread in self._threads:
            thread.join(timeout=5.0)


class RclpyServices(mc.Services):
    """Graph access for the core, on the manager's node."""

    def __init__(self, node: Node, backend: RclpyBackend, spec: ManagerSpec,
                 log: Callable[[str], None]):
        self._node = node
        self._backend = backend
        self._spec = spec
        self._log = log

    def discover(self, pattern: str) -> List[str]:
        return discover_lifecycle_nodes(self._node, pattern)

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


class ManagerNode(Node):
    """Publishes ``~/status``, takes ``~/command`` and ticks the core."""

    def __init__(self, spec: ManagerSpec, runner: LaunchRunner,
                 on_finished: Callable[[], None]):
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
            parsed = json.loads(message.data)
        except ValueError:
            parsed = None
        ack = self.core.handle_command(parsed)
        if not ack['request_id']:
            self.get_logger().warning('ignored a command without a usable request_id')
        self._publish(force=True)

    def _drain(self) -> None:
        events = self._runner.events
        while events:
            kind, group, pid, name, code = events.popleft()
            if kind == 'started':
                self.core.on_process_started(group, pid, name)
            else:
                self.core.on_process_exited(group, pid, name, code)

    def _tick(self) -> None:
        self._drain()
        self.core.tick()
        self._publish()
        if self.core.finished and not self._finished:
            self._finished = True
            self.get_logger().info('every group is stopped: the manager is done')
            self._on_finished()

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
    rclpy.init()
    node = ManagerNode(spec, runner, on_finished=service.shutdown)
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    spinner = threading.Thread(target=executor.spin, name='rclpy', daemon=True)
    spinner.start()
    try:
        return service.run(shutdown_when_idle=False)
    finally:
        runner.close()
        executor.shutdown()
        spinner.join(timeout=5.0)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
