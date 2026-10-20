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
Unit tests for ``marine_simulation.demo_perspective`` and the shipped ``demo.perspective``.

The perspective file is checked against the roster, so a boat added or renamed there fails here
until ``python3 -m marine_simulation.demo_perspective`` regenerates the file. Boat names come
from the shipped roster, never quoted.
"""

import json
import pathlib
import re

from marine_simulation import demo_perspective as dp
from marine_simulation import roster
import pytest
import yaml

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
SHIPPED = PACKAGE / 'config' / 'demo.perspective'
ROSTER = PACKAGE / 'config' / 'demo_roster.yaml'

# What qt_gui writes after it imported the shipped file once (the live check, 2026-10-20): the
# name list is a binary @Variant, so the keys of the [perspective] section are the sign.
STORED = ('[General]\nperspectives=@Variant(\\0\\0\\0\\t\\0\\0\\0\\x1)\n\n[perspective]\n'
          '%40demo.perspective\\pluginmanager\\running-plugins=x\n')


def boat_names():
    return [boat.name for boat in roster.load_roster(str(ROSTER))]


def _value(entry):
    """Decode a value the way ``PerspectiveManager._import_value`` does (type ``repr``)."""
    assert entry['type'] == 'repr'
    return eval(entry['repr'])      # noqa: S307 - qt_gui does exactly this with the same data


def _instances(data):
    return data['groups']['pluginmanager']['groups']


# --- the shipped file against the roster ---------------------------------------------------

def test_the_shipped_file_is_what_the_generator_writes_for_the_roster():
    assert SHIPPED.read_text() == dp.perspective_text(boat_names()), (
        'regenerate: python3 -m marine_simulation.demo_perspective '
        'config/demo_roster.yaml config/demo.perspective')


def test_one_ping_profile_per_boat_with_its_name_and_full_topic():
    groups = _instances(json.loads(SHIPPED.read_text()))
    configs = {}
    for name, group in groups.items():
        if name.startswith('plugin__rqt_ping_profile__'):
            configs[name] = yaml.safe_load(
                _value(group['groups']['plugin']['keys']['config_yaml']))
    assert len(configs) == len(boat_names())
    by_title = {c['title']: c for c in configs.values()}
    assert sorted(by_title) == sorted(boat_names())
    for boat, config in by_title.items():
        assert config['topic'] == '/%s/sensors/mbes/detections' % boat
        assert (config['depth_mode'], config['depth_min'], config['depth_max']) == \
            ('fixed', 0.0, 30.0)


def test_the_coverage_plugin_is_there_on_the_scorers_topic():
    groups = _instances(json.loads(SHIPPED.read_text()))
    (coverage,) = [g for n, g in groups.items() if n.startswith('plugin__rqt_coverage__')]
    config = yaml.safe_load(_value(coverage['groups']['plugin']['keys']['config_yaml']))
    assert config['topic'] == 'coverage_assessment'


def test_running_plugins_list_every_instance_exactly_once():
    data = json.loads(SHIPPED.read_text())
    running = _value(data['groups']['pluginmanager']['keys']['running-plugins'])
    assert running[dp.COVERAGE_PLUGIN_ID] == [1]
    assert running[dp.PING_PROFILE_PLUGIN_ID] == list(range(1, len(boat_names()) + 1))
    expected = {dp.instance_name(plugin, serial)
                for plugin, serials in running.items() for serial in serials}
    assert expected == set(_instances(data))


def test_the_file_holds_no_monitor_specific_window_state():
    text = SHIPPED.read_text()
    assert 'mainwindow' not in text and 'geometry' not in text


def test_the_plugin_ids_are_the_ones_the_plugin_packages_declare():
    ui = pathlib.Path(__file__).resolve()
    for part in ui.parents:
        candidate = part / 'ui_ws' / 'src' / 'rqt_operator_tools'
        if candidate.is_dir():
            break
    else:
        pytest.skip('rqt_operator_tools is not in this workspace')
    for plugin_id in (dp.COVERAGE_PLUGIN_ID, dp.PING_PROFILE_PLUGIN_ID):
        package, _, klass = plugin_id.partition('/')
        text = (candidate / package / 'plugin.xml').read_text()
        assert 'class name="%s"' % klass in text


def test_the_generator_follows_the_roster_order_and_names(tmp_path):
    out = tmp_path / 'p.perspective'
    assert dp.main([str(ROSTER), str(out)]) == 0
    assert out.read_text() == SHIPPED.read_text()
    assert dp.main([]) == 2
    text = dp.perspective_text(['alpha', 'beta'])
    assert '/alpha/sensors/mbes/detections' in text and '/beta/sensors/mbes/detections' in text
    assert re.search(r'PingProfilePlugin__2', text) and 'PingProfilePlugin__3' not in text


# --- how rqt is started ---------------------------------------------------------------------

def test_the_imported_name_is_the_one_qt_gui_gives_a_file():
    # qt_gui/main.py: HIDDEN_PREFIX + os.path.basename(perspective_file)
    assert dp.imported_name('/a/b/demo.perspective') == '@demo.perspective'


def test_the_settings_file_follows_xdg_config_home_then_home():
    assert dp.rqt_settings_file({'XDG_CONFIG_HOME': '/x', 'HOME': '/h'}) == \
        '/x/ros.org/rqt_gui.ini'
    assert dp.rqt_settings_file({'HOME': '/h'}) == '/h/.config/ros.org/rqt_gui.ini'
    assert dp.rqt_settings_file({'XDG_CONFIG_HOME': '', 'HOME': '/h'}) == \
        '/h/.config/ros.org/rqt_gui.ini'


def _settings(tmp_path, text=None):
    path = tmp_path / 'rqt_gui.ini'
    if text is not None:
        path.write_text(text)
    return str(path)


def test_no_settings_file_is_a_first_start(tmp_path):
    arguments, why = dp.rqt_arguments(str(SHIPPED), False, _settings(tmp_path))
    assert arguments == ['--perspective-file', str(SHIPPED)] and 'first start' in why


def test_the_stored_perspective_is_started_by_name(tmp_path):
    arguments, why = dp.rqt_arguments(str(SHIPPED), False, _settings(tmp_path, STORED))
    assert arguments == ['--perspective', '@demo.perspective'] and 'stored' in why


def test_a_plain_name_list_is_read_too(tmp_path):
    text = '[General]\nperspectives=Default, @@demo.perspective, "a, b"\n'
    assert dp.has_perspective(_settings(tmp_path, text), '@demo.perspective')
    assert dp.has_perspective(_settings(tmp_path, text), 'a, b')
    assert dp.has_perspective(_settings(tmp_path, text), 'Default')
    assert not dp.has_perspective(_settings(tmp_path, text), 'demo')


def test_the_operators_old_demo_perspective_does_not_count(tmp_path):
    old = '[General]\nperspectives=Default, demo\n\n[perspective]\ndemo\\mainwindow\\state=1\n'
    arguments, _ = dp.rqt_arguments(str(SHIPPED), False, _settings(tmp_path, old))
    assert arguments[0] == '--perspective-file'


def test_a_name_that_only_starts_like_ours_does_not_count(tmp_path):
    other = '[perspective]\n%40demo.perspective2\\mainwindow\\state=1\n'
    assert not dp.has_perspective(_settings(tmp_path, other), '@demo.perspective')


def test_fresh_imports_again_but_only_the_first_time_in_a_process(tmp_path):
    settings = _settings(tmp_path, STORED)
    first, why = dp.rqt_arguments(str(SHIPPED), True, settings)
    assert first[0] == '--perspective-file' and '--rqt-fresh' in why
    second, _ = dp.rqt_arguments(str(SHIPPED), True, settings)
    assert second[0] == '--perspective'


def test_fresh_is_not_used_up_by_a_start_that_failed(tmp_path):
    with pytest.raises(ValueError, match='does not exist'):
        dp.rqt_arguments(str(tmp_path / 'missing.perspective'), True, _settings(tmp_path))
    assert dp.rqt_arguments(str(SHIPPED), True, _settings(tmp_path, STORED))[0][0] == \
        '--perspective-file'


def test_an_unreadable_settings_file_is_named_not_treated_as_a_first_start(tmp_path):
    with pytest.raises(ValueError, match='cannot read the rqt settings'):
        dp.rqt_arguments(str(SHIPPED), False, str(tmp_path))      # a directory
