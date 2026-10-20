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
Start the whole demo under the launch manager: the one command.

``ros2 run marine_simulation demo_manager.py`` runs the ``demo`` profile: the boats, CAMP on the
demo's own settings, the target-area publisher, the coverage scorer and, once CAMP is up, the
window placement. ``--profile headless`` leaves CAMP and the placement out. The manager converges
every boat's lifecycle nodes to active, so a lost ``change_state`` reply (issue #96) no longer
leaves a boat dead, and closing CAMP stops everything and ends this process. CAMP comes back
with the window and map view it saved when it last closed; ``--camp-fresh`` discards them for a
start (the fitted view is only the default of a first start). rqt is imported from the shipped
perspective file on a first start and with ``--rqt-fresh``, and comes back as it was after.
``ros2 run launch_manager_proto launch_manager_proto status`` shows what it is doing.
``scripts/run_demo.sh`` is the helper's command; it finds this machine's files and calls this.

Everything that would make the display wrong is refused before anything starts, with the
reason, as ``THE DEMO DID NOT START: ...`` and exit status 2: another demo running, a CAMP
already open, a missing or unusable file, a session the windows cannot be placed in.

The boat names come from the roster only: the manager configuration
(``config/demo_manager.yaml``) is written with placeholders that this script fills in.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Sequence

from ament_index_python.packages import get_package_share_directory, PackageNotFoundError
from launch_manager_proto.config import ArgumentSpec
from marine_simulation import demo_support
from marine_simulation import roster
import yaml

# Lifecycle nodes each boat runs (counted from a live run of demo_boats_launch.py). The
# manager calls the boats READY only once it has seen this many per boat, so a node that
# never appeared is reported ("N of M expected lifecycle nodes seen") instead of ignored.
MIN_LIFECYCLE_NODES_PER_BOAT = 9


def boats_regex(names: Sequence[str]) -> str:
    """Return the alternation matching the namespaces of these boats."""
    return '|'.join(re.escape(n) for n in names)


def scorer_template_path() -> str:
    """Return the scorer package's example parameter file, the template of the real ones."""
    return os.path.join(get_package_share_directory('coverage_assessment'),
                        'config', 'coverage_assessment.yaml')


def scorer_parameters(boats: Sequence, template: dict = None) -> dict:
    """
    Return the coverage_assessment parameters scoring these boats' CUBE grids.

    The scorer's ``map_frame`` is the first boat's map frame (the boats publish
    ``earth -> <boat>/map``, never a plain ``map``) and its tide frames are that boat's too.
    """
    if template is None:
        with open(scorer_template_path()) as f:
            template = yaml.safe_load(f)
    return demo_support.scorer_parameters(template, boats)


def boats_launch_arguments(spec, items: Sequence[str], declared: Sequence[str] = None) -> Dict:
    """
    Return the extra ``name:=value`` arguments for the ``boats`` group, checked.

    A name must be declared by ``demo_boats_launch.py`` (read from the launch file itself) and
    must not be one the configuration already gives the group (``--boats``, ``--roster``,
    ``--no-joysticks``/``--joysticks`` and the lifecycle guard are set by the manager).
    """
    if not items:
        return {}
    if 'boats' not in spec.groups:
        raise ValueError('this configuration has no boats group to give %s to' % ' '.join(items))
    if declared is None:
        declared = demo_support.declared_launch_arguments()
    return demo_support.parse_launch_arguments(
        items, declared, list(spec.groups['boats'].arguments))


def substitutions(names: Sequence[str], boats_argument: str, enable_joysticks: bool,
                  scorer_params: str, roster_file: str, joystick_config: str,
                  layout_config: str, target_file: str,
                  camp_fresh: bool = False, rqt_fresh: bool = False) -> Dict[str, str]:
    """Return the values for the ``${placeholders}`` of ``demo_manager.yaml``."""
    return {
        'boats': boats_argument,
        'boats_regex': boats_regex(names),
        'boats_expect': str(MIN_LIFECYCLE_NODES_PER_BOAT * len(names)),
        'enable_joysticks': 'true' if enable_joysticks else 'false',
        'scorer_params': scorer_params,
        'roster_file': roster_file,
        'joystick_config': joystick_config,
        'layout_config': layout_config,
        'target_file': target_file,
        'camp_fresh': 'true' if camp_fresh else 'false',
        'rqt_fresh': 'true' if rqt_fresh else 'false',
    }


def check_layout_tool(layout: str, tool: str = None) -> None:
    """
    Raise ``ValueError`` with the reason unless the windows can be placed on this session.

    Runs ``place_windows.py --check`` (X11, ``wmctrl``, a layout that parses, the monitors it
    names connected), the same check ``run_demo.sh`` makes, from beside this script.
    """
    tool = tool or os.environ.get('DEMO_PLACE_WINDOWS') or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'place_windows.py')
    try:
        result = subprocess.run([tool, '--check', '--layout', layout], capture_output=True,
                                text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError('cannot run the window placement check %s: %s' % (tool, error)) \
            from None
    if result.returncode != 0:
        reason = (result.stderr or result.stdout).strip() or 'exit status %d' % result.returncode
        raise ValueError('the windows cannot be laid out: %s'
                         % reason.replace('place_windows: ', '', 1))


def check_target_tool(target: str, tool: str = None) -> None:
    """
    Raise ``ValueError`` with the reason unless ``target`` is a CAMP file the publisher accepts.

    Runs ``publish_survey_area.py --check``: without it a malformed file would only show as a
    publisher node that appears in the graph, publishes nothing and exits.
    """
    tool = tool or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'publish_survey_area.py')
    try:
        result = subprocess.run([tool, '--check', target], capture_output=True, text=True,
                                timeout=60)
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError('cannot run the target area check %s: %s' % (tool, error)) from None
    if result.returncode != 0:
        reason = (result.stderr or result.stdout).strip() or 'exit status %d' % result.returncode
        raise ValueError('the target area file cannot be used: %s'
                         % reason.replace('publish_survey_area: ', '', 1))


def preflight(members: Sequence[str], enable_joysticks: bool, joystick_config: str,
              layout_config: str, target_file: str, check_layout=None, camp_pids=None,
              check_target=None) -> None:
    """
    Refuse, with the reason, what would make the groups of ``members`` start wrong.

    Raises ``ValueError``. Run before any group starts, so a missing file, a running CAMP or
    a session without X11 stops the demo plainly instead of leaving a half-started display.
    """
    if 'boats' in members and enable_joysticks:
        demo_support.require_file(joystick_config, 'joystick file')
    if 'camp' in members or 'target_area' in members:
        demo_support.require_file(target_file, 'target area file')
        (check_target or check_target_tool)(target_file)
    if 'camp' in members:
        pids = (camp_pids or demo_support.running_camp_pids)()
        if pids:
            raise ValueError('CAMP is already running (process %s); close it first so the demo '
                             'starts its own CAMP' % ', '.join(map(str, pids)))
    if 'layout' in members:
        demo_support.require_file(layout_config, 'layout file')
        (check_layout or check_layout_tool)(layout_config)


def non_empty(text: str) -> str:
    """Return ``text``; an empty value is refused, never replaced by a default."""
    if not text.strip():
        raise argparse.ArgumentTypeError('needs a value, not an empty string')
    return text


def build_parser() -> argparse.ArgumentParser:
    # no abbreviations: run_demo.sh reads the full option names to decide which files it needs
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--profile', type=non_empty,
                        help='profile to start (default: the configured one)')
    parser.add_argument('--boats', default='',
                        help='comma separated boat names (default: the whole roster)')
    parser.add_argument('--roster', type=non_empty,
                        help='roster file (default: the installed one)')
    parser.add_argument('--config', type=non_empty,
                        help='manager configuration (default: the installed one)')
    parser.add_argument('--no-joysticks', action='store_true',
                        help='do not start the joy_linux drivers (pads not plugged in)')
    parser.add_argument('--joysticks', type=non_empty, metavar='FILE',
                        help="this computer's gamepad bindings (default: the installed example)")
    layout = parser.add_mutually_exclusive_group()
    layout.add_argument('--layout', type=non_empty, metavar='FILE',
                        help="this computer's window layout (default: the installed example)")
    layout.add_argument('--no-layout', action='store_true',
                        help='do not move the windows')
    parser.add_argument('--target', type=non_empty, metavar='FILE',
                        help='saved CAMP file holding the target survey area (default: the '
                             'installed demo polygon); CAMP opens it and the scorer uses it')
    parser.add_argument('--camp-fresh', action='store_true',
                        help='discard the window and map view CAMP saved when it last closed '
                             '(a first start); otherwise CAMP comes back as it was closed')
    parser.add_argument('--rqt-fresh', action='store_true',
                        help='import the shipped rqt perspective again (Survey Coverage and one '
                             'Ping Profile per boat), replacing the one rqt stored (a first '
                             'start); otherwise rqt comes back as it was closed')
    parser.add_argument('launch_args', nargs='*', metavar='name:=value',
                        help='more arguments of the boats launch (demo_boats_launch.py), '
                             'for example tide_speed_factor:=1; the ones the options above '
                             'set are refused')
    return parser


def main(argv: List[str] = None) -> int:
    args = build_parser().parse_args(argv)
    from launch_manager_proto.config import ConfigError, load_config
    from launch_manager_proto.manager import run_manager

    share = get_package_share_directory('marine_simulation')
    roster_file = os.path.abspath(os.path.expanduser(
        args.roster or os.path.join(share, 'config', 'demo_roster.yaml')))
    try:
        boats = roster.select_boats(roster.load_roster(roster_file), args.boats)
    except (ValueError, OSError, yaml.YAMLError) as error:
        print('roster problem: %s' % error, file=sys.stderr)
        return 2
    names = [b.name for b in boats]
    joysticks = os.path.abspath(os.path.expanduser(
        args.joysticks or os.path.join(share, 'config', 'demo_joysticks.yaml')))
    layout = os.path.abspath(os.path.expanduser(
        args.layout or os.path.join(share, 'config', 'demo_layout.yaml')))
    target = os.path.abspath(os.path.expanduser(
        args.target or os.path.join(share, 'config', 'demo_target_polygon_camp.json')))
    try:
        demo_support.acquire_demo_lock(demo_support.state_dir())
    except (ValueError, OSError) as error:
        print('THE DEMO DID NOT START: %s' % error, file=sys.stderr)
        return 2
    state_dir = tempfile.mkdtemp(prefix='demo_manager_')
    try:
        scorer_path = os.path.join(state_dir, 'scorer_params.yaml')
        try:
            parameters = scorer_parameters(boats)
            with open(scorer_path, 'w') as f:
                yaml.safe_dump(parameters, f)
        except (ValueError, OSError, yaml.YAMLError, PackageNotFoundError, ImportError) as error:
            print('THE DEMO DID NOT START: cannot build the scorer parameters: %s: %s'
                  % (type(error).__name__, error), file=sys.stderr)
            return 2
        try:
            spec = load_config(
                args.config or os.path.join(share, 'config', 'demo_manager.yaml'),
                substitutions(names, args.boats, not args.no_joysticks, scorer_path,
                              roster_file, joysticks, layout, target, args.camp_fresh,
                              args.rqt_fresh))
        except ConfigError as error:
            print('configuration error:\n%s' % error, file=sys.stderr)
            return 2
        try:
            extra = boats_launch_arguments(spec, args.launch_args)
        except ValueError as error:
            print('THE DEMO DID NOT START: %s' % error, file=sys.stderr)
            return 2
        for name, value in extra.items():
            spec.groups['boats'].arguments[name] = ArgumentSpec(name, 'string', value)
        if args.profile:
            if args.profile not in spec.profiles:
                print('unknown profile %r; the configuration has %s'
                      % (args.profile, ', '.join(sorted(spec.profiles))), file=sys.stderr)
                return 2
            spec.default_profile = args.profile
        if args.no_layout:
            for name, members in spec.profiles.items():
                spec.profiles[name] = [g for g in members if g != 'layout']
        try:
            preflight(spec.profiles[spec.default_profile], not args.no_joysticks, joysticks,
                      layout, target)
        except ValueError as error:
            print('THE DEMO DID NOT START: %s' % error, file=sys.stderr)
            return 2
        return run_manager(spec)
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
