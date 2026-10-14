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
The manager as a process: real LaunchService, real rclpy, fake lifecycle nodes.

Runs on a private ROS_DOMAIN_ID. The fake "boats" lose a ``change_state`` reply, as in the
bug record, and the manager must still bring them to ``active``; a second group that exits
cleanly stands in for the operator closing CAMP and must stop the rest.
"""

import json
import os
import signal
import subprocess
import sys
import time

from launch_manager_proto import lifecycle_core as core
from launch_manager_proto import lifecycle_rclpy
from launch_manager_proto.cli import format_status
import pytest
import rclpy
from rclpy_support import private_domain
from std_msgs.msg import String
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE_ROOT = os.path.dirname(HERE)
FIXTURES = os.path.join(HERE, 'fixtures')


def config_text(token, closer_seconds=8, scoped_extra=None):
    groups = {
        'fakes': {
            'launch': {'path': os.path.join(FIXTURES, 'fake_boats_launch.py')},
            'arguments': {'token': {'type': 'string', 'default': token}},
            'follows': ['closer'],
            'lifecycle': {'match': '^/fb._%s/' % token, 'expect': 3},
            'ready': {'timeout': 60},
        },
        'closer': {
            'launch': {'path': os.path.join(FIXTURES, 'closer_launch.py')},
            'arguments': {'seconds': {'type': 'int', 'default': closer_seconds}},
            'requires': ['fakes'], 'restart': 'never',
        },
    }
    return yaml.safe_dump({
        'manager': {'name': 'lmp_%s' % token, 'default_profile': 'all',
                    'exit_when_all_stopped': True, 'status_period': 0.5,
                    'converge': {'settle': 0.3, 'reply_timeout': 1.5,
                                 'backoff': [0.3, 0.5], 'poll_period': 0.2}},
        'groups': groups,
        'profiles': {'all': ['fakes', 'closer'], 'fakes': ['fakes'], 'none': []},
    })


class Harness:
    """One manager process, its configuration, log and fake-node cleanup."""

    def __init__(self, tmp_path, token, **kwargs):
        self.token = token
        self.config = tmp_path / 'manager.yaml'
        self.config.write_text(config_text(token, **kwargs))
        self.log = tmp_path / 'manager.log'
        self.env = dict(os.environ)
        self.env['PYTHONPATH'] = os.pathsep.join(
            [PACKAGE_ROOT, HERE, self.env.get('PYTHONPATH', '')])
        self.proc = None
        self.snapshot = None

    def start(self):
        self.proc = subprocess.Popen(
            [sys.executable, '-m', 'launch_manager_proto.cli', 'manager', '--config',
             str(self.config)], env=self.env, stdout=open(self.log, 'w'),
            stderr=subprocess.STDOUT, start_new_session=True)

    def leftovers(self):
        """Return pids (other than this test) whose command line carries our token."""
        found = []
        needle = ('_%s' % self.token).encode()
        for entry in os.listdir('/proc'):
            if not entry.isdigit() or int(entry) == os.getpid():
                continue
            try:
                with open('/proc/%s/cmdline' % entry, 'rb') as f:
                    if needle in f.read() and b'fake_lifecycle_node' in open(
                            '/proc/%s/cmdline' % entry, 'rb').read():
                        found.append(int(entry))
            except OSError:
                continue
        return found

    def cleanup(self):
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGINT)
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
        for pid in self.leftovers():
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def text(self):
        return self.log.read_text() if self.log.exists() else ''


@pytest.fixture(scope='module', autouse=True)
def ros():
    private_domain()
    rclpy.init()
    yield
    rclpy.shutdown()


class Watcher:
    """Collect the manager's status snapshots."""

    def __init__(self, name):
        self.node = rclpy.create_node('lmp_watch_%s' % name)
        self.latest = None
        self.history = []
        self.node.create_subscription(String, '/%s/status' % name, self._on, 10)
        self.command = self.node.create_publisher(String, '/%s/command' % name, 10)

    def _on(self, message):
        self.latest = json.loads(message.data)
        self.history.append(self.latest)

    def wait(self, predicate, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            rclpy.spin_once(self.node, timeout_sec=0.1)
            if self.latest is not None and predicate(self.latest):
                return True
        return False

    def send(self, request_id, kind, timeout=20, **fields):
        """Publish a command until its ack shows up in a snapshot; return the ack."""
        message = String(data=json.dumps({'request_id': request_id, 'type': kind, **fields}))
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            acks = [a for a in (self.latest or {}).get('acks', [])
                    if a['request_id'] == request_id]
            if acks:
                return acks[0]
            self.command.publish(message)
            self.wait(lambda s: False, 0.4)
        raise AssertionError('no ack for %s' % request_id)

    def group(self, name):
        return [g for g in self.latest['groups'] if g['name'] == name][0]

    def close(self):
        self.node.destroy_node()


def test_lost_reply_demo_reaches_ready_then_closing_stops_everything(tmp_path):
    harness = Harness(tmp_path, 'a1', closer_seconds=15)
    watcher = Watcher('lmp_a1')
    try:
        harness.start()
        assert watcher.wait(lambda s: watcher.group('fakes')['state'] == 'READY', 90), \
            (watcher.latest and format_status(watcher.latest), harness.text())
        nodes = watcher.group('fakes')['lifecycle']['nodes']
        assert len(nodes) == 3 and all(n['state'] == core.ACTIVE for n in nodes.values())
        # the closer group only starts once the fakes are READY (requires)
        assert watcher.wait(lambda s: watcher.group('closer')['state'] in ('STARTING', 'READY'),
                            30)
        # the operator closes "CAMP": the closer exits cleanly, everything else stops
        assert harness.proc.wait(timeout=90) == 0, harness.text()
        assert watcher.history[-1]['profile_actual'] in ('all', 'none', 'custom')
        assert harness.leftovers() == [], harness.text()
        assert 'follows closer, which closed' in harness.text()
    finally:
        watcher.close()
        harness.cleanup()


def test_set_profile_command_is_acknowledged_in_status(tmp_path):
    harness = Harness(tmp_path, 'a2', closer_seconds=300)
    watcher = Watcher('lmp_a2')
    try:
        harness.start()
        assert watcher.wait(lambda s: watcher.group('fakes')['state'] == 'READY', 90), \
            harness.text()
        # an unknown profile is rejected, visibly
        message = String(data=json.dumps(
            {'request_id': 'rq1', 'type': 'SET_PROFILE', 'profile': 'bogus'}))
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not any(
                a['request_id'] == 'rq1' for a in (watcher.latest or {}).get('acks', [])):
            watcher.command.publish(message)
            watcher.wait(lambda s: False, 0.5)
        ack = [a for a in watcher.latest['acks'] if a['request_id'] == 'rq1'][0]
        assert ack['result'] == 'REJECTED' and 'unknown profile' in ack['detail']
    finally:
        watcher.close()
        harness.cleanup()


def test_scoped_stop_and_restart_of_one_group(tmp_path):
    """Stop one group without touching the other, then bring it back (the spike's proof)."""
    harness = Harness(tmp_path, 'a5', closer_seconds=600)
    watcher = Watcher('lmp_a5')
    try:
        harness.start()
        assert watcher.wait(lambda s: watcher.group('closer')['state'] == 'READY', 90), \
            harness.text()
        assert len(harness.leftovers()) == 3
        # stop only the closer: the profile 'fakes' runs just the fakes
        assert watcher.send('s1', 'SET_PROFILE', profile='fakes')['result'] == 'ACCEPTED'
        assert watcher.wait(lambda s: watcher.group('closer')['state'] == 'STOPPED', 40), \
            harness.text()
        assert watcher.group('fakes')['state'] == 'READY' and len(harness.leftovers()) == 3
        assert watcher.latest['profile_actual'] == 'fakes'
        assert harness.proc.poll() is None            # the manager did not exit
        # bring it back
        assert watcher.send('s2', 'START', groups=['closer'])['result'] == 'ACCEPTED'
        assert watcher.wait(lambda s: watcher.group('closer')['state'] == 'READY', 40)
        # stop the fakes: their processes go, the closer notices it is no longer supported
        assert watcher.send('s3', 'STOP', groups=['fakes'])['result'] == 'ACCEPTED'
        assert watcher.wait(lambda s: watcher.group('fakes')['state'] == 'STOPPED', 40)
        assert harness.leftovers() == []
        assert watcher.wait(lambda s: watcher.group('closer')['state'] == 'DEGRADED', 20)
        # and start them again: a fresh set of processes converges despite the lost replies
        assert watcher.send('s4', 'START', groups=['fakes'])['result'] == 'ACCEPTED'
        assert watcher.wait(lambda s: watcher.group('fakes')['state'] == 'READY', 60), \
            harness.text()
        assert len(harness.leftovers()) == 3
        assert watcher.wait(lambda s: watcher.group('closer')['state'] == 'READY', 20)
    finally:
        watcher.close()
        harness.cleanup()


def test_guard_converges_a_launch_that_loses_replies(tmp_path):
    """The standalone guard fixes the same race for a launch nobody manages."""
    token = 'a3'
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join([PACKAGE_ROOT, HERE, env.get('PYTHONPATH', '')])
    launch = subprocess.Popen(
        ['ros2', 'launch', os.path.join(FIXTURES, 'fake_boats_launch.py'), 'token:=' + token],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        guard = subprocess.run(
            [sys.executable, '-m', 'launch_manager_proto.cli', 'converge', '--match',
             '^/fb._%s/' % token, '--expect', '3', '--timeout', '90', '--settle', '0.5'],
            env=env, capture_output=True, text=True, timeout=120)
        assert guard.returncode == 0, guard.stdout + guard.stderr
        assert '3 lifecycle node(s) on target active' in guard.stdout
    finally:
        os.killpg(launch.pid, signal.SIGINT)
        try:
            launch.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(launch.pid, signal.SIGKILL)


def test_guard_reports_and_fails_when_a_node_never_appears(tmp_path):
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join([PACKAGE_ROOT, HERE, env.get('PYTHONPATH', '')])
    guard = subprocess.run(
        [sys.executable, '-m', 'launch_manager_proto.cli', 'converge', '--match',
         '^/nothing_here/', '--expect', '1', '--timeout', '4'],
        env=env, capture_output=True, text=True, timeout=60)
    assert guard.returncode == 1
    assert 'did not converge' in guard.stdout and 'saw 0 of 1' in guard.stdout


def test_status_cli_prints_a_snapshot(tmp_path):
    harness = Harness(tmp_path, 'a4', closer_seconds=300)
    watcher = Watcher('lmp_a4')
    try:
        harness.start()
        assert watcher.wait(lambda s: watcher.group('fakes')['state'] == 'READY', 90), \
            harness.text()
        out = subprocess.run(
            [sys.executable, '-m', 'launch_manager_proto.cli', 'status', '--manager', 'lmp_a4'],
            env=harness.env, capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr
        assert 'fakes' in out.stdout and 'READY' in out.stdout
        assert lifecycle_rclpy.state_name(3) == core.ACTIVE
    finally:
        watcher.close()
        harness.cleanup()
