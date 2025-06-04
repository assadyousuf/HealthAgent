import os
import sys
from typing import List, Optional, Any, Dict

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

from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContextFrame

# Pipecat-flows imports
from pipecat_flows import (
    FlowManager,
    FlowConfig,
    FlowArgs,
    FlowResult,
    ContextStrategy,
    ContextStrategyConfig,
)

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


# --- Flow Result TypedDicts ---
class GenericFlowResult(FlowResult):
    success: bool
    message: Optional[str] = None
    next_node_override: Optional[str] = None


class DataCaptureResult(GenericFlowResult):
    data_captured: Optional[Dict[str, Any]] = None


# --- Handler Functions ---
async def initialize_flow_context(
    actual_action_config: dict, flow_manager_instance: FlowManager
):
    logger.info("Initializing flow context.")
    flow_manager_instance.state["patient_data"] = {}
    flow_manager_instance.state["current_appointment_offer_index"] = 0
    flow_manager_instance.state["available_appointments"] = AVAILABLE_APPOINTMENTS

    try:
        address_validator = AddressValidator(
            client_id=os.getenv("USPS_CLIENT_ID"),
            client_secret=os.getenv("USPS_CLIENT_SECRET"),
        )
        flow_manager_instance.state["address_validator"] = address_validator
        logger.info("AddressValidator initialized successfully and stored in context.")
    except ValueError as e:
        logger.warning(
            f"Failed to initialize AddressValidator: {e}. Address validation will be skipped."
        )
        flow_manager_instance.state["address_validator"] = None
    except Exception as e:
        logger.error(
            f"Unexpected error during AddressValidator init: {e}. Validation skipped."
        )
        flow_manager_instance.state["address_validator"] = None


async def record_generic_data(
    llm_args: Dict[str, Any],
    flow_manager: FlowManager,
    expected_keys: List[str],
    data_label: str,
) -> DataCaptureResult:
    captured_data = {}
    all_keys_present_and_valid = True

    logger.debug(
        f"[record_generic_data - {data_label}] Using LLM arguments: {llm_args}"
    )

    for key in expected_keys:
        value = llm_args.get(key)
        if value is not None:
            captured_data[key] = value
        else:
            logger.warning(
                f"[record_generic_data - {data_label}] Key '{key}' not found or is null in LLM arguments: {llm_args}."
            )
            all_keys_present_and_valid = False

    if captured_data and all_keys_present_and_valid:
        if flow_manager and hasattr(flow_manager, "state"):
            if "patient_data" not in flow_manager.state:
                logger.warning(
                    "[record_generic_data] Initializing 'patient_data' in flow_manager.state as it was missing."
                )
                flow_manager.state["patient_data"] = {}

            flow_manager.state["patient_data"].update(captured_data)
            logger.info(
                f"[record_generic_data - {data_label}] {data_label} recorded: {captured_data}. Patient data: {flow_manager.state['patient_data']}"
            )
            return DataCaptureResult(success=True, data_captured=captured_data)
        else:
            logger.error(
                f"[record_generic_data - {data_label}] FlowManager or its state attribute not available. Cannot save data."
            )
            return DataCaptureResult(
                success=False,
                message=f"Internal error: FlowManager state unavailable for {data_label}.",
            )

    missing_msg = f"Could not capture all required information for {data_label}."
    if not captured_data:
        missing_msg = f"No data provided or found for {data_label}."

    logger.warning(
        f"[record_generic_data - {data_label}] {missing_msg} LLM arguments used: {llm_args}"
    )
    return DataCaptureResult(success=False, message=missing_msg)


async def record_name(
    llm_args: Dict[str, Any], flow_manager: FlowManager
) -> DataCaptureResult:
    return await record_generic_data(llm_args, flow_manager, ["name"], "Name")


async def record_dob(
    llm_args: Dict[str, Any], flow_manager: FlowManager
) -> DataCaptureResult:
    return await record_generic_data(llm_args, flow_manager, ["dob"], "DOB")


async def record_payer_name(
    llm_args: Dict[str, Any], flow_manager: FlowManager
) -> DataCaptureResult:
    return await record_generic_data(
        llm_args, flow_manager, ["payer_name"], "Payer Name"
    )


async def record_member_id(
    llm_args: Dict[str, Any], flow_manager: FlowManager
) -> DataCaptureResult:
    return await record_generic_data(llm_args, flow_manager, ["member_id"], "Member ID")


async def record_referral_bool(args: FlowArgs) -> DataCaptureResult:
    patient_data = args["flow_manager"].context["patient_data"]
    function_args_dict = args.get("function_args", {})

    has_referral_arg = function_args_dict.get("referral_bool")
    physician_name_arg = function_args_dict.get("referral_physician_name")

    next_node_override = None
    success_capture = False

    current_data_snapshot = {}

    if isinstance(has_referral_arg, bool):
        patient_data["referral_bool"] = has_referral_arg
        current_data_snapshot["referral_bool"] = has_referral_arg
        logger.info(f"Referral status recorded: {has_referral_arg}")
        success_capture = True

        if has_referral_arg:
            if (
                physician_name_arg
                and isinstance(physician_name_arg, str)
                and physician_name_arg.strip()
            ):
                patient_data["referral_physician"] = physician_name_arg.strip()
                current_data_snapshot["referral_physician"] = patient_data[
                    "referral_physician"
                ]
                logger.info(
                    f"Referral physician name also captured: {patient_data['referral_physician']}"
                )
                next_node_override = "get_complaint"
            else:
                logger.info(
                    "Referral is true, physician name not provided. Transitioning to get_referral_physician."
                )
                next_node_override = "get_referral_physician"
        else:
            patient_data.pop("referral_physician", None)
            logger.info("No referral. Transitioning to get_complaint.")
            next_node_override = "get_complaint"
    elif (
        physician_name_arg
        and isinstance(physician_name_arg, str)
        and physician_name_arg.strip()
    ):
        # Physician name was provided, but referral_bool was not explicitly true/false (e.g., user just said "Dr. Smith").
        # Infer referral_bool as True.
        logger.info(
            f"Physician name '{physician_name_arg}' provided without explicit 'yes/no'. Inferring referral_bool=True."
        )
        patient_data["referral_bool"] = True
        current_data_snapshot["referral_bool"] = True

        patient_data["referral_physician"] = physician_name_arg.strip()
        current_data_snapshot["referral_physician"] = patient_data["referral_physician"]
        logger.info(
            f"Referral physician name captured: {patient_data['referral_physician']}"
        )

        success_capture = True
        next_node_override = "get_complaint"
    else:
        logger.warning(
            f"referral_bool missing or not a boolean, and no physician name provided. Function args: {function_args_dict}. Re-prompting at get_referral_bool."
        )
        success_capture = False
        next_node_override = "get_referral_bool"

    return DataCaptureResult(
        success=success_capture,
        data_captured=current_data_snapshot if success_capture else None,
        next_node_override=next_node_override,
    )


async def record_referral_physician(
    llm_args: Dict[str, Any], flow_manager: FlowManager
) -> DataCaptureResult:
    return await record_generic_data(
        llm_args, flow_manager, ["referral_physician"], "Referral Physician"
    )


async def record_complaint(
    llm_args: Dict[str, Any], flow_manager: FlowManager
) -> DataCaptureResult:
    return await record_generic_data(llm_args, flow_manager, ["complaint"], "Complaint")


async def record_and_validate_address(args: FlowArgs) -> DataCaptureResult:
    patient_data = args["flow_manager"].context["patient_data"]
    address_validator = args["flow_manager"].context.get("address_validator")
    function_args_dict = args.get("function_args", {})

    street = function_args_dict.get("address_street")
    city = function_args_dict.get("address_city")
    state_abbr = function_args_dict.get("address_state")
    zip_code = function_args_dict.get("address_zip")

    if not (street and city and state_abbr and zip_code):
        return DataCaptureResult(
            success=False,
            message="Missing one or more address components.",
            next_node_override="get_full_address",
        )

    current_address = {
        "address_street": street,
        "address_city": city,
        "address_state": state_abbr,
        "address_zip": zip_code,
    }
    patient_data.update(current_address)
    logger.info(f"Address components recorded: {current_address}")

    if address_validator:
        val_result = await address_validator.validate_address(
            street1=street, city=city, state=state_abbr, zip5=zip_code
        )
        logger.info(f"Address validation result: {val_result}")
        status = val_result.get("status")
        reason = val_result.get("reason", "Unknown validation issue.")
        validated_addr = val_result.get("validated_address")

        # Update patient_data with validated address if changes occurred or to standardize
        if validated_addr and status in ["VALID", "VALID_WITH_CHANGES"]:
            patient_data.update(
                {
                    "address_street": validated_addr.get("street1", street),
                    "address_city": validated_addr.get("city", city),
                    "address_state": validated_addr.get("state", state_abbr),
                    "address_zip": validated_addr.get("zip5", zip_code),
                }
            )

        if status == "VALID":
            patient_data["_address_validation_message"] = (
                "Your address has been validated successfully."
            )
            return DataCaptureResult(
                success=True,
                data_captured=patient_data,
                next_node_override="notify_address_validation_result",
            )
        elif status == "VALID_WITH_CHANGES":
            patient_data["_address_validation_message"] = (
                f"We validated your address with some corrections: {reason}"
            )
            return DataCaptureResult(
                success=True,
                data_captured=patient_data,
                next_node_override="notify_address_validation_result",
            )
        else:  # INVALID, AMBIGUOUS, API_ERROR etc.
            patient_data["_address_validation_error_reason"] = reason
            # Even if validation fails, data was 'captured', success is true for the capture part.
            # The next_node_override directs the flow to handle the validation failure.
            return DataCaptureResult(
                success=True,
                data_captured=current_address,
                next_node_override="address_validation_failed_prompt",
            )
    else:
        logger.warning("Address validator not configured. Skipping validation.")
        patient_data["_address_validation_message"] = "Address validation was skipped."
        return DataCaptureResult(
            success=True,
            data_captured=current_address,
            next_node_override="notify_address_validation_result",
        )


async def process_address_correction_choice(args: FlowArgs) -> DataCaptureResult:
    function_args_dict = args.get("function_args", {})
    choice = function_args_dict.get("user_choice")
    patient_data = args["flow_manager"].context["patient_data"]

    if choice == "correct_address":
        logger.info("User chose to correct the address.")
        for key in [
            "address_street",
            "address_city",
            "address_state",
            "address_zip",
            "_address_validation_message",
            "_address_validation_error_reason",
            "_address_validation_ack",
        ]:
            patient_data.pop(key, None)
        return DataCaptureResult(success=True, next_node_override="get_full_address")
    elif choice == "proceed_as_is":
        logger.info("User chose to proceed with the address as is.")
        patient_data["_address_validation_ack"] = (
            "User acknowledged potential address issues and wants to proceed."
        )
        return DataCaptureResult(
            success=True, next_node_override="notify_address_validation_result"
        )
    else:
        logger.warning(f"Address correction choice unclear: {choice}. Re-prompting.")
        return DataCaptureResult(
            success=False,
            message="Choice unclear.",
            next_node_override="address_validation_failed_prompt",
        )


async def record_phone(
    llm_args: Dict[str, Any], flow_manager: FlowManager
) -> DataCaptureResult:
    return await record_generic_data(llm_args, flow_manager, ["phone"], "Phone")


async def record_email_bool_preference(args: FlowArgs) -> DataCaptureResult:
    result = await record_generic_data(args, ["email_bool"], "Email Preference")
    if result.success and result.data_captured:
        if args["flow_manager"].context["patient_data"].get("email_bool") is True:
            result.next_node_override = "get_email_address"
        elif args["flow_manager"].context["patient_data"].get("email_bool") is False:
            result.next_node_override = "summarize_info"
        else:  # Should not happen if LLM provides boolean
            result.success = False
            result.message = "Email preference unclear (not boolean)."
            result.next_node_override = "get_email_bool"  # Re-ask
    elif not result.success:
        result.next_node_override = "get_email_bool"  # Re-ask if capture failed
    return result


async def record_email_address(
    llm_args: Dict[str, Any], flow_manager: FlowManager
) -> DataCaptureResult:
    return await record_generic_data(
        llm_args, flow_manager, ["email_address"], "Email Address"
    )


async def process_confirmation(args: FlowArgs) -> DataCaptureResult:
    function_args_dict = args.get("function_args", {})
    confirmed = function_args_dict.get("confirmed")
    correction_field = function_args_dict.get("correction_needed_field")
    patient_data = args["flow_manager"].context["patient_data"]

    if confirmed is True:
        patient_data.pop("_correction_hint", None)
        return DataCaptureResult(success=True, next_node_override="offer_appointments")
    elif confirmed is False:
        patient_data["_correction_hint"] = (
            correction_field if correction_field else "something"
        )
        return DataCaptureResult(success=True, next_node_override="ask_what_to_correct")
    else:
        logger.warning("Confirmation unclear (not True/False). Re-summarizing.")
        return DataCaptureResult(
            success=False,
            message="Confirmation status unclear.",
            next_node_override="summarize_info",
        )


async def process_correction_choice(args: FlowArgs) -> DataCaptureResult:
    function_args_dict = args.get("function_args", {})
    field_key_input = function_args_dict.get("field_to_correct", "").lower()
    patient_data = args["flow_manager"].context["patient_data"]

    field_to_node_map = {
        "name": "get_name",
        "full name": "get_name",
        "date of birth": "get_dob",
        "dob": "get_dob",
        "insurance": "get_payer_name",
        "payer name": "get_payer_name",
        "insurance provider": "get_payer_name",
        "member id": "get_member_id",
        "insurance id": "get_member_id",
        "referral": "get_referral_bool",
        "referring physician": "get_referral_physician",
        "complaint": "get_complaint",
        "reason for visit": "get_complaint",
        "address": "get_full_address",
        "phone": "get_phone",
        "phone number": "get_phone",
        "email": "get_email_address",
        "email address": "get_email_address",
    }
    target_node = field_to_node_map.get(field_key_input)

    if target_node:
        logger.info(
            f"User wants to correct: {field_key_input}. Transitioning to {target_node}"
        )
        # Simplified clearing logic - clear based on target node's typical data
        if target_node == "get_name":
            patient_data.pop("name", None)
        elif target_node == "get_dob":
            patient_data.pop("dob", None)
        elif target_node == "get_payer_name":
            patient_data.pop("payer_name", None)
        elif target_node == "get_member_id":
            patient_data.pop("member_id", None)
        elif target_node == "get_referral_bool":
            patient_data.pop("referral_bool", None)
            patient_data.pop("referral_physician", None)
        elif target_node == "get_referral_physician":
            patient_data.pop("referral_physician", None)
        elif target_node == "get_complaint":
            patient_data.pop("complaint", None)
        elif target_node == "get_full_address":
            for k in [
                "address_street",
                "address_city",
                "address_state",
                "address_zip",
                "_address_validation_message",
                "_address_validation_error_reason",
                "_address_validation_ack",
            ]:
                patient_data.pop(k, None)
        elif target_node == "get_phone":
            patient_data.pop("phone", None)
        elif target_node == "get_email_address":
            patient_data.pop("email_address", None)
            patient_data.pop("email_bool", None)

        return DataCaptureResult(success=True, next_node_override=target_node)
    else:
        patient_data["_correction_hint"] = (
            f"I didn't quite understand that '{field_key_input}' was the item to correct."
        )
        return DataCaptureResult(
            success=False,
            message=f"Unknown field to correct: {field_key_input}.",
            next_node_override="ask_what_to_correct",
        )


async def handle_appointment_choice(args: FlowArgs) -> DataCaptureResult:
    function_args_dict = args.get("function_args", {})
    accepted = function_args_dict.get("appointment_accepted")
    patient_data = args["flow_manager"].context["patient_data"]
    offer_idx = args["flow_manager"].context.get(
        "_currently_offered_appointment_index", -1
    )
    available_appts = args["flow_manager"].context["available_appointments"]

    if not (0 <= offer_idx < len(available_appts)):
        logger.error(
            "Error in appointment choice: Invalid or missing _currently_offered_appointment_index."
        )
        args["flow_manager"].context["current_appointment_offer_index"] = 0
        return DataCaptureResult(
            success=False,
            message="Internal error processing appointment choice.",
            next_node_override="offer_appointments",
        )

    offered_appt_details = available_appts[offer_idx]
    if accepted is True:
        patient_data["appointment"] = offered_appt_details
        logger.info(f"Appointment accepted: {offered_appt_details}")
        return DataCaptureResult(
            success=True, next_node_override="conclude_conversation"
        )
    elif accepted is False:
        logger.info(f"Appointment declined: {offered_appt_details}")
        return DataCaptureResult(success=True, next_node_override="offer_appointments")
    else:
        logger.warning(
            "Appointment choice unclear (not True/False). Re-offering same appointment."
        )
        args["flow_manager"].context["current_appointment_offer_index"] = offer_idx
        return DataCaptureResult(
            success=False,
            message="Choice unclear.",
            next_node_override="offer_appointments",
        )


async def no_suitable_appointment_handler(args: FlowArgs) -> GenericFlowResult:
    args["flow_manager"].context["patient_data"][
        "appointment"
    ] = "Declined all/None suitable"
    logger.info("No suitable appointment found or all declined.")
    return GenericFlowResult(success=True, next_node_override="conclude_conversation")


async def end_call_handler(args: FlowArgs) -> GenericFlowResult:
    logger.info("Call ending process initiated by LLM function call.")
    return GenericFlowResult(
        success=True
    )  # Transition to final_termination_node will handle actual end


# Handler for offer_appointments pre_action
async def prepare_appointment_offer_message_handler(
    args: FlowArgs,
) -> GenericFlowResult:
    idx = args["flow_manager"].context.get("current_appointment_offer_index", 0)
    appts = args["flow_manager"].context["available_appointments"]

    if idx < len(appts):
        appt = appts[idx]
        args["flow_manager"].context[
            "_current_appointment_task_message"
        ] = f"We have an opening with {appt['doctor']} on {appt['day']} at {appt['time']}. Would that work for you?"
        args["flow_manager"].context["_currently_offered_appointment_index"] = idx
        args["flow_manager"].context["current_appointment_offer_index"] = idx + 1
        args["flow_manager"].context["_offering_an_appointment_now"] = True
    else:
        args["flow_manager"].context[
            "_current_appointment_task_message"
        ] = "Those are all the currently available slots I see. Unfortunately, we couldn't find a suitable time. Please select the 'no_appointment_found_or_all_declined' option to proceed."
        args["flow_manager"].context["_currently_offered_appointment_index"] = -1
        args["flow_manager"].context["_offering_an_appointment_now"] = False
    return GenericFlowResult(success=True)


async def prepare_name_spelling_confirmation_message(
    actual_action_config: dict, flow_manager: FlowManager
) -> GenericFlowResult:
    """
    Prepares and speaks the name spelling confirmation message using OpenAILLMContextFrame.
    Adapts message if explicit correction is needed.
    """
    patient_data = flow_manager.state.get("patient_data", {})
    patient_name = patient_data.get("name")
    needs_explicit_correction = flow_manager.state.get(
        "_name_correction_needed_flag", False
    )

    if needs_explicit_correction:
        message_to_speak = "My apologies for the trouble. Could you please spell out your full name for me now?"
        flow_manager.state["_name_correction_needed_flag"] = False
    elif not patient_name:
        logger.warning(
            "Patient name not found in state for spelling confirmation pre-action."
        )
        message_to_speak = "I seem to have missed your name. Could you please spell out your full name for me?"
    else:
        spelled_out_name = " ".join(list(patient_name.upper()))
        message_to_speak = (
            f"{spelled_out_name}. "
            "Is that spelling correct? If not, please tell me the correct full name, or if it is correct, just confirm."
        )

    await flow_manager.task.queue_frame(
        OpenAILLMContextFrame(
            context=OpenAILLMContext(
                messages=[{"role": "system", "content": message_to_speak}]
            )
        )
    )
    logger.info(
        f"OpenAILLMContextFrame queued for name spelling/correction: {message_to_speak}"
    )

    # Add a message to the context to indicate we asked a question
    await flow_manager.task.queue_frame(
        OpenAILLMContextFrame(
            context=OpenAILLMContext(
                messages=[{"role": "system", "content": message_to_speak}]
            )
        )
    )

    return GenericFlowResult(success=True)


async def process_name_spelling_confirmation(
    llm_args: Dict[str, Any], flow_manager: FlowManager
) -> DataCaptureResult:
    logger.debug(f"Processing name spelling confirmation. LLM args: {llm_args}")
    patient_data = flow_manager.state["patient_data"]

    spelling_correct = llm_args.get("spelling_correct")
    corrected_full_name = llm_args.get("corrected_full_name")

    if spelling_correct is True:
        logger.info(f"Name spelling confirmed for: {patient_data.get('name')}")
        flow_manager.state["_name_correction_needed_flag"] = (
            False  # Ensure flag is clear
        )
        return DataCaptureResult(
            success=True, data_captured={"name": patient_data.get("name")}
        )  # Proceeds to get_dob by default
    elif spelling_correct is False:
        # Check if a valid-looking corrected name was actually provided
        if (
            corrected_full_name
            and isinstance(corrected_full_name, str)
            and corrected_full_name.strip()
            and len(corrected_full_name.strip().split())
            >= 1  # Basic check: at least one word
            and not any(
                kw in corrected_full_name.lower()
                for kw in ["no", "not", "wrong", "incorrect"]
            )  # Avoid common negative phrases
        ):
            old_name = patient_data.get("name", "[unknown]")
            new_name = corrected_full_name.strip()
            patient_data["name"] = new_name
            logger.info(f"Name corrected from '{old_name}' to '{new_name}'.")
            flow_manager.state["_name_correction_needed_flag"] = False  # Clear flag
            # Set flag to indicate we need to confirm the corrected spelling
            flow_manager.state["_corrected_name_needs_confirmation"] = True
            return DataCaptureResult(
                success=True,
                data_captured={"name": new_name},
                next_node_override="confirm_corrected_spelling",
            )
        else:
            # User said spelling is incorrect, but didn't provide a usable correction, or LLM misfired.
            logger.info(
                "Spelling incorrect, but no valid corrected name provided. Setting flag to ask for explicit correction."
            )
            flow_manager.state["_name_correction_needed_flag"] = True
            return DataCaptureResult(
                success=True,
                message="Spelling incorrect, requesting explicit correction.",
                next_node_override="confirm_name_spelling_or_request_correction",
            )
    else:
        # spelling_correct is None or not a boolean - LLM failed to provide clear decision.
        logger.warning(
            f"LLM did not provide clear spelling_correct value ({spelling_correct}). Re-prompting for confirmation."
        )
        flow_manager.state["_name_correction_needed_flag"] = (
            False  # Reset to normal confirmation prompt
        )
        return DataCaptureResult(
            success=True,
            message="Confirmation unclear.",
            next_node_override="confirm_name_spelling_or_request_correction",
        )


async def confirm_corrected_spelling_handler(
    llm_args: Dict[str, Any], flow_manager: FlowManager
) -> DataCaptureResult:
    """
    Simple handler that transitions to get_dob after corrected spelling confirmation.
    """
    logger.info("Corrected spelling has been confirmed. Proceeding to get_dob.")
    flow_manager.state["_corrected_name_needs_confirmation"] = False  # Clear flag
    return DataCaptureResult(success=True)


async def prepare_corrected_spelling_confirmation_message(
    actual_action_config: dict, flow_manager: FlowManager
) -> GenericFlowResult:
    """
    Prepares and speaks verbal confirmation of the corrected name.
    """
    patient_data = flow_manager.state.get("patient_data", {})
    patient_name = patient_data.get("name", "your name")

    message_to_speak = f"Thank you for the correction. I now have your name as {patient_name}. Let me continue with a few more questions."

    await flow_manager.task.queue_frame(
        OpenAILLMContextFrame(
            context=OpenAILLMContext(
                messages=[{"role": "system", "content": message_to_speak}]
            )
        )
    )
    logger.info(
        f"OpenAILLMContextFrame queued for corrected spelling confirmation: {message_to_speak}"
    )

    return GenericFlowResult(success=True)


# --- Flow Configuration ---
"""flow_config: FlowConfig = {
    "initial_node": "greeting",
    "nodes": {
        "greeting": {
            "pre_actions": [
                {"type": "initialize_flow_context"},
            ],
            "role_messages": [{"role": "system", "content": BASE_SYSTEM_PROMPT}],
            "task_messages": [
                {
                    "role": "system",
                    "content": "Start by introducing yourself (virtual assistant) and the clinic (AssortHealth). Then, ask for the patient's full name.",
                }
            ],
            "functions": [
                {
                    "type": "function",
                    "function": {
                        "name": "capture_name",
                        "handler": record_name,
                        "description": "Captures the patient's full name.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": "The patient's full name.",
                                }
                            },
                            "required": ["name"],
                        },
                        "transition_to": "confirm_name_spelling_or_request_correction",
                    },
                }
            ],
        },
        "confirm_name_spelling_or_request_correction": {
            "pre_actions": [{"type": "prepare_name_spelling_confirmation_message"}],
            "role_messages": [{"role": "system", "content": BASE_SYSTEM_PROMPT}],
            "task_messages": [
                {
                    "role": "system",
                    "content": "A question about name spelling has just been asked to the user via TTS. DO NOT repeat the question or generate any response. Simply wait for the user's response, then analyze their answer to determine if the spelling is correct or if they're providing a corrected name. Call the process_name_spelling_confirmation function ONLY after the user responds.",
                }
            ],
            "context_strategy": ContextStrategyConfig(strategy=ContextStrategy.APPEND),
            "functions": [
                {
                    "type": "function",
                    "function": {
                        "name": "process_name_spelling_confirmation",
                        "handler": process_name_spelling_confirmation,
                        "description": "Processes the user's response regarding the name spelling. Call this ONLY after the user has responded to the spelling question.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "spelling_correct": {
                                    "type": "boolean",
                                    "description": "True if the user confirms the current spelling is correct. False if they indicate it is incorrect.",
                                },
                                "corrected_full_name": {
                                    "type": ["string", "null"],
                                    "description": "The user's correctly spelled full name, ONLY IF they explicitly provide it after indicating the spelling is incorrect.",
                                },
                            },
                            "required": ["spelling_correct"],
                        },
                        "transition_to": "get_dob",
                    },
                }
            ],
        },
        "confirm_corrected_spelling": {
            "pre_actions": [
                {"type": "prepare_corrected_spelling_confirmation_message"}
            ],
            "role_messages": [{"role": "system", "content": BASE_SYSTEM_PROMPT}],
            "task_messages": [
                {
                    "role": "system",
                    "content": "The corrected name has been acknowledged via TTS. No further response is needed. Simply call the confirm_corrected_spelling function to proceed.",
                }
            ],
            "functions": [
                {
                    "type": "function",
                    "function": {
                        "name": "confirm_corrected_spelling",
                        "handler": confirm_corrected_spelling_handler,
                        "description": "Confirms the corrected spelling and proceeds to the next step.",
                        "parameters": {"type": "object", "properties": {}},
                        "transition_to": "get_dob",
                    },
                }
            ],
        },
        "get_dob": {
            "task_messages": [
                {
                    "role": "system",
                    "content": "Thank the patient by name (use name from context if available). Ask for their date of birth (month, day, and year).",
                }
            ],
            "functions": [
                {
                    "type": "function",
                    "function": {
                        "name": "capture_dob",
                        "handler": record_dob,
                        "description": "Captures date of birth. Try to format as YYYY-MM-DD.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "dob": {
                                    "type": "string",
                                    "description": "Patient's date of birth (e.g., YYYY-MM-DD or 'January first nineteen eighty three').",
                                }
                            },
                            "required": ["dob"],
                        },
                        "transition_to": "get_payer_name",
                    },
                }
            ],
        },
        "get_payer_name": {
            "task_messages": [
                {
                    "role": "system",
                    "content": "Ask for the name of the patient's insurance provider. Give examples like Blue Cross or Aetna.",
                }
            ],
            "functions": [
                {
                    "type": "function",
                    "function": {
                        "name": "capture_payer_name",
                        "handler": record_payer_name,
                        "description": "Captures insurance payer name.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "payer_name": {
                                    "type": "string",
                                    "description": "Name of the insurance payer.",
                                }
                            },
                            "required": ["payer_name"],
                        },
                        "transition_to": "get_member_id",
                    },
                }
            ],
        },
        "get_member_id": {
            "task_messages": [
                {
                    "role": "system",
                    "content": "Ask for their member ID for the insurance they mentioned (use payer name from context).",
                }
            ],
            "functions": [
                {
                    "type": "function",
                    "function": {
                        "name": "capture_member_id",
                        "handler": record_member_id,
                        "description": "Captures insurance member ID.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "member_id": {
                                    "type": "string",
                                    "description": "The insurance member ID.",
                                }
                            },
                            "required": ["member_id"],
                        },
                        "transition_to": "get_referral_bool",
                    },
                }
            ],
        },
        "get_referral_bool": {
            "task_messages": [
                {
                    "role": "system",
                    "content": "Ask if they have a referral from another physician. If they only provide a physician's name, assume they mean 'yes' they have a referral. You must capture both the referral status (true/false for 'yes'/'no') and, if applicable, the physician's name.",
                }
            ],
            "functions": [
                {
                    "type": "function",
                    "function": {
                        "name": "capture_referral_status",
                        "handler": record_referral_bool,
                        "description": "Determines if user has a referral. Optionally captures physician name if provided simultaneously. If only a physician name is given, infer referral status as true.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "referral_bool": {
                                    "type": "boolean",
                                    "description": "True if patient has a referral, false otherwise. Infer as true if a physician's name is provided without an explicit yes/no.",
                                },
                                "referral_physician_name": {
                                    "type": "string",
                                    "description": "Referring physician's name, if mentioned along with the referral status or by itself.",
                                },
                            },
                            "required": ["referral_bool"],
                        },
                    },
                }
            ],
        },
        "get_referral_physician": {
            "task_messages": [
                {
                    "role": "system",
                    "content": "The patient has a referral. Ask for the full name of the referring physician.",
                }
            ],
            "functions": [
                {
                    "type": "function",
                    "function": {
                        "name": "capture_referral_physician_name",
                        "handler": record_referral_physician,
                        "description": "Captures referring physician's full name.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "referral_physician": {
                                    "type": "string",
                                    "description": "Full name of referring physician.",
                                }
                            },
                            "required": ["referral_physician"],
                        },
                        "transition_to": "get_complaint",
                    },
                }
            ],
        },
        "get_complaint": {
            "task_messages": [
                {
                    "role": "system",
                    "content": "Ask for their chief medical complaint or reason for their visit.",
                }
            ],
            "functions": [
                {
                    "type": "function",
                    "function": {
                        "name": "capture_complaint",
                        "handler": record_complaint,
                        "description": "Captures chief medical complaint.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "complaint": {
                                    "type": "string",
                                    "description": "Patient's chief complaint/reason for visit.",
                                }
                            },
                            "required": ["complaint"],
                        },
                        "transition_to": "get_full_address",
                    },
                }
            ],
        },
        "get_full_address": {
            "task_messages": [
                {
                    "role": "system",
                    "content": "Ask for their full mailing address: street, city, state, and ZIP code.",
                }
            ],
            "functions": [
                {
                    "type": "function",
                    "function": {
                        "name": "capture_full_address",
                        "handler": record_and_validate_address,
                        "description": "Captures street, city, state (2-letter abbr), and 5-digit ZIP. Validates it.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "address_street": {
                                    "type": "string",
                                    "description": "Full street address.",
                                },
                                "address_city": {
                                    "type": "string",
                                    "description": "City name.",
                                },
                                "address_state": {
                                    "type": "string",
                                    "description": "State (2-letter abbreviation).",
                                },
                                "address_zip": {
                                    "type": "string",
                                    "description": "5-digit ZIP code.",
                                },
                            },
                            "required": [
                                "address_street",
                                "address_city",
                                "address_state",
                                "address_zip",
                            ],
                        },
                    },
                }
            ],
        },
        "notify_address_validation_result": {
            "task_messages": [
                {
                    "role": "system",
                    "content": "Acknowledge the address information (using validation message from context: patient_data._address_validation_message or patient_data._address_validation_ack). Then, ask for their primary phone number.",
                }
            ],
            "functions": [
                {
                    "type": "function",
                    "function": {
                        "name": "capture_phone_after_address",
                        "handler": record_phone,
                        "description": "Captures primary phone number.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "phone": {
                                    "type": "string",
                                    "description": "Patient's primary phone number.",
                                }
                            },
                            "required": ["phone"],
                        },
                        "transition_to": "get_email_bool",
                    },
                }
            ],
        },
        "address_validation_failed_prompt": {
            "task_messages": [
                {
                    "role": "system",
                    "content": "Inform patient about address validation issue (using patient_data._address_validation_error_reason). Ask if they want to correct address or proceed as provided.",
                }
            ],
            "functions": [
                {
                    "type": "function",
                    "function": {
                        "name": "choose_address_correction_action",
                        "handler": process_address_correction_choice,
                        "description": "User choice: correct address or proceed as is.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "user_choice": {
                                    "type": "string",
                                    "enum": ["correct_address", "proceed_as_is"],
                                    "description": "'correct_address' or 'proceed_as_is'.",
                                }
                            },
                            "required": ["user_choice"],
                        },
                    },
                }
            ],
        },
        "get_phone": {
            "task_messages": [
                {"role": "system", "content": "What is your primary phone number?"}
            ],
            "functions": [
                {
                    "type": "function",
                    "function": {
                        "name": "capture_phone_generic",
                        "handler": record_phone,
                        "description": "Captures primary phone number.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "phone": {
                                    "type": "string",
                                    "description": "Patient's primary phone number.",
                                }
                            },
                            "required": ["phone"],
                        },
                        "transition_to": "get_email_bool",  # Default, assuming correction flow might lead here then continue standard flow
                    },
                }
            ],
        },
        "get_email_bool": {
            "task_messages": [
                {
                    "role": "system",
                    "content": "Would you like to provide an email address? This is optional.",
                }
            ],
            "functions": [
                {
                    "type": "function",
                    "function": {
                        "name": "capture_email_preference",
                        "handler": record_email_bool_preference,
                        "description": "Determines if user wants to provide email.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "email_bool": {
                                    "type": "boolean",
                                    "description": "True to provide email, false otherwise.",
                                }
                            },
                            "required": ["email_bool"],
                        },
                    },
                }
            ],
        },
        "get_email_address": {
            "task_messages": [
                {"role": "system", "content": "Okay, what is your email address?"}
            ],
            "functions": [
                {
                    "type": "function",
                    "function": {
                        "name": "capture_email_address",
                        "handler": record_email_address,
                        "description": "Captures email address.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "email_address": {
                                    "type": "string",
                                    "description": "Patient's email address.",
                                }
                            },
                            "required": ["email_address"],
                        },
                        "transition_to": "summarize_info",
                    },
                }
            ],
        },
        "summarize_info": {
            "task_messages": [
                {
                    "role": "system",
                    "content": "Now, please summarize all the information collected from the patient: name, DOB, insurance (payer & ID), referral status (and physician if any), complaint, full address, phone, and email (if provided). After summarizing, ask 'Is all of this information correct?'",
                }
            ],
            "context_strategy": ContextStrategyConfig(strategy=ContextStrategy.APPEND),
            "functions": [
                {
                    "type": "function",
                    "function": {
                        "name": "confirm_information",
                        "handler": process_confirmation,
                        "description": "Processes user's confirmation. If not confirmed, identifies field for correction.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "confirmed": {
                                    "type": "boolean",
                                    "description": "True if info is correct, false otherwise.",
                                },
                                "correction_needed_field": {
                                    "type": "string",
                                    "description": "Field to correct (e.g. 'name', 'address'), if not confirmed. Optional.",
                                },
                            },
                            "required": ["confirmed"],
                        },
                    },
                }
            ],
        },
        "ask_what_to_correct": {
            "task_messages": [
                {
                    "role": "system",
                    "content": "The patient said some information was incorrect. Use hint from context.patient_data._correction_hint if available. Ask what specific part they'd like to correct (e.g., name, address, phone).",
                }
            ],
            "context_strategy": ContextStrategyConfig(strategy=ContextStrategy.APPEND),
            "functions": [
                {
                    "type": "function",
                    "function": {
                        "name": "select_field_to_correct",
                        "handler": process_correction_choice,
                        "description": "Identifies which field user wants to correct from a list of valid fields (e.g. name, dob, address, phone, email, referral, complaint, insurance, member id).",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "field_to_correct": {
                                    "type": "string",
                                    "description": "The field user wants to correct. Should match one of the keywords for known fields.",
                                }
                            },
                            "required": ["field_to_correct"],
                        },
                    },
                }
            ],
        },
        "offer_appointments": {
            "pre_actions": [
                {
                    "type": "prepare_appointment_offer_message_handler",
                }
            ],
            "task_messages": [
                {
                    "role": "system",
                    "content": "{{context._current_appointment_task_message}}",
                }
            ],
            "context_strategy": ContextStrategyConfig(
                strategy=ContextStrategy.APPEND
            ),  # Enable templating
            "functions": [
                {
                    "type": "function",
                    "function": {
                        "name": "process_appointment_acceptance",
                        "handler": handle_appointment_choice,
                        "description": "Processes if patient accepted the offered appointment. Only call if an appointment was actually offered.",
                        "parameters": {
                            "type": "object",
                            "properties": {"appointment_accepted": {"type": "boolean"}},
                            "required": ["appointment_accepted"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "no_appointment_found_or_all_declined",
                        "handler": no_suitable_appointment_handler,
                        "description": "Handles the case where no appointments are left or suitable, as per the system's instruction. Call this if the system told you no appointments are available.",
                        "parameters": {"type": "object", "properties": {}},
                    },
                },
            ],
        },
        "conclude_conversation": {
            "task_messages": [
                {
                    "role": "system",
                    "content": "Conclude the call. If an appointment was booked (check patient_data.appointment in your context), confirm it. Otherwise, if they declined all or none were suitable, acknowledge that. Always end with 'Thank you for calling AssortHealth. Goodbye.' Then call the 'end_the_call' function.",
                }
            ],
            "context_strategy": ContextStrategyConfig(strategy=ContextStrategy.APPEND),
            "functions": [
                {
                    "type": "function",
                    "function": {
                        "name": "end_the_call",
                        "handler": end_call_handler,
                        "description": "Signals system to end the call.",
                        "parameters": {"type": "object", "properties": {}},
                        "transition_to": "final_termination_node",
                    },
                }
            ],
        },
        "final_termination_node": {"post_actions": [{"type": "end_conversation"}]},
    },
}
"""


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

    flow_manager.register_action("initialize_flow_context", initialize_flow_context)
    flow_manager.register_action(
        "prepare_appointment_offer_message_handler",
        prepare_appointment_offer_message_handler,
    )
    flow_manager.register_action(
        "prepare_name_spelling_confirmation_message",
        prepare_name_spelling_confirmation_message,
    )
    flow_manager.register_action(
        "prepare_corrected_spelling_confirmation_message",
        prepare_corrected_spelling_confirmation_message,
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
