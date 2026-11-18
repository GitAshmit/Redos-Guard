// Reads one test string per line from stdin, prints "<bt> <dfa> <bt_steps>" for each line.
// Built by tests/test_native.py against a freshly generated redos_tables.h.
#include <cstdio>
#include <cstring>
#include <string>
#include <iostream>
#include "redos_core.h"

int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    uint32_t bt_steps = 0, dfa_steps = 0;
    bool capped = false;
    bool bt = rg_bt_match(line.c_str(), line.size(), &bt_steps, 5000000, &capped);
    bool dfa = rg_dfa_match(line.c_str(), line.size(), &dfa_steps);
    std::printf("%d %d %u %d\n", (int)bt, (int)dfa, bt_steps, (int)capped);
  }
  return 0;
}
