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

"""Unit tests for marine_simulation.demo_nav (the nav2 parameter delta and node names)."""

import copy
import re

from marine_simulation import demo_nav
import pytest
import yaml

SOURCE = yaml.safe_load("""
bt_task_navigator:
  ros__parameters:
    global_frame: <tf_prefix>/map
local_costmap:
  local_costmap:
    ros__parameters:
      width: 350
      resolution: 0.5
      plugins: ["chart_layer", "inflation_layer"]
      chart_layer: {plugin: "s57_layer::S57Layer", enabled: true}
      inflation_layer: {plugin: "nav2_costmap_2d::InflationLayer"}
global_costmap:
  global_costmap:
    ros__parameters:
      width: 5000
      height: 5000
      resolution: 1.0
      plugins: ["chart_layer", "inflation_layer"]
      chart_layer: {plugin: "s57_layer::S57Layer", enabled: true}
      inflation_layer: {plugin: "nav2_costmap_2d::InflationLayer"}
planner_server:
  ros__parameters:
    GridBased: {minimum_turning_radius: 5.0}
""")


def test_the_delta_drops_the_chart_layer_and_shrinks_only_the_global_window():
    out = demo_nav.nav2_params(SOURCE)
    for costmap in ('local_costmap', 'global_costmap'):
        node = out[costmap][costmap]['ros__parameters']
        assert node['plugins'] == ['inflation_layer']
        assert 'chart_layer' not in node
    node = out['global_costmap']['global_costmap']['ros__parameters']
    assert node['width'] == node['height'] == demo_nav.GLOBAL_COSTMAP_SIZE_M
    assert node['resolution'] == demo_nav.GLOBAL_COSTMAP_RESOLUTION_M
    # the local costmap, the one the controller avoids obstacles in, is Ben's
    assert out['local_costmap']['local_costmap']['ros__parameters']['resolution'] == 0.5


def test_everything_outside_the_delta_is_the_source():
    out = demo_nav.nav2_params(SOURCE)
    expected = copy.deepcopy(SOURCE)
    for costmap in ('local_costmap', 'global_costmap'):
        node = expected[costmap][costmap]['ros__parameters']
        node['plugins'] = ['inflation_layer']
        del node['chart_layer']
    expected['global_costmap']['global_costmap']['ros__parameters'].update(
        width=demo_nav.GLOBAL_COSTMAP_SIZE_M, height=demo_nav.GLOBAL_COSTMAP_SIZE_M,
        resolution=demo_nav.GLOBAL_COSTMAP_RESOLUTION_M)
    assert out == expected


def test_the_source_is_not_changed():
    before = copy.deepcopy(SOURCE)
    demo_nav.nav2_params(SOURCE)
    assert SOURCE == before


@pytest.mark.parametrize('mutate', [
    lambda p: p.pop('local_costmap'),
    lambda p: p['global_costmap']['global_costmap']['ros__parameters'].pop('plugins'),
    lambda p: p['global_costmap']['global_costmap']['ros__parameters']['plugins'].remove(
        'chart_layer'),
    lambda p: p['global_costmap']['global_costmap']['ros__parameters'].pop('width'),
    lambda p: p['global_costmap']['global_costmap']['ros__parameters'].pop('resolution'),
])
def test_a_source_that_no_longer_fits_the_delta_is_refused_not_ignored(mutate):
    broken = copy.deepcopy(SOURCE)
    mutate(broken)
    with pytest.raises(ValueError):
        demo_nav.nav2_params(broken)


def test_the_shipped_ben_file_takes_the_delta():
    """The real file (installed with ben_project11) still has what the delta removes."""
    with open(demo_nav.source_path()) as f:
        out = demo_nav.nav2_params(yaml.safe_load(f))
    assert out['global_costmap']['global_costmap']['ros__parameters']['plugins'] == [
        'inflation_layer']


def test_write_params_is_content_addressed_and_reused(tmp_path):
    source = tmp_path / 'ben.yaml'
    source.write_text(yaml.safe_dump(SOURCE))
    first = demo_nav.write_params(str(tmp_path / 'out'), str(source))
    again = demo_nav.write_params(str(tmp_path / 'out'), str(source))
    assert first == again and re.search(r'nav2_params-[0-9a-f]{12}\.yaml$', first)
    assert yaml.safe_load(open(first)) == demo_nav.nav2_params(SOURCE)
    assert [p.name for p in (tmp_path / 'out').iterdir()] == [first.rsplit('/', 1)[1]]


def test_write_params_rewrites_a_damaged_file_and_leaves_no_temporary(tmp_path):
    source = tmp_path / 'ben.yaml'
    source.write_text(yaml.safe_dump(SOURCE))
    path = demo_nav.write_params(str(tmp_path / 'out'), str(source))
    good = open(path).read()
    open(path, 'w').write(good[:20])            # a truncated file under the right name
    assert demo_nav.write_params(str(tmp_path / 'out'), str(source)) == path
    assert open(path).read() == good
    assert [p.name for p in (tmp_path / 'out').iterdir()] == [path.rsplit('/', 1)[1]]


def test_the_exclude_regex_matches_nav2_nodes_of_the_named_boats_only():
    regex = re.compile(demo_nav.nav_exclude_regex(['a', 'b_c']))
    for node in ('/a/controller_server', '/b_c/bt_task_navigator',
                 '/a/local_costmap/local_costmap', '/a/global_costmap/global_costmap'):
        assert regex.search(node), node
    for node in ('/a/mission_manager', '/a/helm_manager', '/c/controller_server',
                 '/a/sensors/mbes/cube_bathymetry', '/aa/controller_server',
                 '/a/controller_server_extra'):
        assert not regex.search(node), node


def test_every_nav2_server_of_ben_launch_is_listed():
    """The list is the lifecycle_nodes list of ben_project11's navigation_launch.py."""
    import os
    from ament_index_python.packages import get_package_share_directory
    path = os.path.join(get_package_share_directory('ben_project11'), 'launch',
                        'navigation_launch.py')
    text = open(path).read()
    start = text.index('lifecycle_nodes = [')
    block = text[start:text.index(']', start)]
    in_launch = set(re.findall(r"^\s*'([a-z_]+)',", block, re.M))
    assert in_launch == set(demo_nav.NAV2_SERVERS)


def test_node_counts_and_names():
    assert demo_nav.lifecycle_nodes_per_boat(9, False) == 9
    assert demo_nav.lifecycle_nodes_per_boat(9, True) == 10
    names = demo_nav.nav_node_names('a')
    assert names['controller_server'] == '/a/controller_server'
    assert len(names) == len(demo_nav.NAV2_SERVERS) + len(demo_nav.NAV2_COSTMAPS)


def test_the_bond_timeout_is_longer_than_nav2s_default_of_four_seconds():
    assert demo_nav.BOND_TIMEOUT_S > 4.0
