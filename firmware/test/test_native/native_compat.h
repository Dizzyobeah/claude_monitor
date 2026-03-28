#pragma once
// Minimal stubs for Arduino types/functions used by testable firmware code.
// Only needed for native (host) test builds — real ESP32 builds use Arduino.h.

#include <cstdint>
#include <cstring>
#include <cstdio>

// Stub millis() — tests provide their own time
static uint32_t _fake_millis = 0;
inline uint32_t millis() { return _fake_millis; }
inline void set_millis(uint32_t t) { _fake_millis = t; }
