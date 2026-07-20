"""
server.py - FastAPI WebSocket server for Exotel Voicebot
Phase 1: B2C focused, architecture ready for B2B multi-tenancy

Also serves /dashboard: per-call transcripts, language events, and metrics
from logs/calls/*.jsonl. Protected by DASHBOARD_KEY (env) because ngrok makes
this server public -- transcripts must never be one guessable URL away.
"""

import html
import json
import os

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import HTMLResponse

from pipecat.runner.utils import parse_telephony_websocket

from ..config import WS_HOST, WS_PORT
from ..core.pipeline import build_b2c_pipeline
from ..memory.memory_store import MemoryStore
from ..utils.call_log import LOG_DIR

app = FastAPI(title="AI Phone Assistant - B2C MVP")
memory = MemoryStore()

DASHBOARD_KEY = os.environ.get("DASHBOARD_KEY", "")


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "phase": "B2C MVP", "languages": ["hi-IN", "te-IN", "en-IN"]}


def _check_key(k: str):
    if not DASHBOARD_KEY:
        raise HTTPException(403, "Dashboard disabled: set DASHBOARD_KEY in .env")
    if k != DASHBOARD_KEY:
        raise HTTPException(403, "Wrong or missing key (?k=...)")


_STYLE = """<style>
body{font-family:system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;
     background:#111;color:#eee}
a{color:#7ab8ff} h1,h2{font-weight:600} .muted{color:#888;font-size:.85em}
.turn{margin:.5rem 0;padding:.55rem .8rem;border-radius:10px;max-width:80%}
.user{background:#1d3a5f;margin-left:auto} .bot{background:#2a2a2a}
.event{color:#c9a227;font-size:.85em;margin:.4rem 0;text-align:center}
table{border-collapse:collapse;width:100%} td,th{padding:.4rem .6rem;text-align:left;
border-bottom:1px solid #333} tr:hover{background:#1a1a1a}
</style>"""


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(k: str = ""):
    """List calls, newest first."""
    _check_key(k)
    rows = []
    if os.path.isdir(LOG_DIR):
        for name in sorted(os.listdir(LOG_DIR), reverse=True):
            if not name.endswith(".jsonl"):
                continue
            meta = {"phone": "?", "turns": 0, "lang": "", "dur": ""}
            try:
                with open(os.path.join(LOG_DIR, name), encoding="utf-8") as f:
                    for line in f:
                        ev = json.loads(line)
                        if ev["type"] == "call_started":
                            meta["phone"] = ev.get("phone", "?")
                        elif ev["type"] == "user":
                            meta["turns"] += 1
                        elif ev["type"] == "call_ended":
                            meta["lang"] = ev.get("lang", "")
                            meta["dur"] = f"{ev.get('call_duration_sec', '')}s"
            except Exception:
                pass
            rows.append(
                f"<tr><td><a href='/dashboard/{html.escape(name)}?k={html.escape(k)}'>"
                f"{html.escape(name)}</a></td><td>{html.escape(str(meta['phone']))}</td>"
                f"<td>{meta['turns']}</td><td>{html.escape(str(meta['lang']))}</td>"
                f"<td>{html.escape(str(meta['dur']))}</td></tr>"
            )
    body = (
        f"<h1>Sahaay — Calls</h1><table><tr><th>Call</th><th>From</th>"
        f"<th>User turns</th><th>End lang</th><th>Duration</th></tr>{''.join(rows)}</table>"
        if rows
        else "<h1>Sahaay — Calls</h1><p class=muted>No calls logged yet.</p>"
    )
    return HTMLResponse(f"<!doctype html><title>Sahaay Calls</title>{_STYLE}{body}")


@app.get("/dashboard/{fname}", response_class=HTMLResponse)
async def dashboard_call(fname: str, k: str = ""):
    """Render one call as a conversation."""
    _check_key(k)
    # Path traversal guard: basename only, must exist inside LOG_DIR.
    if os.path.basename(fname) != fname or not fname.endswith(".jsonl"):
        raise HTTPException(404)
    path = os.path.join(LOG_DIR, fname)
    if not os.path.isfile(path):
        raise HTTPException(404)

    parts = [f"<p><a href='/dashboard?k={html.escape(k)}'>&larr; all calls</a></p>",
             f"<h2>{html.escape(fname)}</h2>"]
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            t, typ = ev.get("t", ""), ev.get("type")
            if typ == "user":
                lang = f" <span class=muted>[{ev.get('lang')}]</span>" if ev.get("lang") else ""
                parts.append(f"<div class='turn user'><span class=muted>{t}s</span> "
                             f"{html.escape(ev.get('text', ''))}{lang}</div>")
            elif typ == "bot":
                parts.append(f"<div class='turn bot'><span class=muted>{t}s</span> "
                             f"{html.escape(ev.get('text', ''))}</div>")
            elif typ == "call_started":
                parts.append(f"<div class=event>call from {html.escape(str(ev.get('phone')))}</div>")
            elif typ == "language_switch":
                parts.append(f"<div class=event>language &rarr; {html.escape(str(ev.get('to')))} "
                             f"({html.escape(str(ev.get('why')))})</div>")
            elif typ == "call_ended":
                parts.append(f"<div class=event>ended &middot; {html.escape(json.dumps(ev))}</div>")
            else:
                parts.append(f"<div class=event>{html.escape(json.dumps(ev, ensure_ascii=False))}</div>")
    return HTMLResponse(f"<!doctype html><title>{html.escape(fname)}</title>{_STYLE}{''.join(parts)}")


def _phone_from_call_data(call_data) -> str:
    """Normalize caller phone from Exotel parse result."""
    # CallData supports both attribute and dict-style access
    phone = (
        getattr(call_data, "from_number", None)
        or call_data.get("from")
        or call_data.get("from_number")
        or ""
    )
    if not phone:
        custom = call_data.get("custom_parameters") or {}
        if isinstance(custom, dict):
            phone = custom.get("From") or custom.get("CallFrom") or custom.get("from") or ""
        elif isinstance(custom, str) and "from=" in custom.lower():
            # e.g. "lead=42&from=9198..."
            for part in custom.split("&"):
                if "=" in part and part.split("=", 1)[0].lower() in ("from", "callfrom"):
                    phone = part.split("=", 1)[1]
                    break
    return phone or "unknown"


@app.websocket("/exotel-stream")
async def exotel_stream(websocket: WebSocket):
    await websocket.accept()

    # Exotel sends: 1) {"event":"connected"} then 2) {"event":"start", "start":{...}}
    # parse_telephony_websocket consumes both and returns typed call_data.
    # Old code only read one message and crashed with KeyError: 'start'.
    try:
        transport_type, call_data = await parse_telephony_websocket(websocket)
    except Exception as e:
        print(f"[server] Failed to parse Exotel handshake: {e}")
        await websocket.close()
        return

    stream_sid = call_data.get("stream_id") or call_data.get("stream_sid")
    call_sid = call_data.get("call_id") or call_data.get("call_sid")
    phone_number = _phone_from_call_data(call_data)

    print(
        f"[server] New call | transport={transport_type} | "
        f"stream_sid={stream_sid} | call_sid={call_sid} | from={phone_number}"
    )

    if not stream_sid:
        print(f"[server] Missing stream_sid in call_data={call_data}; closing")
        await websocket.close()
        return

    profile = await memory.start_call(phone_number)
    print(f"[server] Profile loaded for {phone_number} | calls: {profile.total_calls}")

    try:
        await build_b2c_pipeline(
            websocket=websocket,
            stream_sid=stream_sid,
            call_sid=call_sid,
            phone_number=phone_number,
            profile=profile,
            memory=memory,
        )
    except Exception as e:
        print(f"[server] Pipeline error: {e}")
        import traceback

        traceback.print_exc()
    finally:
        print(f"[server] Call ended: {phone_number}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=WS_HOST, port=WS_PORT)
