"""
server.py - FastAPI WebSocket server for Exotel Voicebot
Phase 1: B2C focused, architecture ready for B2B multi-tenancy
"""

import json
import os
from fastapi import FastAPI, WebSocket

from pipecat.serializers.exotel import ExotelFrameSerializer
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

from ..config import WS_HOST, WS_PORT, EXOTEL_SAMPLE_RATE
from ..core.pipeline import build_b2c_pipeline
from ..memory.memory_store import MemoryStore

app = FastAPI(title="AI Phone Assistant - B2C MVP")
memory = MemoryStore()

@app.get("/healthz")
async def healthz():
    return {"status": "ok", "phase": "B2C MVP", "languages": ["hi-IN", "te-IN", "en-IN"]}


def _extract_phone_number(start_event: dict) -> str:
    """Extract caller number from Exotel start event.
    TODO: Verify exact key with real Exotel payload on first test call.
    """
    start = start_event.get("start", {})
    custom = start.get("customParameters", {})
    return (
        custom.get("From") or 
        custom.get("CallFrom") or 
        start.get("from") or 
        "unknown"
    )


@app.websocket("/exotel-stream")
async def exotel_stream(websocket: WebSocket):
    await websocket.accept()

    # Read first message (Exotel "start" event)
    start_event = json.loads(await websocket.receive_text())
    stream_sid = start_event["start"]["streamSid"]
    call_sid = start_event["start"].get("callSid")
    phone_number = _extract_phone_number(start_event)

    print(f"[server] New call | stream_sid={stream_sid} | from={phone_number}")

    # Load / create profile immediately
    profile = await memory.start_call(phone_number)

    print(f"[server] Profile loaded for {phone_number} | calls: {profile.total_calls}")

    # Build and run the full Pipecat pipeline
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
    finally:
        # Graceful disconnect handling
        # In production, we should cancel running PipelineTask and background tasks here
        # to prevent memory leaks and wasted API calls on abrupt hang-ups.
        print(f"[server] Call ended cleanly: {phone_number}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=WS_HOST, port=WS_PORT)