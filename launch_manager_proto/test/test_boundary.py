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

"""The package must stay free of marine dependencies, so that moving it out is a rename."""

import ast
import os
import re
import sys
import xml.etree.ElementTree as ET

import pytest

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = os.path.join(PACKAGE_ROOT, 'launch_manager_proto')
ALLOWED_IMPORTS = {
    'launch_manager_proto', 'rclpy', 'launch', 'launch_ros', 'lifecycle_msgs', 'std_msgs',
    'ros2launch_session', 'ament_index_python', 'yaml',
}
ALLOWED_DEPENDS = {
    'ament_index_python', 'launch', 'launch_ros', 'lifecycle_msgs', 'rclpy',
    'ros2launch_session', 'std_msgs',
    'python3-yaml',
}


def module_files():
    return sorted(os.path.join(SOURCES, f) for f in os.listdir(SOURCES) if f.endswith('.py'))


def third_party_imports(path):
    with open(path) as f:
        tree = ast.parse(f.read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split('.')[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split('.')[0])
    return {n for n in names if n not in sys.stdlib_module_names}


@pytest.mark.parametrize('path', module_files(), ids=os.path.basename)
def test_a_module_imports_only_what_a_generic_launch_manager_may(path):
    assert third_party_imports(path) <= ALLOWED_IMPORTS, path


def test_package_xml_depends_only_on_generic_packages():
    root = ET.parse(os.path.join(PACKAGE_ROOT, 'package.xml')).getroot()
    depends = {e.text for e in root if e.tag.endswith('depend') and e.tag != 'buildtool_depend'
               and e.tag != 'test_depend'}
    assert depends <= ALLOWED_DEPENDS, depends


def test_every_third_party_import_is_declared_in_package_xml():
    root = ET.parse(os.path.join(PACKAGE_ROOT, 'package.xml')).getroot()
    declared = {e.text for e in root if e.tag == 'exec_depend'}
    imported = set()
    for path in module_files():
        imported |= third_party_imports(path)
    imported -= {'launch_manager_proto'}
    packages = {'yaml': 'python3-yaml'}
    missing = {packages.get(name, name) for name in imported} - declared
    assert not missing, 'imported but not declared in package.xml: %s' % sorted(missing)


def test_no_marine_package_is_named_anywhere_in_the_package():
    pattern = re.compile(r'\bmarine_\w+|\bunh_marine\w*', re.IGNORECASE)
    files = module_files() + [os.path.join(PACKAGE_ROOT, n) for n in ('package.xml', 'setup.py')]
    for path in files:
        with open(path) as f:
            assert pattern.search(f.read()) is None, path
