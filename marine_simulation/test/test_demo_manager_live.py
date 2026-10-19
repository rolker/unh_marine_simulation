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
Host-only: the demo's boats under the launch manager, end to end.

Needs the geoid and VDatum grids under ``~/data/world/datum``, takes a minute or two and
starts about forty processes, so it only runs when ``ROS_DOMAIN_ID`` is set to a private
domain above 100 (set it on purpose; this test never picks one for you) and otherwise skips
with that reason.

It starts ``demo_manager.py`` with the ``headless`` profile (boats and scorer, no CAMP) for
two boats and no joysticks, and waits for the manager to call the boats READY. Then it runs
the existing ``demo_boats_selftest.py`` against them, stops and restarts the boats group (a
restart used to kill every Python lifecycle node: stale launch_ros handlers sent them a
second, invalid transition) and finally interrupts the manager, which must take everything
down. No CAMP and no GUI is started.
"""

import json
import os
import pathlib
import signal
import subprocess
import sys
import time

from ament_index_python.packages import get_package_prefix
import pytest
import rclpy
from std_msgs.msg import String

DATUM = pathlib.Path(os.path.expanduser('~/data/world/datum'))
DOMAIN = os.environ.get('ROS_DOMAIN_ID', '')
BOATS = 'bluefin,clownfish'

pytestmark = [
    pytest.mark.skipif(not (DATUM / 'geoid').is_dir() or not (DATUM / 'vdatum').is_dir(),
                       reason='datum grids missing under ~/data/world/datum'),
    pytest.mark.skipif(not DOMAIN.isdigit() or int(DOMAIN) <= 100 or int(DOMAIN) in (42, 88),
                       reason='set ROS_DOMAIN_ID to a private domain above 100 to run this'),
]


def test_boats_under_the_manager_reach_ready_restart_and_stop_cleanly(tmp_path):
    log = tmp_path / 'manager.log'
    # the script itself, not `ros2 run` (whose wrapper process would take the SIGINT)
    script = os.path.join(get_package_prefix('marine_simulation'), 'lib', 'marine_simulation',
                          'demo_manager.py')
    manager = subprocess.Popen(
        [sys.executable, script, '--profile', 'headless', '--boats', BOATS, '--no-joysticks'],
        stdout=open(log, 'w'), stderr=subprocess.STDOUT, start_new_session=True)
    rclpy.init()
    node = rclpy.create_node('demo_manager_live_test')
    latest = {}
    node.create_subscription(
        String, '/demo_manager/status',
        lambda m: latest.update(json.loads(m.data)), 10)
    commands = node.create_publisher(String, '/demo_manager/command', 10)

    def group(name):
        return {g['name']: g for g in latest.get('groups', [])}[name]

    def boats():
        return group('boats')

    def wait_for(predicate, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end and manager.poll() is None:
            rclpy.spin_once(node, timeout_sec=0.2)
            if latest and predicate():
                return True
        return False

    def command(request_id, kind, **fields):
        message = String(data=json.dumps({'request_id': request_id, 'type': kind, **fields}))
        end = time.monotonic() + 20
        while time.monotonic() < end:
            if any(a['request_id'] == request_id for a in latest.get('acks', [])):
                return
            commands.publish(message)
            wait_for(lambda: False, 0.5)
        raise AssertionError('no ack for %s' % request_id)

    try:
        assert wait_for(lambda: boats()['state'] == 'READY', 240), \
            (json.dumps(latest, indent=1), log.read_text()[-3000:])
        # the scorer waits for the target-area publisher, so both come up behind the boats
        assert wait_for(lambda: group('scorer')['state'] == 'READY', 120), \
            (json.dumps(latest, indent=1), log.read_text()[-3000:])
        assert group('target_area')['state'] == 'READY', group('target_area')
        nodes = boats()['lifecycle']['nodes']
        assert len(nodes) >= 10, sorted(nodes)
        assert all(n['state'] == 'active' for n in nodes.values()), nodes
        selftest = subprocess.run(
            ['ros2', 'run', 'marine_simulation', 'demo_boats_selftest.py', '--boats', BOATS],
            capture_output=True, text=True, timeout=400)
        assert selftest.returncode == 0, selftest.stdout[-4000:] + selftest.stderr[-2000:]

        command('live-stop', 'STOP', groups=['boats'])
        assert wait_for(lambda: boats()['state'] == 'STOPPED', 120), log.read_text()[-3000:]
        assert boats()['lifecycle']['nodes'] == {}
        command('live-start', 'START', groups=['boats'])
        assert wait_for(lambda: boats()['state'] == 'READY', 240), \
            (json.dumps(latest, indent=1), log.read_text()[-3000:])
        assert all(n['state'] == 'active' for n in boats()['lifecycle']['nodes'].values())
        dead = [line for line in log.read_text().splitlines() if 'process has died' in line
                and 'asv_sim' not in line]       # asv_sim exits -2 on every SIGINT
        assert dead == [], dead

        os.kill(manager.pid, signal.SIGINT)               # the manager alone, not its group
        assert manager.wait(timeout=90) is not None
        end = time.monotonic() + 8.0                      # let the graph forget the nodes
        while time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=0.2)
        remaining = sorted(
            ns.rstrip('/') + '/' + name for name, ns in node.get_node_names_and_namespaces()
            if ns.startswith(('/bluefin', '/clownfish')) or name in (
                'asv_sim', 'coverage_assessment', 'demo_manager', 'survey_area_publisher'))
        assert remaining == [], remaining
    finally:
        node.destroy_node()
        rclpy.shutdown()
        if manager.poll() is None:
            os.killpg(manager.pid, signal.SIGKILL)
