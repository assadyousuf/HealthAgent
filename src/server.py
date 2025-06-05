import argparse
import json
import os
import xml  # Added import

import uvicorn
from .bot import run_bot
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import HTMLResponse

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Determine the absolute path to the templates directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(SCRIPT_DIR, "..", "templates")


@app.post("/")
async def start_call():
    print("POST TwiML")
    # Adjusted path for templates
    streams_xml_path = os.path.join(TEMPLATE_DIR, "streams.xml")
    with open(streams_xml_path) as f:
        xml_content = f.read()

    return HTMLResponse(content=xml_content, media_type="application/xml")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    start_data = websocket.iter_text()
    await start_data.__anext__()
    call_data = json.loads(await start_data.__anext__())
    print(call_data, flush=True)
    stream_sid = call_data["start"]["streamSid"]
    call_sid = call_data["start"]["callSid"]
    print("WebSocket connection accepted")
    await run_bot(websocket, stream_sid, call_sid, testing=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Pipecat AssortHealth Agent Server"
    )  # Modified description
    parser.add_argument(
        "-t",
        "--test",
        action="store_true",
        default=False,
        help="set the server in testing mode",
    )
    args, _ = parser.parse_known_args()

    app.state.testing = args.test

    uvicorn.run(app, host="0.0.0.0", port=8765)
