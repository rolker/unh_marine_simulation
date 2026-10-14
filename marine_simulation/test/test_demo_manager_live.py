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
Host-only: the demo's boats under the launch manager, checked end to end.

Needs the geoid and VDatum grids under ``~/data/world/datum``, takes a minute or two and
starts about forty processes, so it only runs when ``ROS_DOMAIN_ID`` is set to a private
domain above 100 (set it on purpose; this test never picks one for you) and otherwise skips
with that reason. It starts ``demo_manager.py`` with the ``boats`` profile for two boats
and no joysticks, waits for the manager to call the boats READY, and runs the existing
``demo_boats_selftest.py`` against them. No CAMP and no GUI is started.
"""

import json
import os
import pathlib
import signal
import subprocess
import time

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


def test_boats_under_the_manager_reach_ready_and_pass_the_selftest(tmp_path):
    log = tmp_path / 'manager.log'
    manager = subprocess.Popen(
        ['ros2', 'run', 'marine_simulation', 'demo_manager.py', '--profile', 'boats',
         '--boats', BOATS, '--no-joysticks'],
        stdout=open(log, 'w'), stderr=subprocess.STDOUT, start_new_session=True)
    rclpy.init()
    node = rclpy.create_node('demo_manager_live_test')
    latest = {}
    node.create_subscription(
        String, '/demo_manager/status',
        lambda m: latest.update(json.loads(m.data)), 10)
    try:
        end = time.monotonic() + 240
        ready = False
        while time.monotonic() < end and manager.poll() is None:
            rclpy.spin_once(node, timeout_sec=0.2)
            groups = {g['name']: g for g in latest.get('groups', [])}
            if groups.get('boats', {}).get('state') == 'READY':
                ready = True
                break
        assert ready, (json.dumps(latest, indent=1), log.read_text()[-3000:])
        nodes = groups['boats']['lifecycle']['nodes']
        assert len(nodes) >= 10, sorted(nodes)
        assert all(n['state'] == 'active' for n in nodes.values()), nodes
        selftest = subprocess.run(
            ['ros2', 'run', 'marine_simulation', 'demo_boats_selftest.py', '--boats', BOATS],
            capture_output=True, text=True, timeout=400)
        assert selftest.returncode == 0, selftest.stdout[-4000:] + selftest.stderr[-2000:]
    finally:
        node.destroy_node()
        rclpy.shutdown()
        if manager.poll() is None:
            os.killpg(manager.pid, signal.SIGINT)
            try:
                manager.wait(timeout=60)
            except subprocess.TimeoutExpired:
                os.killpg(manager.pid, signal.SIGKILL)
