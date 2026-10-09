#!/usr/bin/env python3
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
Check a running multi-boat simulation for cross-wired boats.

Three checks, each a plain function over data collected from the ROS graph so it
can be tested without ROS:

- no two nodes share a fully qualified name,
- every TF child frame has exactly one parent (``earth`` may parent many),
- no boat's nodes publish another boat's topics, and no topic outside the boats'
  namespaces is published by the nodes of two different boats.

Run against a running ``demo_boats_launch.py``::

    ros2 run marine_simulation check_multi_boat_graph.py

Exit status 0 when every check passes, 1 when one fails.
"""

import argparse
import collections
import os
import sys
import time
from typing import Dict, Iterable, List, Sequence, Set, Tuple

import yaml

# Topics every vehicle legitimately publishes to (the single shared bus or the
# global fleet list). A new entry here should be a deliberate decision.
SHARED_TOPICS = frozenset({
    '/marine/platforms', '/tf', '/tf_static', '/rosout', '/parameter_events', '/clock',
})


def fq_name(name: str, namespace: str) -> str:
    return '/' + '/'.join(p for p in (namespace + '/' + name).split('/') if p)


def duplicate_node_names(nodes: Iterable[Tuple[str, str]]) -> List[str]:
    """
    Return fully qualified node names that appear more than once.

    ``nodes`` is ``(name, namespace)`` pairs, as ``get_node_names_and_namespaces``
    returns them.
    """
    counts = collections.Counter(fq_name(n, ns) for n, ns in nodes)
    return sorted(name for name, count in counts.items() if count > 1)


def multi_parent_frames(edges: Iterable[Tuple[str, str]]) -> Dict[str, Set[str]]:
    """
    Return the TF child frames that have more than one parent.

    ``edges`` is ``(parent, child)`` pairs. A frame with several children (such as
    ``earth``) is fine; a frame with several parents is two boats fighting over it.
    """
    parents = collections.defaultdict(set)
    for parent, child in edges:
        parents[child].add(parent)
    return {c: p for c, p in sorted(parents.items()) if len(p) > 1}


def _boat_of(path: str, boats: Sequence[str]) -> str:
    first = path.strip('/').split('/')[0] if path.strip('/') else ''
    return first if first in boats else ''


def cross_boat_publishers(
        publishers: Dict[str, Sequence[Tuple[str, str]]],
        boats: Sequence[str],
        shared_topics: Iterable[str] = SHARED_TOPICS) -> List[str]:
    """
    Return a message per topic that more than one boat publishes to.

    ``publishers`` maps a topic to its publishers' ``(node name, namespace)``.
    A node belongs to a boat when its namespace starts with the boat's name; a
    node in no boat's namespace (``asv_sim``, TF listeners) belongs to nobody
    and may publish anywhere.

    - A topic inside boat X's namespace must not be published by boat Y's nodes.
    - A topic outside every boat's namespace must not be published by the nodes
      of two boats, unless it is in ``shared_topics``.
    """
    shared = set(shared_topics)
    problems = []
    for topic, pubs in sorted(publishers.items()):
        if topic in shared:
            continue
        owner = _boat_of(topic, boats)
        publishing = sorted({_boat_of(ns, boats) for _, ns in pubs} - {''})
        if owner:
            wrong = [b for b in publishing if b != owner]
            if wrong:
                problems.append('%s belongs to %s but is published by %s'
                                % (topic, owner, ', '.join(wrong)))
        elif len(publishing) > 1:
            problems.append('%s is outside the boat namespaces but published by %s'
                            % (topic, ', '.join(publishing)))
    return problems


def boats_from_roster(path: str) -> List[str]:
    """Read the boat names from the demo roster file."""
    with open(path) as f:
        return [b['name'] for b in yaml.safe_load(f)['boats']]


def default_roster_path() -> str:
    """Return the installed roster path."""
    from ament_index_python.packages import get_package_share_directory
    return os.path.join(
        get_package_share_directory('marine_simulation'), 'config', 'demo_roster.yaml')


class GraphSampler:
    """Collect nodes, topic publishers and TF edges from the live graph."""

    def __init__(self, node):
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
        from tf2_msgs.msg import TFMessage
        self.node = node
        self.edges = set()
        node.create_subscription(TFMessage, '/tf', self._on_tf, 100)
        node.create_subscription(
            TFMessage, '/tf_static', self._on_tf,
            QoSProfile(depth=100, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                       reliability=ReliabilityPolicy.RELIABLE))

    def _on_tf(self, msg):
        for t in msg.transforms:
            self.edges.add((t.header.frame_id.lstrip('/'), t.child_frame_id.lstrip('/')))

    def nodes(self) -> List[Tuple[str, str]]:
        return [(n, ns) for n, ns in self.node.get_node_names_and_namespaces()]

    def publishers(self) -> Dict[str, List[Tuple[str, str]]]:
        result = {}
        for topic, _ in self.node.get_topic_names_and_types():
            infos = self.node.get_publishers_info_by_topic(topic)
            if infos:
                result[topic] = [(i.node_name, i.node_namespace) for i in infos]
        return result


def run_checks(sampler: GraphSampler, boats: Sequence[str], tf_seconds: float) -> List[str]:
    """Spin the sampler for ``tf_seconds`` and return the problems found."""
    import rclpy
    deadline = time.monotonic() + tf_seconds
    while time.monotonic() < deadline:
        rclpy.spin_once(sampler.node, timeout_sec=0.1)
    problems = []
    for name in duplicate_node_names(sampler.nodes()):
        problems.append('duplicate node name %s' % name)
    for child, parents in multi_parent_frames(sampler.edges).items():
        problems.append('TF frame %s has several parents: %s'
                        % (child, ', '.join(sorted(parents))))
    problems.extend(cross_boat_publishers(sampler.publishers(), boats))
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--roster', help='demo roster file (default: the installed one)')
    parser.add_argument('--boats', help='comma separated boat names (overrides --roster)')
    parser.add_argument('--tf-seconds', type=float, default=5.0,
                        help='how long to sample /tf (default 5)')
    args = parser.parse_args(argv)

    import rclpy
    boats = (args.boats.split(',') if args.boats
             else boats_from_roster(args.roster or default_roster_path()))
    rclpy.init()
    node = rclpy.create_node('check_multi_boat_graph')
    try:
        problems = run_checks(GraphSampler(node), boats, args.tf_seconds)
    finally:
        node.destroy_node()
        rclpy.shutdown()
    for p in problems:
        print('FAIL', p)
    print('%d problem(s) for boats %s' % (len(problems), ', '.join(boats)))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
