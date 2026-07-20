"""
server.py - FastAPI WebSocket server for Exotel Voicebot
Phase 1: B2C focused, architecture ready for B2B multi-tenancy
"""

from fastapi import FastAPI, WebSocket

from pipecat.runner.utils import parse_telephony_websocket

from ..config import WS_HOST, WS_PORT
from ..core.pipeline import build_b2c_pipeline
from ..memory.memory_store import MemoryStore

app = FastAPI(title="AI Phone Assistant - B2C MVP")
memory = MemoryStore()


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "phase": "B2C MVP", "languages": ["hi-IN", "te-IN", "en-IN"]}


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
