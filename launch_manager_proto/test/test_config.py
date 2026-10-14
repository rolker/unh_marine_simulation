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

"""Configuration loading and validation."""

import copy

from launch_manager_proto import config
import pytest
import yaml

GOOD = {
    'manager': {'name': 'demo_manager', 'default_profile': 'demo', 'status_period': 0.5,
                'exit_when_all_stopped': True, 'converge': {'settle': 0.5, 'max_attempts': 3,
                                                            'backoff': [0.1, 0.2]}},
    'groups': {
        'boats': {
            'launch': {'package': 'p', 'file': 'boats_launch.py'},
            'arguments': {'joystick': {'type': 'bool', 'default': True}},
            'lifecycle': {'match': '^/(a|b)/', 'expect': 2},
            'ready': {'timeout': 90},
        },
        'camp': {'launch': {'package': 'c', 'file': 'camp_launch.py'}, 'requires': ['boats'],
                 'restart': 'never'},
        'scorer': {'launch': {'package': 's', 'file': 's.py'}, 'follows': ['camp'],
                   'lifecycle': {'nodes': ['/coverage_assessment']}},
    },
    'profiles': {'demo': ['boats', 'camp', 'scorer'], 'boats': ['boats']},
}


def good():
    return copy.deepcopy(GOOD)


def problems(data, **subs):
    with pytest.raises(config.ConfigError) as info:
        config.parse_config(data, subs)
    return str(info.value)


def test_good_config_parses_into_typed_specs():
    spec = config.parse_config(good())
    assert spec.name == 'demo_manager' and spec.exit_when_all_stopped
    assert spec.converge.settle == 0.5 and spec.converge.max_attempts == 3
    assert tuple(spec.converge.backoff) == (0.1, 0.2)
    boats = spec.groups['boats']
    assert boats.lifecycle.match == '^/(a|b)/' and boats.lifecycle.expect == 2
    assert boats.lifecycle.target == 'active' and boats.ready_timeout == 90.0
    assert spec.groups['camp'].restart == 'never'
    assert spec.groups['scorer'].lifecycle.expect == 1
    assert spec.profiles['demo'] == ['boats', 'camp', 'scorer']


def test_placeholders_are_substituted_and_unknown_ones_rejected():
    data = good()
    data['groups']['boats']['lifecycle']['match'] = '^/(${boats})/'
    spec = config.parse_config(data, {'boats': 'a|b'})
    assert spec.groups['boats'].lifecycle.match == '^/(a|b)/'
    assert '${missing}' in problems({**good(), 'groups': {
        **good()['groups'], 'boats': {**good()['groups']['boats'],
                                      'description': '${missing}'}}})


def test_expect_may_arrive_as_text_from_a_placeholder():
    data = good()
    data['groups']['boats']['lifecycle']['expect'] = '${n}'
    assert config.parse_config(data, {'n': '7'}).groups['boats'].lifecycle.expect == 7
    data['groups']['boats']['lifecycle']['expect'] = '${n}'
    assert 'expect must be' in problems(data, n='many')


def test_regex_quantifier_braces_are_not_placeholders():
    data = good()
    data['groups']['boats']['lifecycle']['match'] = '^/a{2}/'
    assert config.parse_config(data).groups['boats'].lifecycle.match == '^/a{2}/'


def test_requires_cycle_is_rejected():
    data = good()
    data['groups']['boats']['requires'] = ['camp']
    assert 'requires cycle' in problems(data)


def test_follows_cycle_is_rejected():
    data = good()
    data['groups']['camp']['follows'] = ['scorer']
    assert 'follows cycle' in problems(data)


def test_unknown_group_references_are_rejected():
    data = good()
    data['groups']['camp']['requires'] = ['ghost']
    data['profiles']['demo'].append('phantom')
    text = problems(data)
    assert "unknown group 'ghost'" in text and "unknown group 'phantom'" in text


def test_profile_with_unsatisfied_requires_is_rejected_at_load():
    data = good()
    data['profiles']['demo'] = ['camp']
    assert "requires 'boats'" in problems(data)


def test_default_profile_must_exist():
    data = good()
    data['manager']['default_profile'] = 'nope'
    assert 'default_profile' in problems(data)


def test_launch_by_path_is_accepted_and_bad_launch_forms_are_not():
    data = good()
    data['groups']['camp']['launch'] = {'path': '/tmp/x_launch.py'}
    spec = config.parse_config(data)
    assert spec.groups['camp'].package is None and spec.groups['camp'].file == '/tmp/x_launch.py'
    data['groups']['camp']['launch'] = {'path': 'a', 'file': 'b'}
    assert 'launch must be' in problems(data)


def test_shutdown_timeouts_are_not_configurable_here():
    data = good()
    data['groups']['camp']['shutdown'] = {'timeout': 5}
    assert "unknown key 'shutdown'" in problems(data)


def test_exec_groups_and_unknown_keys_are_rejected():
    data = good()
    data['groups']['camp']['exec'] = ['ls']
    data['groups']['camp']['respawn'] = True
    text = problems(data)
    assert 'exec is not supported' in text and "unknown key 'respawn'" in text


def test_lifecycle_needs_nodes_or_match_and_a_known_target():
    data = good()
    data['groups']['boats']['lifecycle'] = {'target': 'running'}
    text = problems(data)
    assert 'needs either match or nodes' in text and 'target must be one of' in text


def test_bad_regex_and_relative_node_names_are_rejected():
    data = good()
    data['groups']['boats']['lifecycle'] = {'match': '(', 'nodes': ['relative']}
    text = problems(data)
    assert 'regular expression' in text and 'fully qualified' in text


def test_restart_policy_values():
    data = good()
    data['groups']['camp']['restart'] = 'always'
    assert 'restart must be one of' in problems(data)


def test_numbers_must_be_positive_and_real():
    data = good()
    data['manager']['status_period'] = 0
    data['groups']['boats']['ready']['timeout'] = float('nan')
    text = problems(data)
    assert text.count('positive number') == 2


def test_declared_arguments_are_typed_and_defaults_checked():
    data = good()
    data['groups']['boats']['arguments'] = {
        'n': {'type': 'int', 'default': 'many'}, 'x': {'type': 'color', 'default': 1},
        'free': 'text'}
    text = problems(data)
    assert 'default does not match' in text and 'type must be one of' in text
    assert 'must declare {type, default}' in text


@pytest.mark.parametrize('kind,text,expected', [
    ('string', 'abc', 'abc'), ('bool', 'true', True), ('bool', 'false', False),
    ('int', '12', 12), ('float', '1.5', 1.5)])
def test_coerce_argument_accepts_declared_types(kind, text, expected):
    spec = config.ArgumentSpec('a', kind, None)
    assert config.coerce_argument(spec, text) == expected


@pytest.mark.parametrize('kind,text', [
    ('bool', 'True'), ('bool', '1'), ('int', '1.5'), ('int', 'x'), ('float', 'nan'),
    ('float', 'inf'), ('float', '')])
def test_coerce_argument_rejects_everything_else(kind, text):
    with pytest.raises(ValueError):
        config.coerce_argument(config.ArgumentSpec('a', kind, None), text)


def test_launch_argument_text():
    assert config.launch_argument_text(True) == 'true'
    assert config.launch_argument_text(False) == 'false'
    assert config.launch_argument_text(3) == '3'


def test_not_a_mapping_and_missing_sections():
    assert 'mapping' in problems([1, 2])
    assert 'manager section is required' in problems({})
    data = good()
    del data['profiles']
    assert 'profiles must be' in problems(data)


def test_load_config_reports_unreadable_and_invalid_yaml(tmp_path):
    with pytest.raises(config.ConfigError, match='cannot read'):
        config.load_config(str(tmp_path / 'missing.yaml'))
    bad = tmp_path / 'bad.yaml'
    bad.write_text('manager: [unclosed')
    with pytest.raises(config.ConfigError, match='cannot read'):
        config.load_config(str(bad))


def test_load_config_round_trip(tmp_path):
    path = tmp_path / 'ok.yaml'
    path.write_text(yaml.safe_dump(GOOD))
    assert config.load_config(str(path)).default_profile == 'demo'


def test_numbers_and_flags_may_arrive_as_placeholder_text():
    data = good()
    data['manager']['status_period'] = '${period}'
    data['manager']['exit_when_all_stopped'] = '${exit}'
    data['manager']['converge'] = {'settle': '${settle}', 'max_attempts': '${tries}',
                                   'reply_timeout': '${reply}'}
    data['groups']['boats']['ready']['timeout'] = '${ready}'
    spec = config.parse_config(data, {'period': '0.5', 'exit': 'false', 'settle': '0',
                                      'tries': '3', 'reply': '2', 'ready': '45'})
    assert spec.status_period == 0.5 and spec.exit_when_all_stopped is False
    assert spec.converge.settle == 0.0 and spec.converge.max_attempts == 3
    assert spec.converge.reply_timeout == 2.0 and spec.groups['boats'].ready_timeout == 45.0
    text = problems(data, period='soon', exit='maybe', settle='-1', tries='0', reply='x',
                    ready='y')
    assert text.count('must be') >= 5


def test_a_lifecycle_section_that_could_never_become_ready_is_refused():
    data = good()
    data['groups']['scorer']['lifecycle'] = {'nodes': ['/a'], 'expect': 3}
    assert 'more than the 1 node' in problems(data)
    data = good()
    data['groups']['boats']['lifecycle'] = {'match': ''}
    assert 'must not be empty' in problems(data)
    data = good()
    data['groups']['scorer']['lifecycle'] = {'nodes': ['/a', '/a', '/b']}
    spec = config.parse_config(data)
    assert spec.groups['scorer'].lifecycle.nodes == ['/a', '/b']
    assert spec.groups['scorer'].lifecycle.expect == 2
    data = good()
    data['groups']['boats']['ready']['nodes'] = ['relative']
    assert 'ready.nodes' in problems(data)


@pytest.mark.parametrize('package,file', [
    ('p', '../x.py'), ('p', '/etc/x.py'), ('p', 'a/../../x.py'), ('../p', 'x.py'),
    ('p q', 'x.py')])
def test_a_launch_file_may_not_leave_its_package_directory(package, file):
    data = good()
    data['groups']['camp']['launch'] = {'package': package, 'file': file}
    assert 'launch.' in problems(data)


def test_a_launch_file_in_a_subdirectory_of_the_launch_directory_is_fine():
    data = good()
    data['groups']['camp']['launch'] = {'package': 'p', 'file': 'sub/x_launch.py'}
    assert config.parse_config(data).groups['camp'].file == 'sub/x_launch.py'
