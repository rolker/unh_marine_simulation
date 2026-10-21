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

"""Test of the ZeroMQ port shim (src/demo_zmq_ports.c): compile it and bind through a stub."""

import os
import pathlib
import shutil
import subprocess

import pytest

SOURCE = pathlib.Path(__file__).resolve().parents[1] / 'src' / 'demo_zmq_ports.c'
# libzmq stands in as a shared library, so that main's call goes through the dynamic linker
# the way BehaviorTree.CPP's does, and the preloaded shim is found first.
LIBRARY = r"""
#include <stdio.h>
int zmq_bind(void *socket, const char *address) { printf("%s\n", address); return 0; }
"""
MAIN = r"""
int zmq_bind(void *socket, const char *address);
int main(void) {
  zmq_bind(0, "tcp://*:1667");
  zmq_bind(0, "tcp://*:1668");
  zmq_bind(0, "ipc:///tmp/x:5");
  zmq_bind(0, "tcp://127.0.0.1:65530");
  return 0;
}
"""

pytestmark = pytest.mark.skipif(shutil.which('cc') is None, reason='no C compiler')


@pytest.fixture(scope='module')
def tools(tmp_path_factory):
    work = tmp_path_factory.mktemp('shim')
    shim, stub = work / 'libshim.so', work / 'main'
    (work / 'lib.c').write_text(LIBRARY)
    (work / 'main.c').write_text(MAIN)
    subprocess.run(['cc', '-shared', '-fPIC', '-o', str(shim), str(SOURCE), '-ldl'], check=True)
    subprocess.run(['cc', '-shared', '-fPIC', '-o', str(work / 'libstubzmq.so'),
                    str(work / 'lib.c')], check=True)
    subprocess.run(['cc', '-o', str(stub), str(work / 'main.c'), '-L' + str(work), '-lstubzmq',
                    '-Wl,-rpath,' + str(work)], check=True)
    return shim, stub


def bind_addresses(tools, offset):
    shim, stub = tools
    env = dict(os.environ, LD_PRELOAD=str(shim))
    env.pop('DEMO_ZMQ_PORT_OFFSET', None)
    if offset is not None:
        env['DEMO_ZMQ_PORT_OFFSET'] = offset
    out = subprocess.run([str(stub)], env=env, capture_output=True, text=True, check=True)
    return out.stdout.split()


def test_tcp_binds_move_by_the_offset_and_nothing_else_does(tools):
    assert bind_addresses(tools, '10') == [
        'tcp://*:1677', 'tcp://*:1678', 'ipc:///tmp/x:5', 'tcp://127.0.0.1:65530']   # no wrap


@pytest.mark.parametrize('offset', [
    None, '', 'abc', '0', '5x', '1000000', '9223372036854775807', '-9223372036854775808',
    '99999999999999999999'])
def test_no_offset_or_a_bad_one_changes_nothing(tools, offset):
    assert bind_addresses(tools, offset) == [
        'tcp://*:1667', 'tcp://*:1668', 'ipc:///tmp/x:5', 'tcp://127.0.0.1:65530']
