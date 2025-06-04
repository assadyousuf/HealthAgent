import os
import sys
from typing import Any

from dotenv import load_dotenv
from loguru import logger

# Pipecat imports
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.network.fastapi_websocket import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat_flows import FlowManager

# Pipecat-flows imports


from medical_intake_flow import flow_config

# Project-specific imports
# Assuming services.address_validator is in a directory reachable by Python's import system.
# If flow_bot.py is in src/, and services/ is in src/, then from .services.address_validator import AddressValidator
# Or ensure PYTHONPATH is set up correctly.
# For now, using the user's original import path from bot.py
from services.address_validator import AddressValidator

load_dotenv(override=True)

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")

# --- Constants and Global Data ---
BASE_SYSTEM_PROMPT = "You are a friendly, polite, and efficient medical office assistant. Your output will be converted to audio, so do not use any special characters like asterisks or lists. Speak in short, clear, and complete sentences. Only ask one question at a time, unless specified otherwise. Wait for the user to respond before moving to the next question. You must ALWAYS use one of the available functions to progress the conversation. If a user provides information that seems insufficient or incorrect for a function call, ask for clarification before calling the function."

AVAILABLE_APPOINTMENTS = [
    {"doctor": "Dr. Smith", "day": "Monday", "time": "10:00 AM"},
    {"doctor": "Dr. Jones", "day": "Tuesday", "time": "2:30 PM"},
    {"doctor": "Dr. Lee", "day": "Wednesday", "time": "9:15 AM"},
    {"doctor": "Dr. Brown", "day": "Friday", "time": "4:00 PM"},
]




# --- Main Bot Logic (adapted from original bot.py and patient_intake_openai.py) ---
async def run_bot(websocket_client: Any, stream_sid: str, call_sid: str, testing: bool):
    twilio_serializer = TwilioFrameSerializer(
        stream_sid=stream_sid,
        call_sid=call_sid,
        account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
        auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
    )

    transport = FastAPIWebsocketTransport(
        websocket=websocket_client,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_analyzer=SileroVADAnalyzer(),
            serializer=twilio_serializer,
        ),
    )

    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))

    cartesia_api_key = os.getenv("CARTESIA_API_KEY")
    if not cartesia_api_key:
        logger.error("CARTESIA_API_KEY environment variable not found!")
    tts = CartesiaTTSService(
        api_key=cartesia_api_key,
        voice_id="71a7ad14-091c-4e8e-a314-022ece01c121",
        push_silence_after_stop=testing,
    )

    llm = OpenAILLMService(
        api_key=os.getenv("OPENAI_API_KEY"),
        model=os.getenv("OPENAI_MODEL_NAME", "gpt-4.1-nano"),
    )

    llm_history_context = OpenAILLMContext()
    context_aggregator = llm.create_context_aggregator(llm_history_context)

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
            allow_interruptions=True,
        ),
    )

    flow_manager = FlowManager(
        task=task,
        llm=llm,
        context_aggregator=context_aggregator,
        tts=tts,
        flow_config=flow_config,
    )


    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport_instance, client):
        logger.info(f"Client {client} connected to transport")
        await flow_manager.initialize()

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport_instance, client):
        logger.info(f"Client {client} disconnected from transport")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False, force_gc=True)
    logger.info("Starting AssortHealth Flow Bot pipeline runner...")
    await runner.run(task)
    logger.info("AssortHealth Flow Bot pipeline task finished.")
