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

"""Manager configuration: load a YAML file, substitute placeholders, validate everything."""

from dataclasses import dataclass, field
import math
import re
from typing import Any, Dict, List, Mapping, Optional

from launch_manager_proto import lifecycle_core as core
import yaml

RESTART_POLICIES = ('never', 'on-failure')
ARGUMENT_TYPES = ('string', 'bool', 'int', 'float')
_PLACEHOLDER = re.compile(r'\$\{([A-Za-z_]\w*)\}')
_NAME = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,63}$')
_CONVERGE_FIELDS = ('poll_period', 'query_timeout', 'reply_timeout', 'inflight_timeout',
                    'appear_timeout', 'settle', 'max_attempts')


class ConfigError(ValueError):
    """The configuration is unusable; the message lists every problem found."""


@dataclass
class ArgumentSpec:
    """A declared launch argument: a type and a default, nothing free-form."""

    name: str
    kind: str
    default: Any


@dataclass
class LifecycleSpec:
    """Which lifecycle nodes a group owns and where they should be."""

    match: Optional[str] = None
    exclude: Optional[str] = None
    nodes: List[str] = field(default_factory=list)
    expect: int = 1
    target: str = core.ACTIVE


@dataclass
class GroupSpec:
    """One launch file run as a unit."""

    name: str
    package: Optional[str]    # None: ``file`` is a path
    file: str
    arguments: Dict[str, ArgumentSpec] = field(default_factory=dict)
    requires: List[str] = field(default_factory=list)
    follows: List[str] = field(default_factory=list)
    lifecycle: Optional[LifecycleSpec] = None
    ready_nodes: List[str] = field(default_factory=list)
    ready_timeout: float = 60.0
    restart: str = 'on-failure'
    description: str = ''


@dataclass
class ManagerSpec:
    """The whole configuration."""

    name: str
    default_profile: str
    status_period: float = 1.0
    exit_when_all_stopped: bool = False
    converge: core.ConvergeConfig = field(default_factory=core.ConvergeConfig)
    groups: Dict[str, GroupSpec] = field(default_factory=dict)
    profiles: Dict[str, List[str]] = field(default_factory=dict)


def coerce_argument(spec: ArgumentSpec, text: str) -> Any:
    """Parse ``text`` as the declared type, strictly (``True`` is not a bool here)."""
    if spec.kind == 'string':
        return str(text)
    if spec.kind == 'bool':
        if text in ('true', 'false'):
            return text == 'true'
        raise ValueError('argument %s: %r is not "true" or "false"' % (spec.name, text))
    try:
        value = int(text) if spec.kind == 'int' else float(text)
    except (TypeError, ValueError):
        raise ValueError('argument %s: %r is not a valid %s' % (spec.name, text, spec.kind))
    if spec.kind == 'float' and not math.isfinite(value):
        raise ValueError('argument %s: %r is not finite' % (spec.name, text))
    return value


def launch_argument_text(value: Any) -> str:
    """Return the string a launch argument is passed as."""
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def _substitute(node: Any, values: Mapping[str, str], problems: List[str], where: str) -> Any:
    if isinstance(node, str):
        def replace(match):
            key = match.group(1)
            if key not in values:
                problems.append('%s: unknown placeholder ${%s}' % (where, key))
                return match.group(0)
            return str(values[key])
        return _PLACEHOLDER.sub(replace, node)
    if isinstance(node, list):
        return [_substitute(v, values, problems, where) for v in node]
    if isinstance(node, dict):
        return {k: _substitute(v, values, problems, '%s.%s' % (where, k))
                for k, v in node.items()}
    return node


def _scalar(value):
    """
    Return ``value`` with placeholder text turned into the number or boolean it spells.

    A ``${KEY}`` that fills a whole value arrives as a string; the fields that take a number
    or a flag accept the text (``'30'``, ``'0.5'``, ``'true'``) as what it says. Anything else
    is returned unchanged for the caller's own check to reject.
    """
    if isinstance(value, str):
        text = value.strip()
        if text in ('true', 'false'):
            return text == 'true'
        try:
            return int(text)
        except ValueError:
            pass
        try:
            return float(text)
        except ValueError:
            pass
    return value


def _positive(value, where, problems, default):
    value = _scalar(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or \
            not math.isfinite(value) or value <= 0:
        problems.append('%s must be a positive number, got %r' % (where, value))
        return default
    return float(value)


def _string_list(value, where, problems) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        problems.append('%s must be a list of strings' % where)
        return []
    return list(value)


def _unknown(mapping: Mapping, allowed, where, problems) -> None:
    for key in mapping:
        if key not in allowed:
            problems.append('%s: unknown key %r (allowed: %s)' % (where, key, ', '.join(allowed)))


def _parse_arguments(raw, where, problems) -> Dict[str, ArgumentSpec]:
    out = {}
    if raw is None:
        return out
    if not isinstance(raw, dict):
        problems.append('%s must be a mapping of declared arguments' % where)
        return out
    for name, decl in raw.items():
        here = '%s.%s' % (where, name)
        if not isinstance(decl, dict) or 'type' not in decl or 'default' not in decl:
            problems.append('%s must declare {type, default}' % here)
            continue
        _unknown(decl, ('type', 'default'), here, problems)
        if decl['type'] not in ARGUMENT_TYPES:
            problems.append('%s: type must be one of %s' % (here, ', '.join(ARGUMENT_TYPES)))
            continue
        spec = ArgumentSpec(name=str(name), kind=decl['type'], default=decl['default'])
        try:
            coerce_argument(spec, launch_argument_text(spec.default))
        except ValueError as error:
            problems.append('%s: default does not match its type (%s)' % (here, error))
            continue
        out[str(name)] = spec
    return out


def _parse_lifecycle(raw, where, problems) -> Optional[LifecycleSpec]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        problems.append('%s must be a mapping' % where)
        return None
    _unknown(raw, ('match', 'exclude', 'nodes', 'expect', 'target'), where, problems)
    spec = LifecycleSpec()
    if 'match' in raw:
        try:
            re.compile(raw['match'])
            spec.match = raw['match']
        except (re.error, TypeError) as error:
            problems.append('%s.match is not a valid regular expression (%s)' % (where, error))
        if not raw['match']:
            problems.append('%s.match must not be empty (it would never discover anything)'
                            % where)
            spec.match = None
    if 'exclude' in raw:
        try:
            re.compile(raw['exclude'])
            spec.exclude = raw['exclude']
        except (re.error, TypeError) as error:
            problems.append('%s.exclude is not a valid regular expression (%s)' % (where, error))
        if not raw['exclude']:
            problems.append('%s.exclude must not be empty (it would exclude every node)' % where)
            spec.exclude = None
        elif spec.exclude is not None and 'match' not in raw:
            problems.append('%s.exclude needs a match to narrow (listed nodes are explicit)'
                            % where)
            spec.exclude = None
    spec.nodes = list(dict.fromkeys(_string_list(raw.get('nodes'), where + '.nodes', problems)))
    for name in spec.nodes:
        if not name.startswith('/'):
            problems.append('%s.nodes: %r must be a fully qualified name (start with /)'
                            % (where, name))
    if spec.match is None and not spec.nodes:
        problems.append('%s needs either match or nodes' % where)
    default_expect = len(spec.nodes) if spec.nodes else 1
    expect = raw.get('expect', default_expect)
    if isinstance(expect, str) and expect.isdigit():
        expect = int(expect)      # a ${placeholder} arrives as text
    if isinstance(expect, bool) or not isinstance(expect, int) or expect < 1:
        problems.append('%s.expect must be an integer >= 1' % where)
    else:
        spec.expect = expect
        if spec.match is None and spec.nodes and expect > len(spec.nodes):
            problems.append('%s.expect (%d) is more than the %d node(s) listed and there is no '
                            'match to find others' % (where, expect, len(spec.nodes)))
    spec.target = raw.get('target', core.ACTIVE)
    if spec.target not in core.TARGETS:
        problems.append('%s.target must be one of %s' % (where, ', '.join(core.TARGETS)))
        spec.target = core.ACTIVE
    return spec


def _parse_group(name, raw, problems) -> Optional[GroupSpec]:
    where = 'groups.%s' % name
    if not _NAME.match(str(name)):
        problems.append('%s: group names are letters, digits and underscores' % where)
    if not isinstance(raw, dict):
        problems.append('%s must be a mapping' % where)
        return None
    _unknown(raw, ('launch', 'exec', 'arguments', 'requires', 'follows', 'lifecycle', 'ready',
                   'restart', 'description'), where, problems)
    if 'exec' in raw:
        problems.append('%s.exec is not supported in this prototype (launch files only)'
                        % where)
    launch = raw.get('launch')
    if isinstance(launch, dict) and set(launch) == {'path'} and isinstance(
            launch['path'], str) and launch['path']:
        group = GroupSpec(name=str(name), package=None, file=launch['path'])
    elif isinstance(launch, dict) and set(launch) == {'package', 'file'} and all(
            isinstance(v, str) and v for v in launch.values()):
        group = GroupSpec(name=str(name), package=launch['package'], file=launch['file'])
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', group.package):
            problems.append('%s.launch.package %r is not a package name' % (where, group.package))
        if group.file.startswith('/') or '..' in group.file.split('/'):
            problems.append('%s.launch.file %r must stay inside the package launch directory '
                            '(use launch: {path: ...} for any other file)' % (where, group.file))
    else:
        problems.append('%s.launch must be {package: <str>, file: <str>} or {path: <str>}'
                        % where)
        return None
    group.arguments = _parse_arguments(raw.get('arguments'), where + '.arguments', problems)
    group.requires = _string_list(raw.get('requires'), where + '.requires', problems)
    group.follows = _string_list(raw.get('follows'), where + '.follows', problems)
    group.lifecycle = _parse_lifecycle(raw.get('lifecycle'), where + '.lifecycle', problems)
    ready = raw.get('ready') or {}
    if not isinstance(ready, dict):
        problems.append('%s.ready must be a mapping' % where)
        ready = {}
    _unknown(ready, ('nodes', 'timeout'), where + '.ready', problems)
    group.ready_nodes = _string_list(ready.get('nodes'), where + '.ready.nodes', problems)
    for name in group.ready_nodes:
        if not name.startswith('/'):
            problems.append('%s.ready.nodes: %r must be a fully qualified name (start with /)'
                            % (where, name))
    if 'timeout' in ready:
        group.ready_timeout = _positive(ready['timeout'], where + '.ready.timeout', problems, 60.0)
    group.restart = raw.get('restart', 'on-failure')
    if group.restart not in RESTART_POLICIES:
        problems.append('%s.restart must be one of %s' % (where, ', '.join(RESTART_POLICIES)))
    group.description = str(raw.get('description', ''))
    return group


def _check_acyclic(groups: Dict[str, GroupSpec], key: str, problems: List[str]) -> None:
    state: Dict[str, int] = {}

    def visit(name, path):
        if state.get(name) == 2:
            return
        if state.get(name) == 1:
            problems.append('%s cycle: %s' % (key, ' -> '.join(path + [name])))
            return
        state[name] = 1
        for other in getattr(groups[name], key):
            if other in groups:
                visit(other, path + [name])
        state[name] = 2

    for name in groups:
        visit(name, [])


def parse_config(data: Any, substitutions: Optional[Mapping[str, str]] = None) -> ManagerSpec:
    """Validate parsed YAML ``data`` and return the spec; raise ConfigError listing problems."""
    problems: List[str] = []
    if not isinstance(data, dict):
        raise ConfigError('the configuration must be a mapping')
    data = _substitute(data, substitutions or {}, problems, 'config')
    _unknown(data, ('manager', 'groups', 'profiles'), 'config', problems)
    manager = data.get('manager')
    if not isinstance(manager, dict):
        raise ConfigError('\n'.join(problems + ['manager section is required']))
    _unknown(manager, ('name', 'default_profile', 'status_period', 'exit_when_all_stopped',
                       'converge'), 'manager', problems)
    spec = ManagerSpec(name=str(manager.get('name', '')),
                       default_profile=str(manager.get('default_profile', '')))
    if not _NAME.match(spec.name):
        problems.append('manager.name is required (letters, digits and underscores)')
    if 'status_period' in manager:
        spec.status_period = _positive(manager['status_period'], 'manager.status_period',
                                       problems, 1.0)
    flag = _scalar(manager.get('exit_when_all_stopped', False))
    if not isinstance(flag, bool):
        problems.append('manager.exit_when_all_stopped must be true or false')
    else:
        spec.exit_when_all_stopped = flag
    converge = manager.get('converge') or {}
    if not isinstance(converge, dict):
        problems.append('manager.converge must be a mapping')
        converge = {}
    _unknown(converge, _CONVERGE_FIELDS + ('backoff',), 'manager.converge', problems)
    for key, value in converge.items():
        if key == 'backoff':
            if not isinstance(value, list) or not value or not all(
                    isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0
                    for v in value):
                problems.append('manager.converge.backoff must be a non-empty list of seconds')
            else:
                spec.converge.backoff = tuple(float(v) for v in value)
        elif key == 'max_attempts':
            value = _scalar(value)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                problems.append('manager.converge.max_attempts must be an integer >= 1')
            else:
                spec.converge.max_attempts = value
        elif key == 'settle':
            value = _scalar(value)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or \
                    not math.isfinite(value) or value < 0:
                problems.append('manager.converge.settle must be a finite number >= 0')
            else:
                spec.converge.settle = float(value)
        elif key in _CONVERGE_FIELDS:
            setattr(spec.converge, key,
                    _positive(value, 'manager.converge.%s' % key, problems, 1.0))

    groups = data.get('groups')
    if not isinstance(groups, dict) or not groups:
        problems.append('groups must be a non-empty mapping')
        groups = {}
    for name, raw in groups.items():
        parsed = _parse_group(name, raw, problems)
        if parsed is not None:
            spec.groups[parsed.name] = parsed
    for group in spec.groups.values():
        for key in ('requires', 'follows'):
            for other in getattr(group, key):
                if other not in spec.groups:
                    problems.append('groups.%s.%s names unknown group %r'
                                    % (group.name, key, other))
                elif other == group.name:
                    problems.append('groups.%s.%s names itself' % (group.name, key))
    for key in ('requires', 'follows'):
        _check_acyclic(spec.groups, key, problems)

    profiles = data.get('profiles')
    if not isinstance(profiles, dict) or not profiles:
        problems.append('profiles must be a non-empty mapping')
        profiles = {}
    for name, members in profiles.items():
        listed = _string_list(members, 'profiles.%s' % name, problems)
        for member in listed:
            if member not in spec.groups:
                problems.append('profiles.%s names unknown group %r' % (name, member))
        for member in listed:
            group = spec.groups.get(member)
            if group is None:
                continue
            for needed in group.requires:
                if needed not in listed:
                    problems.append('profiles.%s: group %r requires %r, which the profile does '
                                    'not run' % (name, member, needed))
        spec.profiles[str(name)] = listed
    if spec.default_profile not in spec.profiles:
        problems.append('manager.default_profile %r is not a profile' % spec.default_profile)
    if problems:
        raise ConfigError('\n'.join(problems))
    return spec


def load_config(path: str, substitutions: Optional[Mapping[str, str]] = None) -> ManagerSpec:
    """Read and validate the YAML file at ``path``."""
    try:
        with open(path) as stream:
            data = yaml.safe_load(stream)
    except (OSError, yaml.YAMLError) as error:
        raise ConfigError('cannot read %s: %s' % (path, error))
    return parse_config(data, substitutions)
