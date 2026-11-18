# ReDoS Guard

Finds regular expressions that can freeze a backtracking regex engine (ReDoS), generates an attack
string, and builds the minimized DFA that matches the same language in linear time. An ESP32 demo
shows the difference on real hardware.

Theory of Computation PBL project (24B11CS212).

## How it works

```
regex -> parser -> AST -> Thompson NFA -> epsilon removal -> ambiguity check (A x A product)
                                                  |                     |
                                                  |             vulnerable? -> attack string
                                                  v
                                       subset construction -> Moore minimization -> DFA table
                                                                                       |
                                                                  dashboard / ESP32 (C header export)
```

| TOC concept | File |
|---|---|
| Regex to NFA (Thompson's construction) | `redos/parser.py`, `redos/nfa.py` |
| Epsilon removal (keeps parallel edges, see below) | `redos/nfa.py` |
| Exponential ambiguity of an NFA (product automaton, strongly connected components) | `redos/ambiguity.py` |
| Subset construction, alphabet classes | `redos/dfa.py` |
| DFA minimization (Moore partition refinement) | `redos/dfa.py` |
| Backtracking engine (what gets attacked) | `redos/matchers.py`, `esp32/redos_demo/redos_core.h` |

**Detection rule.** A backtracking engine takes exponential time on a regex when its NFA has a state
q and a word w with two different paths q -> q on w. In the product automaton A x A (pairs of states
that read the same character) this means the diagonal pair (q, q) lies in a strongly connected
component that also has a diverging edge, where the two components use different NFA edges. Parallel
edges are kept when removing epsilon moves because two epsilon routes to the same character edge are
two different attempts for a backtracking engine. For `(a+)+` the two loop routes would otherwise
collapse into one edge and the ambiguity would be missed.

**Attack string.** prefix (shortest word to q) + pump (the word w) repeated n times + a suffix
character that makes the whole match fail, so the engine has to try every way to split the pump.

## Run it

```
pip install -r requirements.txt
python -m pytest            # 80 tests
uvicorn redos.api:app --reload
```

Open http://127.0.0.1:8000 for the dashboard and http://127.0.0.1:8000/docs for the API.
The state diagrams are drawn in the browser with a Graphviz library loaded from a CDN, so they need
internet. Without it the page shows the Graphviz source instead and everything else still works.

API:

- `POST /analyze` with `{"regex": "(a+)+"}`: verdict, attack string, benchmark, NFA/DFA state counts, DOT for both diagrams
- `GET /export/header?regex=...`: C header with the DFA and NFA tables for the ESP32
- `GET /mock/match?regex=...&mode=bt|dfa&s=...`: software stand-in for the board (same JSON as the firmware)

## ESP32 demo

1. Generate the tables for the regex: `python -m redos.export "(a+)+" > esp32/redos_demo/redos_tables.h`
   (or use the "Download redos_tables.h" link on the dashboard).
2. Open `esp32/redos_demo/redos_demo.ino` in Arduino IDE, set `WIFI_SSID` and `WIFI_PASS`, board "ESP32 Dev Module", flash.
3. The serial monitor (115200) prints the board IP. Put it in the Device box on the dashboard.
4. Press "Send attack: backtracking". The board hangs and the watchdog resets it after 3 seconds.
   Press "Send attack: DFA". The board answers in microseconds.

The browser has to be on the same WiFi network as the board. If the dashboard is served over https
the browser will block calls to the board's http address; serving it with uvicorn on http avoids this.

The matching code in `redos_core.h` is plain C++. `tests/test_native.py` compiles it with g++ and checks
both matchers against Python's `re` module on hundreds of strings, and checks that the backtracker's
step count grows exponentially while the DFA does not.

**Not verified on real hardware.** The firmware was written for Arduino-ESP32 core 2.x and 3.x but only
the matching core has been compiled and run (on a PC). The WiFi, watchdog and LED code has not been run
on a board. Things to check on first flash: the deep recursion needs the larger loop-task stack that
`SET_LOOP_TASK_STACK_SIZE` requests, and the watchdog setup differs between core 2.x and 3.x.

## Demo script (viva)

1. Analyze `(a+)+`: verdict VULNERABLE, point at the red state in the NFA diagram (two paths from q1 to q1 on `a`).
2. Show the chart: backtracking steps double with every extra character, DFA steps grow by one.
3. Click `[a-z]+@[a-z]+\.com`: SAFE, no attack string.
4. Send the attack to the board in backtracking mode (freeze and reset), then in DFA mode (instant).

## Limits

- Only exponential blow-ups are detected. Polynomial ones such as `a*a*` are reported as safe (the reason text says so).
- Supported syntax: literals, `.`, classes, `\d \w \s`, groups `(...)` and `(?:...)`, `|`, `* + ?`, `{n,m}` up to 50, `^` and `$` at the very start and end. Matching is a full match.
- Not supported: backreferences, lookaround, `\b`, named groups, characters outside ASCII.
- Subset construction can blow up for some regexes. The DFA is capped at 1500 states and the NFA at 1000 states; the tool reports when a cap is hit.
- The ESP32 export allows up to 64 character classes and inputs up to 120 characters.
- The analysis follows a typical greedy backtracking engine. Real engines (V8, Python `re`, Java) add optimizations, so the exact step counts differ, but the exponential growth is the same.

## Layout

```
redos/        parser, NFA, ambiguity checker, DFA, matchers, export, FastAPI app
web/          dashboard (single page, no build step)
esp32/        Arduino sketch + C++ matching core + generated tables
tests/        80 tests (unit, agreement with Python re, native C++ core)
```
