// Copyright 2026 Roland Arsenault, UNH CCOM
// All rights reserved.
//
// Software License Agreement (BSD 2-Clause Simplified License)
//
// Redistribution and use in source and binary forms, with or without
// modification, are permitted provided that the following conditions
// are met:
//
//  * Redistributions of source code must retain the above copyright
//    notice, this list of conditions and the following disclaimer.
//  * Redistributions in binary form must reproduce the above
//    copyright notice, this list of conditions and the following
//    disclaimer in the documentation and/or other materials provided
//    with the distribution.
//
// THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
// "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
// LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
// FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
// COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
// INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
// BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
// LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
// CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
// LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
// ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
// POSSIBILITY OF SUCH DAMAGE.

// LD_PRELOAD shim that moves the TCP ports a process binds with ZeroMQ.
//
// marine_nav_bt_task_navigator creates a BT::Groot2Publisher on every goal, with the library's
// fixed ports (1667 and 1668) and no parameter to change or switch them off, so a second boat on
// the same computer cannot run a goal ("Address already in use"). The demo preloads this library
// into each boat's nav2 processes with DEMO_ZMQ_PORT_OFFSET set to a different number per boat;
// a "tcp://<host>:<port>" bind then uses <port> + offset. Without the variable (or with a value
// that is not a whole number) nothing changes. Retire it when the navigator makes the port a
// parameter.

#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ADDRESS_MAX 256

typedef int (* bind_function)(void * socket, const char * address);

// Return the port to bind instead, written into out, or 0 when the address is left alone.
static int shifted_address(const char * address, char * out, size_t size)
{
  const char * offset_text = getenv("DEMO_ZMQ_PORT_OFFSET");
  if (offset_text == NULL || address == NULL || strncmp(address, "tcp://", 6) != 0) {
    return 0;
  }
  char * end = NULL;
  long offset = strtol(offset_text, &end, 10);  // NOLINT(runtime/int)
  if (end == offset_text || *end != '\0' || offset == 0) {
    return 0;
  }
  const char * colon = strrchr(address, ':');
  if (colon == NULL) {
    return 0;
  }
  char * port_end = NULL;
  long port = strtol(colon + 1, &port_end, 10);  // NOLINT(runtime/int)
  if (port_end == colon + 1 || *port_end != '\0' || port <= 0 || port + offset > 65535 ||
    port + offset <= 0)
  {
    return 0;
  }
  int length = snprintf(
    out, size, "%.*s:%ld", (int)(colon - address), address, port + offset);
  return length > 0 && (size_t)length < size;
}

int zmq_bind(void * socket, const char * address)
{
  static bind_function real_bind = NULL;
  if (real_bind == NULL) {
    real_bind = (bind_function)dlsym(RTLD_NEXT, "zmq_bind");
    if (real_bind == NULL) {
      return -1;
    }
  }
  char shifted[ADDRESS_MAX];
  if (shifted_address(address, shifted, sizeof(shifted))) {
    return real_bind(socket, shifted);
  }
  return real_bind(socket, address);
}
