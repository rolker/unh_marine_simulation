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

"""The pieces of the command line that need no ROS graph."""

from launch_manager_proto import cli
from launch_manager_proto import lifecycle_core as core
import pytest

SNAPSHOT = {
    'schema': 1, 'manager': 'm', 'profile_actual': 'demo', 'profiles_available': ['demo'],
    'acks': [{'request_id': 'r', 'result': 'ACCEPTED', 'detail': 'stop camp'}],
    'groups': [
        {'name': 'boats', 'desired': 'RUNNING', 'state': 'FAILED',
         'detail': 'lifecycle node /a/x FAILED: configure failed 5 times',
         'lifecycle': {'target': 'active', 'nodes': {
             '/a/x': {'state': 'inactive', 'status': 'FAILED', 'attempts': 5,
                      'last_result': '', 'reason': 'configure failed 5 times'},
             '/a/y': {'state': 'active', 'status': 'ON_TARGET', 'attempts': 0,
                      'last_result': '', 'reason': ''}}}},
        {'name': 'camp', 'desired': 'RUNNING', 'state': 'BLOCKED',
         'detail': 'waiting for boats (FAILED)'},
    ],
}


@pytest.mark.parametrize('data,expected', [
    (SNAPSHOT, True),
    ({k: v for k, v in SNAPSHOT.items() if k != 'acks'}, False),
    ({**SNAPSHOT, 'groups': 'x'}, False),
    ({**SNAPSHOT, 'manager': None}, False),
    ([], False), (None, False), ('{}', False),
])
def test_only_a_complete_snapshot_is_accepted(data, expected):
    assert cli.is_snapshot(data) is expected


def test_the_status_table_names_the_failed_node_and_marks_what_is_not_on_target():
    text = cli.format_status(SNAPSHOT)
    assert 'boats' in text and 'FAILED' in text
    assert '! /a/x: inactive (FAILED) - configure failed 5 times' in text
    assert '  /a/y: active (ON_TARGET)' in text
    assert 'camp' in text and 'waiting for boats (FAILED)' in text
    assert 'ack r ACCEPTED stop camp' in text


def test_the_node_report_lists_one_line_per_node():
    reports = [core.NodeReport('/a', 'active', 'inactive', core.FAILED, attempts=5,
                               reason='refused'),
               core.NodeReport('/b', 'active', 'active', core.ON_TARGET)]
    lines = cli.format_report(reports).splitlines()
    assert len(lines) == 2 and 'attempts 5, refused' in lines[0]


def test_parser_knows_every_documented_command():
    parser = cli.build_parser()
    assert parser.parse_args(['manager', '--config', 'x', '--set', 'a=b']).which == 'manager'
    assert parser.parse_args(['status', '--json']).json is True
    args = parser.parse_args(['command', 'set-profile', 'headless'])
    assert args.verb == 'SET_PROFILE' and args.names == ['headless']
    args = parser.parse_args(['command', '--manager', 'm', 'clear-failure', 'a', 'b'])
    assert args.verb == 'CLEAR_FAILURE' and args.names == ['a', 'b']
    args = parser.parse_args(['converge', '--match', '^/a/', '--expect', '9'])
    assert args.expect == 9 and args.target == 'active'
    with pytest.raises(SystemExit):
        parser.parse_args(['command', 'restart', 'x'])
