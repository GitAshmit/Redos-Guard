"""FastAPI app. Run from the project root:  uvicorn redos.api:app --reload
Open http://127.0.0.1:8000 for the dashboard and /docs for the API.
"""
import sys
from pathlib import Path
from time import perf_counter

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .analyze import analyze, compile_regex
from .dfa import dfa_match
from .export import to_c_header
from .matchers import backtrack_match
from .parser import RegexSyntaxError

sys.setrecursionlimit(8000)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
MOCK_STEP_LIMIT = 300_000  # the mock device "hangs" (watchdog reset) past this many steps

app = FastAPI(title="ReDoS Guard", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class AnalyzeRequest(BaseModel):
    regex: str = Field(..., min_length=1, max_length=300)
    max_steps: int = Field(1_000_000, ge=1_000, le=5_000_000)
    max_pump: int = Field(40, ge=2, le=100)


def _syntax_error(e):
    return HTTPException(status_code=422, detail={"error": e.msg, "position": e.pos})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze")
def analyze_endpoint(req: AnalyzeRequest):
    try:
        return analyze(req.regex, max_steps=req.max_steps, max_pump=req.max_pump)
    except RegexSyntaxError as e:
        raise _syntax_error(e)


@app.get("/export/header", response_class=PlainTextResponse)
def export_header(regex: str = Query(..., min_length=1, max_length=300)):
    """C header with the DFA table and NFA tables for the ESP32 firmware (redos_tables.h)."""
    try:
        return PlainTextResponse(
            to_c_header(regex),
            headers={"Content-Disposition": 'attachment; filename="redos_tables.h"'},
        )
    except RegexSyntaxError as e:
        raise _syntax_error(e)


@app.get("/mock/status")
def mock_status():
    return {"regex_states": 0, "dfa_states": 0, "uptime_ms": 0, "last_reset": "mock device"}


@app.get("/mock/match")
def mock_match(regex: str = Query(..., min_length=1, max_length=300),
               mode: str = Query("dfa"), s: str = Query("", max_length=120)):
    """Software stand-in for the ESP32 (same JSON shape), so the demo works without the board.

    In bt mode it behaves like the real board: past MOCK_STEP_LIMIT steps the board would hang
    until the watchdog resets it, which is reported as reset=true.
    """
    try:
        ast, _, _, _, mdfa, _ = compile_regex(regex)
    except RegexSyntaxError as e:
        raise _syntax_error(e)
    t0 = perf_counter()
    if mode == "bt":
        matched, steps, capped = backtrack_match(ast, s, MOCK_STEP_LIMIT)
        if capped:
            return {"mode": "bt", "reset": True, "matched": False, "steps": steps,
                    "micros": None, "capped": True,
                    "note": "mock device: this input would hang the board until the watchdog resets it"}
    else:
        if mdfa is None:
            raise HTTPException(status_code=422, detail={"error": "DFA too large", "position": None})
        matched, steps = dfa_match(mdfa, s)
    return {"mode": mode, "matched": matched, "steps": steps, "capped": False,
            "micros": int((perf_counter() - t0) * 1_000_000)}


if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
