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
Command line: run the manager, print its status, send it commands, or just converge.

``launch_manager_proto manager --config demo.yaml``
``launch_manager_proto status``                       one snapshot as a table (``--json``)
``launch_manager_proto command start camp``          START / STOP / CLEAR_FAILURE / set-profile
``launch_manager_proto converge --match '^/a/'``     the convergence loop alone, as a guard
"""

import argparse
import json
import sys
import time
from typing import Dict, List, Optional
import uuid

from launch_manager_proto import lifecycle_core as core
from launch_manager_proto.config import ConfigError, load_config
from launch_manager_proto.lifecycle_rclpy import discover_lifecycle_nodes, RclpyBackend
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


def format_status(snapshot: dict) -> str:
    """Render a status snapshot as the table the helper reads."""
    lines = ['manager %s   profile %s   (profiles: %s)' % (
        snapshot.get('manager'), snapshot.get('profile_actual'),
        ', '.join(snapshot.get('profiles_available', [])))]
    width = max([len(g['name']) for g in snapshot.get('groups', [])] + [5])
    for group in snapshot.get('groups', []):
        lines.append('  %-*s  %-8s -> %-8s  %s' % (
            width, group['name'], group['state'], group['desired'], group.get('detail', '')))
        life = group.get('lifecycle')
        if life:
            for name, info in sorted(life['nodes'].items()):
                mark = ' ' if info['status'] == core.ON_TARGET else '!'
                lines.append('   %s %s: %s (%s)%s' % (
                    mark, name, info['state'], info['status'],
                    ' - ' + info['reason'] if info['reason'] else ''))
    for ack in snapshot.get('acks', [])[-3:]:
        lines.append('  ack %s %s %s' % (ack['request_id'], ack['result'], ack['detail']))
    return '\n'.join(lines)


def _find_status_topics(node: Node, manager: Optional[str]) -> List[str]:
    if manager:
        return ['/%s/status' % manager.strip('/')]
    return sorted(name for name, types in node.get_topic_names_and_types()
                  if name.endswith('/status') and 'std_msgs/msg/String' in types)


def _read_snapshot(node: Node, topics: List[str], timeout: float,
                   want_ack: Optional[str] = None) -> Optional[dict]:
    latest: Dict[str, dict] = {}

    def make(topic):
        def on_message(message):
            try:
                data = json.loads(message.data)
            except ValueError:
                return
            if isinstance(data, dict) and 'groups' in data and 'manager' in data:
                latest[topic] = data
        return on_message

    subs = [node.create_subscription(String, t, make(t), 10) for t in topics]
    end = time.monotonic() + timeout
    result = None
    while time.monotonic() < end and result is None:
        rclpy.spin_once(node, timeout_sec=0.1)
        for data in latest.values():
            if want_ack is None or any(a['request_id'] == want_ack for a in data['acks']):
                result = data
                break
    for sub in subs:
        node.destroy_subscription(sub)
    return result


def cmd_status(args) -> int:
    rclpy.init()
    node = Node('launch_manager_proto_status')
    try:
        time.sleep(0.5)
        topics = _find_status_topics(node, args.manager)
        if not topics:
            print('no manager status topic found (is a manager running on this ROS_DOMAIN_ID?)',
                  file=sys.stderr)
            return 2
        snapshot = _read_snapshot(node, topics, args.timeout)
        if snapshot is None:
            print('no status received within %.0f s' % args.timeout, file=sys.stderr)
            return 2
        print(json.dumps(snapshot, indent=2, sort_keys=True) if args.json
              else format_status(snapshot))
        return 0
    finally:
        node.destroy_node()
        rclpy.shutdown()


def cmd_command(args) -> int:
    message = {'request_id': args.request_id or uuid.uuid4().hex[:12], 'type': args.verb}
    if args.verb == 'SET_PROFILE':
        message['profile'] = args.names[0]
    else:
        message['groups'] = args.names
    rclpy.init()
    node = Node('launch_manager_proto_command')
    try:
        time.sleep(0.5)
        topics = _find_status_topics(node, args.manager)
        if len(topics) != 1:
            print('pick a manager with --manager (found: %s)' % (', '.join(topics) or 'none'),
                  file=sys.stderr)
            return 2
        publisher = node.create_publisher(String, topics[0][:-len('status')] + 'command', 10)
        # Re-send until the request is acknowledged in a status snapshot (a topic can drop it).
        end = time.monotonic() + args.timeout
        snapshot = None
        while snapshot is None and time.monotonic() < end:
            publisher.publish(String(data=json.dumps(message)))
            snapshot = _read_snapshot(node, topics, 1.5, want_ack=message['request_id'])
        if snapshot is None:
            print('no acknowledgement of %s within %.0f s' % (message['request_id'],
                                                              args.timeout), file=sys.stderr)
            return 2
        ack = [a for a in snapshot['acks'] if a['request_id'] == message['request_id']][-1]
        print('%s %s' % (ack['result'], ack['detail']))
        return 0 if ack['result'] == 'ACCEPTED' else 1
    finally:
        node.destroy_node()
        rclpy.shutdown()


def cmd_manager(args) -> int:
    from launch_manager_proto.manager import run_manager
    substitutions = {}
    for item in args.set or []:
        key, _, value = item.partition('=')
        if not key or not _:
            print('--set wants KEY=VALUE, got %r' % item, file=sys.stderr)
            return 2
        substitutions[key] = value
    try:
        spec = load_config(args.config, substitutions)
    except ConfigError as error:
        print('configuration error in %s:\n%s' % (args.config, error), file=sys.stderr)
        return 2
    return run_manager(spec)


def format_report(reports) -> str:
    """Render per-node convergence reports, one line each."""
    return '\n'.join('  %-40s %-12s %-10s %s' % (
        r.name, r.state, r.status, ('attempts %d, ' % r.attempts if r.attempts else '') +
        (r.reason or r.last_result)) for r in reports)


def cmd_converge(args) -> int:
    """Run the convergence loop alone: the post-launch guard (fixes the lost-reply race)."""
    rclpy.init()
    node = Node('launch_manager_proto_guard')
    backend = RclpyBackend(node, query_timeout=2.0)
    config = core.ConvergeConfig(settle=args.settle)
    converger = core.LifecycleConverger(
        backend, time.monotonic, config, target=args.target,
        log=lambda text: print('[launch_manager_proto] %s' % text, flush=True))
    known = set()
    end = time.monotonic() + args.timeout
    last_print = 0.0
    try:
        while time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=0.05)
            backend.expire()
            now = time.monotonic()
            if now - last_print >= 2.0:
                last_print = now
                for name in discover_lifecycle_nodes(node, args.match):
                    if name not in known:
                        known.add(name)
                        converger.add_node(name)
            converger.tick()
            if len(known) >= args.expect and converger.all_on_target():
                print('[launch_manager_proto] %d lifecycle node(s) on target %s' % (
                    len(known), args.target), flush=True)
                return 0
            if converger.any_failed() and len(known) >= args.expect and all(
                    r.status in (core.ON_TARGET, core.FAILED, core.FINALIZED_STATUS)
                    for r in converger.report()):
                break
        print('[launch_manager_proto] did not converge to %s (saw %d of %d expected node(s)):'
              '\n%s' % (args.target, len(known), args.expect, format_report(converger.report())),
              flush=True)
        return 1
    finally:
        backend.close()
        node.destroy_node()
        rclpy.shutdown()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='launch_manager_proto', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='which', required=True)

    manager = sub.add_parser('manager', help='run the manager')
    manager.add_argument('--config', required=True)
    manager.add_argument('--set', action='append', metavar='KEY=VALUE',
                         help='value for a ${KEY} placeholder in the configuration')
    manager.set_defaults(run=cmd_manager)

    status = sub.add_parser('status', help='print one status snapshot')
    status.add_argument('--manager', help='manager name (default: scan for status topics)')
    status.add_argument('--timeout', type=float, default=5.0)
    status.add_argument('--json', action='store_true')
    status.set_defaults(run=cmd_status)

    command = sub.add_parser('command', help='send a command and wait for its acknowledgement')
    command.add_argument('--manager')
    command.add_argument('--timeout', type=float, default=10.0)
    command.add_argument('--request-id')
    verbs = command.add_subparsers(dest='verb_name', required=True)
    for verb, argname in (('set-profile', 'profile'), ('start', 'groups'),
                          ('stop', 'groups'), ('clear-failure', 'groups')):
        p = verbs.add_parser(verb)
        p.add_argument('names', nargs=1 if argname == 'profile' else '+', metavar=argname)
        p.set_defaults(verb=verb.upper().replace('-', '_'), run=cmd_command)

    converge = sub.add_parser('converge', help='converge lifecycle nodes, no groups')
    converge.add_argument('--match', default=None, help='regular expression on node names')
    converge.add_argument('--target', choices=core.TARGETS, default=core.ACTIVE)
    converge.add_argument('--expect', type=int, default=1,
                          help='nodes that must be seen before success counts')
    converge.add_argument('--timeout', type=float, default=120.0)
    converge.add_argument('--settle', type=float, default=2.0)
    converge.set_defaults(run=cmd_converge)
    return parser


def main(argv=None) -> int:
    """Entry point of the ``launch_manager_proto`` console script."""
    args = build_parser().parse_args(argv)
    return args.run(args)


if __name__ == '__main__':
    sys.exit(main())
