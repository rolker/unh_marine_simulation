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

"""Unit tests for the pure checks in scripts/check_multi_boat_graph.py."""

import importlib.util
import pathlib

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / 'scripts' / 'check_multi_boat_graph.py'
_spec = importlib.util.spec_from_file_location('check_multi_boat_graph', SCRIPT)
graph = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(graph)

# Synthetic boat names: the checks must not depend on the demo roster.
BOATS = ['one', 'two']


def test_duplicate_node_names_are_found_across_namespace_spellings():
    nodes = [('asv_helm', '/one'), ('asv_helm', '/two'), ('mbes_sim', '/one'),
             ('mbes_sim', 'one'), ('asv_sim', '/')]
    assert graph.duplicate_node_names(nodes) == ['/one/mbes_sim']


def test_no_duplicates_when_every_name_is_distinct():
    assert graph.duplicate_node_names([('a', '/'), ('a', '/one'), ('b', '/')]) == []


def test_frame_with_two_parents_is_reported_but_shared_parent_is_not():
    edges = [('earth', 'one/map'), ('earth', 'two/map'), ('one/map', 'one/odom'),
             ('one/odom', 'shared'), ('two/odom', 'shared')]
    assert graph.multi_parent_frames(edges) == {'shared': {'one/odom', 'two/odom'}}


def test_the_same_edge_seen_twice_is_one_parent():
    assert graph.multi_parent_frames([('a', 'b'), ('a', 'b')]) == {}


def test_boat_publishing_into_another_boats_namespace_is_reported():
    pubs = {'/one/odom': [('mru_transform', '/one')],
            '/two/odom': [('mru_transform', '/two'), ('stray', '/one/sensors')]}
    assert len(graph.cross_boat_publishers(pubs, BOATS)) == 1


def test_global_nodes_may_publish_into_boat_namespaces():
    pubs = {'/one/sensors/nav/position': [('asv_sim', '/')]}
    assert graph.cross_boat_publishers(pubs, BOATS) == []


def test_unprefixed_topic_published_by_two_boats_is_reported_unless_shared():
    pubs = {'/odom': [('a', '/one'), ('a', '/two')],
            '/marine/platforms': [('platform_sender', '/one'), ('platform_sender', '/two')]}
    problems = graph.cross_boat_publishers(pubs, BOATS)
    assert len(problems) == 1 and problems[0].startswith('/odom ')


def test_unprefixed_topic_published_by_a_single_boat_is_reported():
    pubs = {'/odom': [('a', '/one')], '/tf': [('rsp', '/one')]}
    problems = graph.cross_boat_publishers(pubs, BOATS)
    assert len(problems) == 1 and problems[0].startswith('/odom ')


def test_root_namespace_publishers_are_ignored_by_design():
    pubs = {'/asv_sim/environment/tide_level': [('asv_sim', '/')],
            '/diagnostics': [('joy_node', '/')]}
    assert graph.cross_boat_publishers(pubs, BOATS) == []


# -- Fast DDS discovery server (issue 116) -------------------------------------------------

def test_through_a_server_the_checker_becomes_a_super_client():
    environ = {'ROS_DISCOVERY_SERVER': '127.0.0.1:11853'}
    assert graph.enable_super_client(environ) is True
    assert environ['ROS_SUPER_CLIENT'] == 'TRUE'


def test_without_a_server_nothing_is_set():
    environ = {}
    assert graph.enable_super_client(environ) is False
    assert environ == {}


def test_a_conflicting_super_client_setting_is_replaced_not_trusted():
    # an incomplete graph would read as a broken demo
    environ = {'ROS_DISCOVERY_SERVER': '127.0.0.1:11853', 'ROS_SUPER_CLIENT': 'FALSE'}
    graph.enable_super_client(environ)
    assert environ['ROS_SUPER_CLIENT'] == 'TRUE'


def test_what_the_checker_starts_is_never_a_super_client():
    environ = {'ROS_DISCOVERY_SERVER': 'x:1', 'ROS_SUPER_CLIENT': 'TRUE', 'PATH': '/bin'}
    assert graph.without_super_client(environ) == {'ROS_DISCOVERY_SERVER': 'x:1',
                                                   'PATH': '/bin'}
    assert environ['ROS_SUPER_CLIENT'] == 'TRUE'        # a copy: the caller's own is untouched
