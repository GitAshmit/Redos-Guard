// Matching core for the ReDoS demo. Plain C++, no Arduino dependencies, so the same code
// can be compiled and tested on a PC (see tests/test_native.py).
// Needs redos_tables.h (generated: python -m redos.export "<regex>" > redos_tables.h).
#pragma once
#include <stddef.h>
#include <stdint.h>
#include "redos_tables.h"

static inline uint8_t rg_class_of(char c) {
  unsigned char u = (unsigned char)c;
  return u < 128 ? RG_CLASS_MAP[u] : RG_NCLASS;
}

// Minimized DFA: one table lookup per character, so time is linear in the input length.
static bool rg_dfa_match(const char* s, size_t n, uint32_t* steps) {
  uint16_t st = RG_DFA_START;
  uint32_t k = 0;
  for (size_t i = 0; i < n; i++) {
    st = RG_DFA_TRANS[st][rg_class_of(s[i])];
    k++;
  }
  if (steps) *steps = k;
  return RG_DFA_ACCEPT[st] != 0;
}

// Backtracking matcher over the Thompson NFA. It behaves like a typical regex engine, so a
// vulnerable pattern makes it take exponential time. max_steps = 0 means "never give up",
// which is what lets the watchdog reset the board in the demo.
struct RgBacktracker {
  const char* s;
  size_t n;
  uint32_t steps, max_steps;
  bool capped;
  int16_t mark[RG_NFA_STATES];  // position at which a state is on the current epsilon path
};

static bool rg_bt(RgBacktracker& b, int st, size_t i) {
  if (b.capped) return false;
  if (++b.steps > b.max_steps && b.max_steps != 0) {
    b.capped = true;
    return false;
  }
  if (b.mark[st] == (int16_t)i) return false;  // epsilon loop without consuming input
  int16_t old = b.mark[st];
  b.mark[st] = (int16_t)i;
  bool ok = false;
  if (st == RG_NFA_ACCEPT) {
    ok = (i == b.n);
  } else {
    if (RG_NFA_CHAR_DST[st] >= 0 && i < b.n &&
        ((RG_NFA_CHAR_SET[st] >> rg_class_of(b.s[i])) & 1ULL)) {
      ok = rg_bt(b, RG_NFA_CHAR_DST[st], i + 1);
    }
    for (uint16_t k = RG_NFA_EPS_OFF[st]; !ok && !b.capped && k < RG_NFA_EPS_OFF[st + 1]; k++) {
      ok = rg_bt(b, RG_NFA_EPS[k], i);
    }
  }
  b.mark[st] = old;
  return ok;
}

static bool rg_bt_match(const char* s, size_t n, uint32_t* steps, uint32_t max_steps, bool* capped) {
  RgBacktracker b;
  b.s = s;
  b.n = n;
  b.steps = 0;
  b.max_steps = max_steps;
  b.capped = false;
  for (int i = 0; i < RG_NFA_STATES; i++) b.mark[i] = -1;
  bool ok = rg_bt(b, RG_NFA_START, 0);
  if (steps) *steps = b.steps;
  if (capped) *capped = b.capped;
  return ok && !b.capped;
}
