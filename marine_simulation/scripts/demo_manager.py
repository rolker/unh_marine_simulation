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
Start the demo under the launch manager.

``ros2 run marine_simulation demo_manager.py`` runs the ``demo`` profile (the boats, CAMP and
the scorer); ``--profile headless`` leaves CAMP out. The manager converges every boat's
lifecycle nodes to active, so a lost ``change_state`` reply (issue #96) no longer leaves a
boat dead, and closing CAMP stops everything. ``ros2 run launch_manager_proto
launch_manager_proto status`` shows what it is doing.

The boat names come from the roster only: the manager configuration
(``config/demo_manager.yaml``) is written with placeholders that this script fills in.
"""

import argparse
import importlib.util
import os
import re
import shutil
import sys
import tempfile
from typing import Dict, List, Sequence

from ament_index_python.packages import get_package_share_directory
import yaml

# Lifecycle nodes each boat runs (counted from a live run of demo_boats_launch.py). The
# manager calls the boats READY only once it has seen this many per boat, so a node that
# never appeared is reported ("N of M expected lifecycle nodes seen") instead of ignored.
MIN_LIFECYCLE_NODES_PER_BOAT = 9


def _load_boats_launch(share: str):
    """Load ``demo_boats_launch.py`` (a launch file is not an importable package)."""
    path = os.path.join(share, 'launch', 'demo_boats_launch.py')
    spec = importlib.util.spec_from_file_location('demo_boats_launch', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def boats_regex(names: Sequence[str]) -> str:
    """Return the alternation matching the namespaces of these boats."""
    return '|'.join(re.escape(n) for n in names)


def _load_demo_launch(share: str):
    """Load ``demo_launch.py``, the one place that knows how the scorer is configured."""
    path = os.path.join(share, 'launch', 'demo_launch.py')
    spec = importlib.util.spec_from_file_location('demo_launch', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scorer_template_path() -> str:
    """Return the scorer package's example parameter file, the template of the real ones."""
    return os.path.join(get_package_share_directory('coverage_assessment'),
                        'config', 'coverage_assessment.yaml')


def scorer_parameters(boats: Sequence, share: str = None, template: dict = None) -> dict:
    """
    Return the coverage_assessment parameters scoring these boats' CUBE grids.

    The content is ``demo_launch.scorer_parameters`` (also used by the one-launch demo), so
    the scorer's ``map_frame`` is the first boat's map frame (the boats publish
    ``earth -> <boat>/map``, never a plain ``map``) and its tide frames are that boat's too.
    """
    demo_launch = _load_demo_launch(share or get_package_share_directory('marine_simulation'))
    if template is None:
        with open(scorer_template_path()) as f:
            template = yaml.safe_load(f)
    return demo_launch.scorer_parameters(template, boats)


def substitutions(names: Sequence[str], boats_argument: str, enable_joysticks: bool,
                  scorer_params: str, roster_file: str) -> Dict[str, str]:
    """Return the values for the ``${placeholders}`` of ``demo_manager.yaml``."""
    return {
        'boats': boats_argument,
        'boats_regex': boats_regex(names),
        'boats_expect': str(MIN_LIFECYCLE_NODES_PER_BOAT * len(names)),
        'enable_joysticks': 'true' if enable_joysticks else 'false',
        'scorer_params': scorer_params,
        'roster_file': roster_file,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--profile', help='profile to start (default: the configured one)')
    parser.add_argument('--boats', default='',
                        help='comma separated boat names (default: the whole roster)')
    parser.add_argument('--roster', help='roster file (default: the installed one)')
    parser.add_argument('--config', help='manager configuration (default: the installed one)')
    parser.add_argument('--no-joysticks', action='store_true',
                        help='do not start the joy_linux drivers (pads not plugged in)')
    return parser


def main(argv: List[str] = None) -> int:
    args = build_parser().parse_args(argv)
    from launch_manager_proto.config import ConfigError, load_config
    from launch_manager_proto.manager import run_manager

    share = get_package_share_directory('marine_simulation')
    launch = _load_boats_launch(share)
    roster_path = args.roster or os.path.join(share, 'config', 'demo_roster.yaml')
    try:
        boats = launch.select_boats(launch.load_roster(roster_path), args.boats)
    except ValueError as error:
        print('roster problem: %s' % error, file=sys.stderr)
        return 2
    names = [b.name for b in boats]
    state_dir = tempfile.mkdtemp(prefix='demo_manager_')
    try:
        scorer_path = os.path.join(state_dir, 'scorer_params.yaml')
        with open(scorer_path, 'w') as f:
            yaml.safe_dump(scorer_parameters(boats, share), f)
        try:
            spec = load_config(
                args.config or os.path.join(share, 'config', 'demo_manager.yaml'),
                substitutions(names, args.boats, not args.no_joysticks, scorer_path,
                              roster_path))
        except ConfigError as error:
            print('configuration error:\n%s' % error, file=sys.stderr)
            return 2
        if args.profile:
            if args.profile not in spec.profiles:
                print('unknown profile %r; the configuration has %s'
                      % (args.profile, ', '.join(sorted(spec.profiles))), file=sys.stderr)
                return 2
            spec.default_profile = args.profile
        return run_manager(spec)
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
