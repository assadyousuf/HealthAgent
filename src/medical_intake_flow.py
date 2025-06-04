#
# Patient Intake Pipeline using Pipecat Dynamic Flows with OpenAI
#
# This pipeline collects patient information with confirmation steps:
# - First name (with spelling confirmation)
# - Last name (with spelling confirmation)
# - Payer name (with spelling confirmation)
# - Payer ID (with confirmation)
# - Referral information (optional)
# - Chief medical complaint
# - Address (with validation)
# - Contact information
# - Provider appointment scheduling
#

import asyncio
import sys
from pathlib import Path
from typing import Dict


from dotenv import load_dotenv
from loguru import logger


from pipecat_flows import (
    FlowArgs,
    FlowManager,
    FlowResult,
    FlowsFunctionSchema,
    NodeConfig,
)

sys.path.append(str(Path(__file__).parent.parent))

load_dotenv(override=True)


# Helper function to convert spaced letters to word
def spaced_letters_to_word(spaced_text: str) -> str:
    """Convert spaced letters like 'a s a d' to 'asad'."""
    # Remove spaces and convert to lowercase
    return spaced_text.replace(" ", "").lower()


# Helper function to remove spaces (preserving case)
def remove_spaces(spaced_text: str) -> str:
    """Remove spaces from text like '1 2 3' to '123' or 'N Y' to 'NY'."""
    return spaced_text.replace(" ", "")


# Helper function to format address for character-by-character spelling
def format_address_for_spelling(address: str) -> str:
    """Format address for character-by-character spelling, preserving structure."""
    result = []
    for char in address:
        if char == " ":
            # Keep spaces to maintain word boundaries
            result.append("  ")  # Double space for clearer pauses
        elif char == ",":
            result.append(" comma ")
        elif char.isalnum():
            result.append(char.upper())
        # Skip other punctuation
    return " ".join(result)


# Mock address validation service
class MockAddressValidator:
    """Simulates an address validation service."""

    def __init__(self):
        # Define some valid zip codes for testing
        self.valid_zip_codes = {
            "10001": "New York",
            "90210": "Beverly Hills",
            "60601": "Chicago",
            "02139": "Cambridge",
            "94105": "San Francisco",
        }

    async def validate_address(self, street: str, city: str, zip_code: str) -> bool:
        """Mock address validation - returns True if zip code matches city."""
        await asyncio.sleep(0.5)  # Simulate API call delay
        return True


# Mock provider schedule
AVAILABLE_TIMES = [
    "Monday, December 18 at 9:00 AM",
    "Monday, December 18 at 10:30 AM",
    "Tuesday, December 19 at 2:00 PM",
    "Wednesday, December 20 at 11:00 AM",
    "Thursday, December 21 at 3:30 PM",
]

# Initialize validators
address_validator = MockAddressValidator()


# Result types
class NameResult(FlowResult):
    name: str


class SpellingConfirmationResult(FlowResult):
    confirmed: bool
    corrected_spelling: str


class PayerIdResult(FlowResult):
    payer_id: int


class PayerIdConfirmationResult(FlowResult):
    confirmed: bool
    corrected_id: int


class ReferralStatusResult(FlowResult):
    has_referral: bool


class ComplaintResult(FlowResult):
    complaint: str


class AddressResult(FlowResult):
    street: str
    city: str
    zip_code: str
    is_valid: bool


class AddressComponentResult(FlowResult):
    value: str


class ContactResult(FlowResult):
    contact_info: str


class AppointmentResult(FlowResult):
    selected_time: str


# Function handlers
async def collect_first_name(args: FlowArgs) -> NameResult:
    """Collect patient's first name."""
    return NameResult(name=args["first_name"])


async def confirm_first_name_spelling(args: FlowArgs) -> SpellingConfirmationResult:
    """Confirm first name spelling."""
    return SpellingConfirmationResult(
        confirmed=args["confirmed"],
        corrected_spelling=args.get("corrected_spelling", ""),
    )


async def collect_last_name(args: FlowArgs) -> NameResult:
    """Collect patient's last name."""
    return NameResult(name=args["last_name"])


async def confirm_last_name_spelling(args: FlowArgs) -> SpellingConfirmationResult:
    """Confirm last name spelling."""
    return SpellingConfirmationResult(
        confirmed=args["confirmed"],
        corrected_spelling=args.get("corrected_spelling", ""),
    )


async def collect_payer_name(args: FlowArgs) -> NameResult:
    """Collect insurance payer name."""
    return NameResult(name=args["payer_name"])


async def confirm_payer_spelling(args: FlowArgs) -> SpellingConfirmationResult:
    """Confirm payer name spelling."""
    return SpellingConfirmationResult(
        confirmed=args["confirmed"],
        corrected_spelling=args.get("corrected_spelling", ""),
    )


async def collect_payer_id(args: FlowArgs) -> PayerIdResult:
    """Collect payer ID number."""
    payer_id_str = args["payer_id"]
    # Convert string to integer, removing any spaces first
    try:
        # Remove spaces and convert to int
        payer_id_int = int(remove_spaces(str(payer_id_str)))
        return PayerIdResult(payer_id=payer_id_int)
    except (ValueError, TypeError):
        # If conversion fails, try to extract just numbers
        numbers_only = "".join(filter(str.isdigit, str(payer_id_str)))
        if numbers_only:
            return PayerIdResult(payer_id=int(numbers_only))
        else:
            # Default to 0 if no valid number found
            return PayerIdResult(payer_id=0)


async def confirm_payer_id(args: FlowArgs) -> PayerIdConfirmationResult:
    """Confirm payer ID number."""
    confirmed = args["confirmed"]
    corrected_id_str = args.get("corrected_id", "")

    if corrected_id_str:
        try:
            # Remove spaces and convert to int
            corrected_id_int = int(remove_spaces(str(corrected_id_str)))
            return PayerIdConfirmationResult(
                confirmed=confirmed, corrected_id=corrected_id_int
            )
        except (ValueError, TypeError):
            # If conversion fails, try to extract just numbers
            numbers_only = "".join(filter(str.isdigit, str(corrected_id_str)))
            if numbers_only:
                return PayerIdConfirmationResult(
                    confirmed=confirmed, corrected_id=int(numbers_only)
                )
            else:
                # Default to 0 if no valid number found
                return PayerIdConfirmationResult(confirmed=confirmed, corrected_id=0)
    else:
        # No correction provided, return 0
        return PayerIdConfirmationResult(confirmed=confirmed, corrected_id=0)


async def check_referral_status(args: FlowArgs) -> ReferralStatusResult:
    """Check if patient has a referral."""
    return ReferralStatusResult(has_referral=args["has_referral"])


async def collect_physician_first_name(args: FlowArgs) -> NameResult:
    """Collect referring physician's first name."""
    return NameResult(name=args["physician_first_name"])


async def confirm_physician_first_name_spelling(
    args: FlowArgs,
) -> SpellingConfirmationResult:
    """Confirm physician first name spelling."""
    return SpellingConfirmationResult(
        confirmed=args["confirmed"],
        corrected_spelling=args.get("corrected_spelling", ""),
    )


async def collect_physician_last_name(args: FlowArgs) -> NameResult:
    """Collect referring physician's last name."""
    return NameResult(name=args["physician_last_name"])


async def confirm_physician_last_name_spelling(
    args: FlowArgs,
) -> SpellingConfirmationResult:
    """Confirm physician last name spelling."""
    return SpellingConfirmationResult(
        confirmed=args["confirmed"],
        corrected_spelling=args.get("corrected_spelling", ""),
    )


async def collect_chief_complaint(args: FlowArgs) -> ComplaintResult:
    """Collect chief medical complaint."""
    return ComplaintResult(complaint=args["complaint"])


async def collect_full_address(args: FlowArgs) -> AddressComponentResult:
    """Collect full address."""
    return AddressComponentResult(value=args["address"])


async def confirm_full_address(args: FlowArgs) -> SpellingConfirmationResult:
    """Confirm full address."""
    return SpellingConfirmationResult(
        confirmed=args["confirmed"],
        corrected_spelling=args.get("corrected_address", ""),
    )


async def collect_house_number(args: FlowArgs) -> AddressComponentResult:
    """Collect house number."""
    return AddressComponentResult(value=args["house_number"])


async def confirm_house_number(args: FlowArgs) -> SpellingConfirmationResult:
    """Confirm house number."""
    return SpellingConfirmationResult(
        confirmed=args["confirmed"],
        corrected_spelling=args.get("corrected_spelling", ""),
    )


async def collect_street_name(args: FlowArgs) -> AddressComponentResult:
    """Collect street name."""
    return AddressComponentResult(value=args["street_name"])


async def confirm_street_name_spelling(args: FlowArgs) -> SpellingConfirmationResult:
    """Confirm street name spelling."""
    return SpellingConfirmationResult(
        confirmed=args["confirmed"],
        corrected_spelling=args.get("corrected_spelling", ""),
    )


async def collect_city(args: FlowArgs) -> AddressComponentResult:
    """Collect city name."""
    return AddressComponentResult(value=args["city"])


async def confirm_city_spelling(args: FlowArgs) -> SpellingConfirmationResult:
    """Confirm city spelling."""
    return SpellingConfirmationResult(
        confirmed=args["confirmed"],
        corrected_spelling=args.get("corrected_spelling", ""),
    )


async def collect_state(args: FlowArgs) -> AddressComponentResult:
    """Collect state."""
    return AddressComponentResult(value=args["state"])


async def confirm_state_spelling(args: FlowArgs) -> SpellingConfirmationResult:
    """Confirm state spelling."""
    return SpellingConfirmationResult(
        confirmed=args["confirmed"],
        corrected_spelling=args.get("corrected_spelling", ""),
    )


async def collect_zip_code(args: FlowArgs) -> AddressComponentResult:
    """Collect zip code."""
    return AddressComponentResult(value=args["zip_code"])


async def restart_address_collection(args: FlowArgs) -> FlowResult:
    """Restart address collection."""
    return FlowResult(status="restarting")


async def collect_phone(args: FlowArgs) -> ContactResult:
    """Collect phone number."""
    return ContactResult(contact_info=args["phone_number"])


async def collect_email(args: FlowArgs) -> ContactResult:
    """Collect email address."""
    return ContactResult(contact_info=args["email"])


async def select_appointment(args: FlowArgs) -> AppointmentResult:
    """Select appointment time."""
    return AppointmentResult(selected_time=args["selected_time"])


async def end_intake(args: FlowArgs) -> FlowResult:
    """Complete the intake process."""
    return FlowResult(status="completed")


# Transition handlers
async def handle_first_name_collection(
    args: Dict, result: NameResult, flow_manager: FlowManager
):
    """Store first name and move to confirmation."""
    flow_manager.state["first_name"] = result["name"]
    await flow_manager.set_node(
        "confirm_first_name", create_confirm_first_name_node(result["name"])
    )


async def handle_first_name_confirmation(
    args: Dict, result: SpellingConfirmationResult, flow_manager: FlowManager
):
    """Handle first name confirmation."""
    if result["confirmed"]:
        # Spelling confirmed, move to next step
        await flow_manager.set_node(
            "collect_last_name", create_collect_last_name_node()
        )
    else:
        # User provided correction, update and confirm again
        if result["corrected_spelling"]:
            # Convert spaced letters back to word
            corrected_name = spaced_letters_to_word(result["corrected_spelling"])
            flow_manager.state["first_name"] = corrected_name
            # Loop back to confirm the new spelling
            await flow_manager.set_node(
                "confirm_first_name",
                create_confirm_first_name_node(corrected_name),
            )
        else:
            # No correction provided, ask again
            current_name = flow_manager.state.get("first_name", "")
            await flow_manager.set_node(
                "confirm_first_name", create_confirm_first_name_node(current_name)
            )


async def handle_last_name_collection(
    args: Dict, result: NameResult, flow_manager: FlowManager
):
    """Store last name and move to confirmation."""
    flow_manager.state["last_name"] = result["name"]
    await flow_manager.set_node(
        "confirm_last_name", create_confirm_last_name_node(result["name"])
    )


async def handle_last_name_confirmation(
    args: Dict, result: SpellingConfirmationResult, flow_manager: FlowManager
):
    """Handle last name confirmation."""
    if result["confirmed"]:
        # Spelling confirmed, move to next step
        await flow_manager.set_node(
            "collect_payer_name", create_collect_payer_name_node()
        )
    else:
        # User provided correction, update and confirm again
        if result["corrected_spelling"]:
            # Convert spaced letters back to word
            corrected_name = spaced_letters_to_word(result["corrected_spelling"])
            flow_manager.state["last_name"] = corrected_name
            # Loop back to confirm the new spelling
            await flow_manager.set_node(
                "confirm_last_name",
                create_confirm_last_name_node(corrected_name),
            )
        else:
            # No correction provided, ask again
            current_name = flow_manager.state.get("last_name", "")
            await flow_manager.set_node(
                "confirm_last_name", create_confirm_last_name_node(current_name)
            )


async def handle_payer_name_collection(
    args: Dict, result: NameResult, flow_manager: FlowManager
):
    """Store payer name and move to confirmation."""
    flow_manager.state["payer_name"] = result["name"]
    await flow_manager.set_node(
        "confirm_payer_name", create_confirm_payer_name_node(result["name"])
    )


async def handle_payer_name_confirmation(
    args: Dict, result: SpellingConfirmationResult, flow_manager: FlowManager
):
    """Handle payer name confirmation."""
    if result["confirmed"]:
        # Spelling confirmed, move to next step
        await flow_manager.set_node("collect_payer_id", create_collect_payer_id_node())
    else:
        # User provided correction, update and confirm again
        if result["corrected_spelling"]:
            # Convert spaced letters back to word
            corrected_name = spaced_letters_to_word(result["corrected_spelling"])
            flow_manager.state["payer_name"] = corrected_name
            # Loop back to confirm the new spelling
            await flow_manager.set_node(
                "confirm_payer_name",
                create_confirm_payer_name_node(corrected_name),
            )
        else:
            # No correction provided, ask again
            current_name = flow_manager.state.get("payer_name", "")
            await flow_manager.set_node(
                "confirm_payer_name", create_confirm_payer_name_node(current_name)
            )


async def handle_payer_id_collection(
    args: Dict, result: PayerIdResult, flow_manager: FlowManager
):
    """Store payer ID and move to confirmation."""
    flow_manager.state["payer_id"] = result["payer_id"]
    await flow_manager.set_node(
        "confirm_payer_id", create_confirm_payer_id_node(result["payer_id"])
    )


async def handle_payer_id_confirmation(
    args: Dict, result: PayerIdConfirmationResult, flow_manager: FlowManager
):
    """Handle payer ID confirmation."""
    if result["confirmed"]:
        # ID confirmed, move to next step
        await flow_manager.set_node("check_referral", create_check_referral_node())
    else:
        # User provided correction, update and confirm again
        corrected_id = result.get("corrected_id", 0)
        if corrected_id and corrected_id != 0:
            flow_manager.state["payer_id"] = corrected_id
            # Loop back to confirm the new ID
            await flow_manager.set_node(
                "confirm_payer_id", create_confirm_payer_id_node(corrected_id)
            )
        else:
            # No correction provided, ask again
            current_id = flow_manager.state.get("payer_id", 0)
            await flow_manager.set_node(
                "confirm_payer_id", create_confirm_payer_id_node(current_id)
            )


async def handle_referral_status(
    args: Dict, result: ReferralStatusResult, flow_manager: FlowManager
):
    """Handle referral status and route accordingly."""
    flow_manager.state["has_referral"] = result["has_referral"]
    if result["has_referral"]:
        await flow_manager.set_node(
            "collect_physician_first_name", create_collect_physician_first_name_node()
        )
    else:
        await flow_manager.set_node(
            "collect_complaint", create_collect_complaint_node()
        )


async def handle_physician_first_name_collection(
    args: Dict, result: NameResult, flow_manager: FlowManager
):
    """Store physician first name and move to confirmation."""
    flow_manager.state["physician_first_name"] = result["name"]
    await flow_manager.set_node(
        "confirm_physician_first_name",
        create_confirm_physician_first_name_node(result["name"]),
    )


async def handle_physician_first_name_confirmation(
    args: Dict, result: SpellingConfirmationResult, flow_manager: FlowManager
):
    """Handle physician first name confirmation."""
    if result["confirmed"]:
        # Spelling confirmed, move to next step
        await flow_manager.set_node(
            "collect_physician_last_name", create_collect_physician_last_name_node()
        )
    else:
        # User provided correction, update and confirm again
        if result["corrected_spelling"]:
            # Convert spaced letters back to word
            corrected_name = spaced_letters_to_word(result["corrected_spelling"])
            flow_manager.state["physician_first_name"] = corrected_name
            # Loop back to confirm the new spelling
            await flow_manager.set_node(
                "confirm_physician_first_name",
                create_confirm_physician_first_name_node(corrected_name),
            )
        else:
            # No correction provided, ask again
            current_name = flow_manager.state.get("physician_first_name", "")
            await flow_manager.set_node(
                "confirm_physician_first_name",
                create_confirm_physician_first_name_node(current_name),
            )


async def handle_physician_last_name_collection(
    args: Dict, result: NameResult, flow_manager: FlowManager
):
    """Store physician last name and move to confirmation."""
    flow_manager.state["physician_last_name"] = result["name"]
    await flow_manager.set_node(
        "confirm_physician_last_name",
        create_confirm_physician_last_name_node(result["name"]),
    )


async def handle_physician_last_name_confirmation(
    args: Dict, result: SpellingConfirmationResult, flow_manager: FlowManager
):
    """Handle physician last name confirmation."""
    if result["confirmed"]:
        # Spelling confirmed, move to next step
        await flow_manager.set_node(
            "collect_complaint", create_collect_complaint_node()
        )
    else:
        # User provided correction, update and confirm again
        if result["corrected_spelling"]:
            # Convert spaced letters back to word
            corrected_name = spaced_letters_to_word(result["corrected_spelling"])
            flow_manager.state["physician_last_name"] = corrected_name
            # Loop back to confirm the new spelling
            await flow_manager.set_node(
                "confirm_physician_last_name",
                create_confirm_physician_last_name_node(corrected_name),
            )
        else:
            # No correction provided, ask again
            current_name = flow_manager.state.get("physician_last_name", "")
            await flow_manager.set_node(
                "confirm_physician_last_name",
                create_confirm_physician_last_name_node(current_name),
            )


async def handle_complaint_collection(
    args: Dict, result: ComplaintResult, flow_manager: FlowManager
):
    """Store complaint and move to full address collection."""
    flow_manager.state["chief_complaint"] = result["complaint"]
    await flow_manager.set_node(
        "collect_full_address", create_collect_full_address_node()
    )


async def handle_full_address_collection(
    args: Dict, result: AddressComponentResult, flow_manager: FlowManager
):
    """Store full address and move to confirmation."""
    flow_manager.state["full_address"] = result["value"]
    await flow_manager.set_node(
        "confirm_full_address", create_confirm_full_address_node(result["value"])
    )


async def handle_full_address_confirmation(
    args: Dict, result: SpellingConfirmationResult, flow_manager: FlowManager
):
    """Handle full address confirmation."""
    if result["confirmed"]:
        # Address confirmed, validate it
        full_address = flow_manager.state.get("full_address", "")

        # Simple parsing - in production, use a proper address parser
        # Expecting format like "123 Main St, New York, NY 10001"
        parts = full_address.split(",")
        if len(parts) >= 3:
            street = parts[0].strip()
            city = parts[1].strip()
            state_zip = parts[2].strip().split()
            if len(state_zip) >= 2:
                state = state_zip[0]
                zip_code = state_zip[-1]

                # Validate address
                is_valid = await address_validator.validate_address(
                    street, city, zip_code
                )

                if is_valid:
                    flow_manager.state["address"] = {
                        "street": street,
                        "city": city,
                        "state": state,
                        "zip_code": zip_code,
                    }
                    await flow_manager.set_node(
                        "collect_phone", create_collect_phone_node()
                    )
                else:
                    # Address invalid, inform user and ask again
                    await flow_manager.set_node(
                        "address_invalid_full", create_address_invalid_full_node()
                    )
            else:
                # Invalid format
                await flow_manager.set_node(
                    "address_invalid_format", create_address_invalid_format_node()
                )
        else:
            # Invalid format
            await flow_manager.set_node(
                "address_invalid_format", create_address_invalid_format_node()
            )
    else:
        # User provided correction
        if result["corrected_spelling"]:
            flow_manager.state["full_address"] = result["corrected_spelling"]
            # Loop back to confirm the new address
            await flow_manager.set_node(
                "confirm_full_address",
                create_confirm_full_address_node(result["corrected_spelling"]),
            )
        else:
            # No correction provided, ask again
            current_address = flow_manager.state.get("full_address", "")
            await flow_manager.set_node(
                "confirm_full_address",
                create_confirm_full_address_node(current_address),
            )


async def handle_restart_full_address(
    args: Dict, result: FlowResult, flow_manager: FlowManager
):
    """Restart full address collection."""
    flow_manager.state.pop("full_address", None)
    await flow_manager.set_node(
        "collect_full_address", create_collect_full_address_node()
    )


async def handle_house_number_collection(
    args: Dict, result: AddressComponentResult, flow_manager: FlowManager
):
    """Store house number and move to confirmation."""
    flow_manager.state["house_number"] = result["value"]
    await flow_manager.set_node(
        "confirm_house_number", create_confirm_house_number_node(result["value"])
    )


async def handle_house_number_confirmation(
    args: Dict, result: SpellingConfirmationResult, flow_manager: FlowManager
):
    """Handle house number confirmation."""
    if result["confirmed"]:
        # Number confirmed, move to next step
        await flow_manager.set_node(
            "collect_street_name", create_collect_street_name_node()
        )
    else:
        # User provided correction, update and confirm again
        if result["corrected_spelling"]:
            # Remove spaces from the house number
            corrected_number = remove_spaces(result["corrected_spelling"])
            flow_manager.state["house_number"] = corrected_number
            # Loop back to confirm the new number
            await flow_manager.set_node(
                "confirm_house_number",
                create_confirm_house_number_node(corrected_number),
            )
        else:
            # No correction provided, ask again
            current_number = flow_manager.state.get("house_number", "")
            await flow_manager.set_node(
                "confirm_house_number", create_confirm_house_number_node(current_number)
            )


async def handle_street_name_collection(
    args: Dict, result: AddressComponentResult, flow_manager: FlowManager
):
    """Store street name and move to confirmation."""
    flow_manager.state["street_name"] = result["value"]
    await flow_manager.set_node(
        "confirm_street_name", create_confirm_street_name_node(result["value"])
    )


async def handle_street_name_confirmation(
    args: Dict, result: SpellingConfirmationResult, flow_manager: FlowManager
):
    """Handle street name confirmation."""
    if result["confirmed"]:
        # Spelling confirmed, move to next step
        await flow_manager.set_node("collect_city", create_collect_city_node())
    else:
        # User provided correction, update and confirm again
        if result["corrected_spelling"]:
            # Convert spaced letters back to word
            corrected_name = spaced_letters_to_word(result["corrected_spelling"])
            flow_manager.state["street_name"] = corrected_name
            # Loop back to confirm the new spelling
            await flow_manager.set_node(
                "confirm_street_name",
                create_confirm_street_name_node(corrected_name),
            )
        else:
            # No correction provided, ask again
            current_name = flow_manager.state.get("street_name", "")
            await flow_manager.set_node(
                "confirm_street_name", create_confirm_street_name_node(current_name)
            )


async def handle_city_collection(
    args: Dict, result: AddressComponentResult, flow_manager: FlowManager
):
    """Store city and move to confirmation."""
    flow_manager.state["city"] = result["value"]
    await flow_manager.set_node(
        "confirm_city", create_confirm_city_node(result["value"])
    )


async def handle_city_confirmation(
    args: Dict, result: SpellingConfirmationResult, flow_manager: FlowManager
):
    """Handle city confirmation."""
    if result["confirmed"]:
        # Spelling confirmed, move to next step
        await flow_manager.set_node("collect_state", create_collect_state_node())
    else:
        # User provided correction, update and confirm again
        if result["corrected_spelling"]:
            # Convert spaced letters back to word
            corrected_city = spaced_letters_to_word(result["corrected_spelling"])
            flow_manager.state["city"] = corrected_city
            # Loop back to confirm the new spelling
            await flow_manager.set_node(
                "confirm_city", create_confirm_city_node(corrected_city)
            )
        else:
            # No correction provided, ask again
            current_city = flow_manager.state.get("city", "")
            await flow_manager.set_node(
                "confirm_city", create_confirm_city_node(current_city)
            )


async def handle_state_collection(
    args: Dict, result: AddressComponentResult, flow_manager: FlowManager
):
    """Store state and move to confirmation."""
    flow_manager.state["state"] = result["value"]
    await flow_manager.set_node(
        "confirm_state", create_confirm_state_node(result["value"])
    )


async def handle_state_confirmation(
    args: Dict, result: SpellingConfirmationResult, flow_manager: FlowManager
):
    """Handle state confirmation."""
    if result["confirmed"]:
        # Spelling confirmed, move to next step
        await flow_manager.set_node("collect_zip_code", create_collect_zip_code_node())
    else:
        # User provided correction, update and confirm again
        if result["corrected_spelling"]:
            # Remove spaces and convert to uppercase for state codes
            corrected_state = remove_spaces(result["corrected_spelling"]).upper()
            flow_manager.state["state"] = corrected_state
            # Loop back to confirm the new spelling
            await flow_manager.set_node(
                "confirm_state", create_confirm_state_node(corrected_state)
            )
        else:
            # No correction provided, ask again
            current_state = flow_manager.state.get("state", "")
            await flow_manager.set_node(
                "confirm_state", create_confirm_state_node(current_state)
            )


async def handle_zip_code_collection(
    args: Dict, result: AddressComponentResult, flow_manager: FlowManager
):
    """Store zip code and validate address."""
    flow_manager.state["zip_code"] = result["value"]

    # Reconstruct full address and validate
    house_number = flow_manager.state.get("house_number", "")
    street_name = flow_manager.state.get("street_name", "")
    street = f"{house_number} {street_name}".strip()
    city = flow_manager.state.get("city", "")
    zip_code = result["value"]

    # Validate address
    is_valid = await address_validator.validate_address(street, city, zip_code)

    if is_valid:
        flow_manager.state["address"] = {
            "street": street,
            "city": city,
            "state": flow_manager.state.get("state", ""),
            "zip_code": zip_code,
        }
        await flow_manager.set_node("collect_phone", create_collect_phone_node())
    else:
        # Address invalid, inform user and start over
        await flow_manager.set_node("address_invalid", create_address_invalid_node())


async def handle_phone_collection(
    args: Dict, result: ContactResult, flow_manager: FlowManager
):
    """Store phone and move to email collection."""
    flow_manager.state["phone_number"] = result["contact_info"]
    await flow_manager.set_node("collect_email", create_collect_email_node())


async def handle_email_collection(
    args: Dict, result: ContactResult, flow_manager: FlowManager
):
    """Store email and move to appointment scheduling."""
    flow_manager.state["email"] = result["contact_info"]
    await flow_manager.set_node(
        "schedule_appointment", create_schedule_appointment_node()
    )


async def handle_appointment_selection(
    args: Dict, result: AppointmentResult, flow_manager: FlowManager
):
    """Store appointment time and move to confirmation."""
    flow_manager.state["appointment_time"] = result["selected_time"]
    await flow_manager.set_node(
        "confirm_appointment", create_confirm_appointment_node(result["selected_time"])
    )


async def handle_restart_address(
    args: Dict, result: FlowResult, flow_manager: FlowManager
):
    """Restart address collection from house number."""
    # Clear address-related state
    flow_manager.state.pop("house_number", None)
    flow_manager.state.pop("street_name", None)
    flow_manager.state.pop("city", None)
    flow_manager.state.pop("state", None)
    flow_manager.state.pop("zip_code", None)
    await flow_manager.set_node(
        "collect_house_number", create_collect_house_number_node()
    )


async def handle_end(args: Dict, result: FlowResult, flow_manager: FlowManager):
    """End the intake process."""
    await flow_manager.set_node("end", create_end_node())


# Node configurations
def create_initial_node() -> NodeConfig:
    """Create initial node for first name collection."""
    return {
        "role_messages": [
            {
                "role": "system",
                "content": "You are a friendly medical intake assistant. Your responses will be converted to audio, so avoid special characters and emojis. IMPORTANT: You must first ASK questions and wait for the user to respond before calling any functions. Never call a function with your own question as the parameter value.",
            }
        ],
        "task_messages": [
            {
                "role": "system",
                "content": "Greet the patient and ask for their first name. Do NOT call any function yet - just speak the greeting and question. Only call collect_first_name after the patient tells you their name.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="collect_first_name",
                description="Call this ONLY after the patient has told you their first name. The first_name parameter should be the actual name the patient said, not your question.",
                properties={
                    "first_name": {
                        "type": "string",
                        "description": "The patient's actual first name as they said it",
                    }
                },
                required=["first_name"],
                handler=collect_first_name,
                transition_callback=handle_first_name_collection,
            )
        ],
    }


def create_confirm_first_name_node(name: str) -> NodeConfig:
    """Create node for confirming first name spelling."""
    # Convert name to spaced letters format
    spaced_name = " ".join(name.upper())
    return {
        "task_messages": [
            {
                "role": "system",
                "content": f"The patient said their first name is '{name}'. You MUST spell it out letter by letter for confirmation. Say EXACTLY: 'Thank you. Let me confirm the spelling of your first name. Is it {spaced_name}?' Make sure to pronounce each letter separately with pauses between them. Do NOT call any function yet - wait for their response. If they say yes/correct/right, set confirmed to true. If they say no OR provide a different spelling, set confirmed to false and if they gave you the correct spelling, put it in corrected_spelling.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="confirm_first_name_spelling",
                description="Call this ONLY after the patient responds to your spelling confirmation question. Set confirmed=true if they agree, or confirmed=false with corrected_spelling if they provide a different spelling.",
                properties={
                    "confirmed": {
                        "type": "boolean",
                        "description": "Whether the patient confirmed the spelling is correct",
                    },
                    "corrected_spelling": {
                        "type": "string",
                        "description": "The corrected spelling if the patient said it was wrong",
                    },
                },
                required=["confirmed"],
                handler=confirm_first_name_spelling,
                transition_callback=handle_first_name_confirmation,
            )
        ],
    }


def create_collect_last_name_node() -> NodeConfig:
    """Create node for last name collection."""
    return {
        "task_messages": [
            {
                "role": "system",
                "content": "Ask for the patient's last name. Do NOT call any function yet - just ask the question. Only call collect_last_name after the patient tells you their last name.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="collect_last_name",
                description="Call this ONLY after the patient has told you their last name. The last_name parameter should be the actual name the patient said, not your question.",
                properties={
                    "last_name": {
                        "type": "string",
                        "description": "The patient's actual last name as they said it",
                    }
                },
                required=["last_name"],
                handler=collect_last_name,
                transition_callback=handle_last_name_collection,
            )
        ],
    }


def create_confirm_last_name_node(name: str) -> NodeConfig:
    """Create node for confirming last name spelling."""
    # Convert name to spaced letters format
    spaced_name = " ".join(name.upper())
    return {
        "task_messages": [
            {
                "role": "system",
                "content": f"The patient said their last name is '{name}'. You MUST spell it out letter by letter for confirmation. Say EXACTLY: 'Let me confirm the spelling of your last name. Is it {spaced_name}?' Make sure to pronounce each letter separately with pauses between them. Do NOT call any function yet - wait for their response. If they say yes/correct, set confirmed to true. If they spell it differently or say no, set confirmed to false and provide the corrected_spelling.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="confirm_last_name_spelling",
                description="Call this ONLY after the patient responds to your spelling confirmation question. Set confirmed=true if they agree, or confirmed=false with corrected_spelling if they provide a different spelling.",
                properties={
                    "confirmed": {
                        "type": "boolean",
                        "description": "Whether the patient confirmed the spelling is correct",
                    },
                    "corrected_spelling": {
                        "type": "string",
                        "description": "The corrected spelling if the patient said it was wrong",
                    },
                },
                required=["confirmed"],
                handler=confirm_last_name_spelling,
                transition_callback=handle_last_name_confirmation,
            )
        ],
    }


def create_collect_payer_name_node() -> NodeConfig:
    """Create node for payer name collection."""
    return {
        "task_messages": [
            {
                "role": "system",
                "content": "Ask for the patient's insurance payer name (e.g., Blue Cross, Aetna, etc.). Do NOT call any function yet - just ask the question. Only call collect_payer_name after the patient tells you their insurance company name.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="collect_payer_name",
                description="Call this ONLY after the patient has told you their insurance company name. The payer_name parameter should be the actual insurance company name the patient said, not your question.",
                properties={
                    "payer_name": {
                        "type": "string",
                        "description": "The actual insurance company name as stated by the patient",
                    }
                },
                required=["payer_name"],
                handler=collect_payer_name,
                transition_callback=handle_payer_name_collection,
            )
        ],
    }


def create_confirm_payer_name_node(name: str) -> NodeConfig:
    """Create node for confirming payer name spelling."""
    # Convert name to spaced letters format
    spaced_name = " ".join(name.upper())
    return {
        "task_messages": [
            {
                "role": "system",
                "content": f"The patient said their insurance payer is '{name}'. You MUST spell it out letter by letter for confirmation. Say EXACTLY: 'Let me confirm the spelling of your insurance company. Is it {spaced_name}?' Make sure to pronounce each letter separately with pauses between them. Do NOT call any function yet - wait for their response. If they say yes/correct, set confirmed to true. If they spell it differently or say no, set confirmed to false and provide the corrected_spelling.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="confirm_payer_spelling",
                description="Call this ONLY after the patient responds to your spelling confirmation question. Set confirmed=true if they agree, or confirmed=false with corrected_spelling if they provide a different spelling.",
                properties={
                    "confirmed": {
                        "type": "boolean",
                        "description": "Whether the patient confirmed the spelling is correct",
                    },
                    "corrected_spelling": {
                        "type": "string",
                        "description": "The corrected spelling if the patient said it was wrong",
                    },
                },
                required=["confirmed"],
                handler=confirm_payer_spelling,
                transition_callback=handle_payer_name_confirmation,
            )
        ],
    }


def create_collect_payer_id_node() -> NodeConfig:
    """Create node for payer ID collection."""
    return {
        "task_messages": [
            {
                "role": "system",
                "content": "Ask for the patient's insurance ID number. Remind them to speak slowly and clearly, and that this should be a numeric ID. Do NOT call any function yet - just ask the question. Only call collect_payer_id after the patient tells you their ID number.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="collect_payer_id",
                description="Call this ONLY after the patient has told you their insurance ID number. The payer_id parameter should be the actual numeric ID the patient said, not your question.",
                properties={
                    "payer_id": {
                        "type": "integer",
                        "description": "The actual insurance ID number as stated by the patient",
                    }
                },
                required=["payer_id"],
                handler=collect_payer_id,
                transition_callback=handle_payer_id_collection,
            )
        ],
    }


def create_confirm_payer_id_node(payer_id: int) -> NodeConfig:
    """Create node for confirming payer ID."""
    # Convert ID to spaced characters format
    spaced_id = " ".join(str(payer_id))
    return {
        "task_messages": [
            {
                "role": "system",
                "content": f"The patient said their insurance ID is '{payer_id}'. You MUST read it back digit by digit for confirmation. Say EXACTLY: 'Let me confirm your insurance ID number. Is it {spaced_id}?' Make sure to pronounce each digit separately with pauses between them. Do NOT call any function yet - wait for their response. If they say yes/correct, set confirmed to true. If they provide a different ID or say no, set confirmed to false and provide the corrected_id as a number.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="confirm_payer_id",
                description="Call this ONLY after the patient responds to your ID confirmation question. Set confirmed=true if they agree, or confirmed=false with corrected_id if they provide a different numeric ID.",
                properties={
                    "confirmed": {
                        "type": "boolean",
                        "description": "Whether the patient confirmed the ID is correct",
                    },
                    "corrected_id": {
                        "type": "integer",
                        "description": "The corrected numeric ID if the patient said it was wrong",
                    },
                },
                required=["confirmed"],
                handler=confirm_payer_id,
                transition_callback=handle_payer_id_confirmation,
            )
        ],
    }


def create_check_referral_node() -> NodeConfig:
    """Create node for checking referral status."""
    return {
        "task_messages": [
            {
                "role": "system",
                "content": "Ask if the patient has a referral from another physician. Do NOT ask if they want to continue with the intake process. Simply ask about the referral and move on based on their response. If they say no, immediately proceed to ask about their chief complaint without any transitional questions.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="check_referral_status",
                description="Check if patient has a referral. Call this immediately after they respond yes or no to the referral question.",
                properties={
                    "has_referral": {
                        "type": "boolean",
                        "description": "True if they have a referral, false if they don't",
                    }
                },
                required=["has_referral"],
                handler=check_referral_status,
                transition_callback=handle_referral_status,
            )
        ],
    }


def create_collect_physician_first_name_node() -> NodeConfig:
    """Create node for physician first name collection."""
    return {
        "task_messages": [
            {
                "role": "system",
                "content": "Ask for the referring physician's first name.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="collect_physician_first_name",
                description="Record referring physician's first name",
                properties={"physician_first_name": {"type": "string"}},
                required=["physician_first_name"],
                handler=collect_physician_first_name,
                transition_callback=handle_physician_first_name_collection,
            )
        ],
    }


def create_confirm_physician_first_name_node(name: str) -> NodeConfig:
    """Create node for confirming physician first name spelling."""
    # Convert name to spaced letters format
    spaced_name = " ".join(name.upper())
    return {
        "task_messages": [
            {
                "role": "system",
                "content": f"The patient said the physician's first name is '{name}'. You MUST spell it out letter by letter for confirmation. Say EXACTLY: 'Let me confirm the spelling of your physician's first name. Is it {spaced_name}?' Make sure to pronounce each letter separately with pauses between them. Do NOT call any function yet - wait for their response. If they say yes/correct, set confirmed to true. If they spell it differently or say no, set confirmed to false and provide the corrected_spelling.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="confirm_physician_first_name_spelling",
                description="Call this ONLY after the patient responds to your spelling confirmation question. Set confirmed=true if they agree, or confirmed=false with corrected_spelling if they provide a different spelling.",
                properties={
                    "confirmed": {
                        "type": "boolean",
                        "description": "Whether the patient confirmed the spelling is correct",
                    },
                    "corrected_spelling": {
                        "type": "string",
                        "description": "The corrected spelling if the patient said it was wrong",
                    },
                },
                required=["confirmed"],
                handler=confirm_physician_first_name_spelling,
                transition_callback=handle_physician_first_name_confirmation,
            )
        ],
    }


def create_collect_physician_last_name_node() -> NodeConfig:
    """Create node for physician last name collection."""
    return {
        "task_messages": [
            {
                "role": "system",
                "content": "Ask for the referring physician's last name.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="collect_physician_last_name",
                description="Record referring physician's last name",
                properties={"physician_last_name": {"type": "string"}},
                required=["physician_last_name"],
                handler=collect_physician_last_name,
                transition_callback=handle_physician_last_name_collection,
            )
        ],
    }


def create_confirm_physician_last_name_node(name: str) -> NodeConfig:
    """Create node for confirming physician last name spelling."""
    # Convert name to spaced letters format
    spaced_name = " ".join(name.upper())
    return {
        "task_messages": [
            {
                "role": "system",
                "content": f"The patient said the physician's last name is '{name}'. You MUST spell it out letter by letter for confirmation. Say EXACTLY: 'Let me confirm the spelling of your physician's last name. Is it {spaced_name}?' Make sure to pronounce each letter separately with pauses between them. Do NOT call any function yet - wait for their response. If they say yes/correct, set confirmed to true. If they spell it differently or say no, set confirmed to false and provide the corrected_spelling.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="confirm_physician_last_name_spelling",
                description="Call this ONLY after the patient responds to your spelling confirmation question. Set confirmed=true if they agree, or confirmed=false with corrected_spelling if they provide a different spelling.",
                properties={
                    "confirmed": {
                        "type": "boolean",
                        "description": "Whether the patient confirmed the spelling is correct",
                    },
                    "corrected_spelling": {
                        "type": "string",
                        "description": "The corrected spelling if the patient said it was wrong",
                    },
                },
                required=["confirmed"],
                handler=confirm_physician_last_name_spelling,
                transition_callback=handle_physician_last_name_confirmation,
            )
        ],
    }


def create_collect_complaint_node() -> NodeConfig:
    """Create node for collecting chief medical complaint."""
    return {
        "task_messages": [
            {
                "role": "system",
                "content": "Now, what brings you in today? Ask the patient about their chief medical complaint or reason for the visit. Be empathetic and let them explain in their own words. Do NOT mention anything about continuing the intake process - just naturally ask about their reason for visiting.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="collect_chief_complaint",
                description="Record patient's chief medical complaint. Call this after they explain their reason for visiting.",
                properties={
                    "complaint": {
                        "type": "string",
                        "description": "The chief complaint or reason for visit as explained by the patient",
                    }
                },
                required=["complaint"],
                handler=collect_chief_complaint,
                transition_callback=handle_complaint_collection,
            )
        ],
    }


def create_collect_full_address_node() -> NodeConfig:
    """Create node for collecting full address."""
    return {
        "task_messages": [
            {
                "role": "system",
                "content": "Now I need to collect your full address. Please tell me your complete address including street number, street name, city, state, and ZIP code. For example: '123 Main Street, New York, NY 10001'. Do NOT call any function yet - wait for their response.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="collect_full_address",
                description="Call this ONLY after the patient has told you their full address. The address parameter should be the complete address they said.",
                properties={
                    "address": {
                        "type": "string",
                        "description": "The full address as stated by the patient",
                    }
                },
                required=["address"],
                handler=collect_full_address,
                transition_callback=handle_full_address_collection,
            )
        ],
    }


def create_confirm_full_address_node(address: str) -> NodeConfig:
    """Create node for confirming full address."""
    # Convert address to spaced characters format
    spaced_address = format_address_for_spelling(address)
    return {
        "task_messages": [
            {
                "role": "system",
                "content": f"The patient said their address is '{address}'. You MUST spell it out character by character for confirmation. Say EXACTLY: 'Let me confirm your address character by character. Is it {spaced_address}?' Make sure to pronounce each character and digit separately with clear pauses between them. When you see double spaces, pause slightly longer. When you see 'comma', say the word 'comma'. Do NOT call any function yet - wait for their response. If they say yes/correct, set confirmed to true. If they provide a different address or say no, set confirmed to false and provide the corrected_address.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="confirm_full_address",
                description="Call this ONLY after the patient responds to your address confirmation. Set confirmed=true if they agree, or confirmed=false with corrected_address if they provide a different address.",
                properties={
                    "confirmed": {
                        "type": "boolean",
                        "description": "Whether the patient confirmed the address is correct",
                    },
                    "corrected_address": {
                        "type": "string",
                        "description": "The corrected address if the patient said it was wrong",
                    },
                },
                required=["confirmed"],
                handler=confirm_full_address,
                transition_callback=handle_full_address_confirmation,
            )
        ],
    }


def create_address_invalid_full_node() -> NodeConfig:
    """Create node for invalid address after full address collection."""
    return {
        "task_messages": [
            {
                "role": "system",
                "content": "I'm sorry, but I couldn't validate that address. This might be because the ZIP code doesn't match the city. Let's try again. Please tell me your complete address including street number, street name, city, state, and ZIP code.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="restart_address_collection",
                description="Restart full address collection",
                properties={},
                required=[],
                handler=restart_address_collection,
                transition_callback=handle_restart_full_address,
            )
        ],
    }


def create_address_invalid_format_node() -> NodeConfig:
    """Create node for invalid address format."""
    return {
        "task_messages": [
            {
                "role": "system",
                "content": "I'm sorry, but I couldn't understand the format of your address. Please provide your complete address in this format: street number and name, city, state abbreviation and ZIP code. For example: '123 Main Street, New York, NY 10001'.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="restart_address_collection",
                description="Restart full address collection",
                properties={},
                required=[],
                handler=restart_address_collection,
                transition_callback=handle_restart_full_address,
            )
        ],
    }


def create_collect_house_number_node() -> NodeConfig:
    """Create node for house number collection."""
    return {
        "task_messages": [
            {
                "role": "system",
                "content": "Now I need to collect your address. Let's start with your house number. What is your house number? Do NOT call any function yet - wait for their response.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="collect_house_number",
                description="Call this ONLY after the patient has told you their house number. The house_number parameter should be the actual number they said.",
                properties={
                    "house_number": {
                        "type": "string",
                        "description": "The house number as stated by the patient",
                    }
                },
                required=["house_number"],
                handler=collect_house_number,
                transition_callback=handle_house_number_collection,
            )
        ],
    }


def create_confirm_house_number_node(number: str) -> NodeConfig:
    """Create node for confirming house number."""
    spaced_number = " ".join(number.upper())
    return {
        "task_messages": [
            {
                "role": "system",
                "content": f"The patient said their house number is '{number}'. You MUST read it back character by character for confirmation. Say EXACTLY: 'Let me confirm your house number. Is it {spaced_number}?' Make sure to pronounce each character separately. Do NOT call any function yet - wait for their response.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="confirm_house_number",
                description="Call this ONLY after the patient responds to your confirmation question. Set confirmed=true if they agree, or confirmed=false with corrected_spelling if they provide a different number.",
                properties={
                    "confirmed": {
                        "type": "boolean",
                        "description": "Whether the patient confirmed the number is correct",
                    },
                    "corrected_spelling": {
                        "type": "string",
                        "description": "The corrected number if the patient said it was wrong",
                    },
                },
                required=["confirmed"],
                handler=confirm_house_number,
                transition_callback=handle_house_number_confirmation,
            )
        ],
    }


def create_collect_street_name_node() -> NodeConfig:
    """Create node for street name collection."""
    return {
        "task_messages": [
            {
                "role": "system",
                "content": "Now, what is your street name? For example, Main Street, Oak Avenue, etc. Do NOT call any function yet - wait for their response.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="collect_street_name",
                description="Call this ONLY after the patient has told you their street name. The street_name parameter should be the actual street name they said.",
                properties={
                    "street_name": {
                        "type": "string",
                        "description": "The street name as stated by the patient",
                    }
                },
                required=["street_name"],
                handler=collect_street_name,
                transition_callback=handle_street_name_collection,
            )
        ],
    }


def create_confirm_street_name_node(name: str) -> NodeConfig:
    """Create node for confirming street name spelling."""
    spaced_name = " ".join(name.upper())
    return {
        "task_messages": [
            {
                "role": "system",
                "content": f"The patient said their street name is '{name}'. You MUST spell it out letter by letter for confirmation. Say EXACTLY: 'Let me confirm the spelling of your street name. Is it {spaced_name}?' Make sure to pronounce each letter separately. Do NOT call any function yet - wait for their response.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="confirm_street_name_spelling",
                description="Call this ONLY after the patient responds to your spelling confirmation question. Set confirmed=true if they agree, or confirmed=false with corrected_spelling if they provide a different spelling.",
                properties={
                    "confirmed": {
                        "type": "boolean",
                        "description": "Whether the patient confirmed the spelling is correct",
                    },
                    "corrected_spelling": {
                        "type": "string",
                        "description": "The corrected spelling if the patient said it was wrong",
                    },
                },
                required=["confirmed"],
                handler=confirm_street_name_spelling,
                transition_callback=handle_street_name_confirmation,
            )
        ],
    }


def create_collect_city_node() -> NodeConfig:
    """Create node for city collection."""
    return {
        "task_messages": [
            {
                "role": "system",
                "content": "What city do you live in? Do NOT call any function yet - wait for their response.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="collect_city",
                description="Call this ONLY after the patient has told you their city. The city parameter should be the actual city name they said.",
                properties={
                    "city": {
                        "type": "string",
                        "description": "The city name as stated by the patient",
                    }
                },
                required=["city"],
                handler=collect_city,
                transition_callback=handle_city_collection,
            )
        ],
    }


def create_confirm_city_node(city: str) -> NodeConfig:
    """Create node for confirming city spelling."""
    spaced_city = " ".join(city.upper())
    return {
        "task_messages": [
            {
                "role": "system",
                "content": f"The patient said their city is '{city}'. You MUST spell it out letter by letter for confirmation. Say EXACTLY: 'Let me confirm the spelling of your city. Is it {spaced_city}?' Make sure to pronounce each letter separately. Do NOT call any function yet - wait for their response.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="confirm_city_spelling",
                description="Call this ONLY after the patient responds to your spelling confirmation question. Set confirmed=true if they agree, or confirmed=false with corrected_spelling if they provide a different spelling.",
                properties={
                    "confirmed": {
                        "type": "boolean",
                        "description": "Whether the patient confirmed the spelling is correct",
                    },
                    "corrected_spelling": {
                        "type": "string",
                        "description": "The corrected spelling if the patient said it was wrong",
                    },
                },
                required=["confirmed"],
                handler=confirm_city_spelling,
                transition_callback=handle_city_confirmation,
            )
        ],
    }


def create_collect_state_node() -> NodeConfig:
    """Create node for state collection."""
    return {
        "task_messages": [
            {
                "role": "system",
                "content": "What state do you live in? You can say the full state name or the two-letter abbreviation. Do NOT call any function yet - wait for their response.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="collect_state",
                description="Call this ONLY after the patient has told you their state. The state parameter should be what they said.",
                properties={
                    "state": {
                        "type": "string",
                        "description": "The state as stated by the patient",
                    }
                },
                required=["state"],
                handler=collect_state,
                transition_callback=handle_state_collection,
            )
        ],
    }


def create_confirm_state_node(state: str) -> NodeConfig:
    """Create node for confirming state spelling."""
    spaced_state = " ".join(state.upper())
    return {
        "task_messages": [
            {
                "role": "system",
                "content": f"The patient said their state is '{state}'. You MUST spell it out letter by letter for confirmation. Say EXACTLY: 'Let me confirm your state. Is it {spaced_state}?' Make sure to pronounce each letter separately. Do NOT call any function yet - wait for their response.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="confirm_state_spelling",
                description="Call this ONLY after the patient responds to your spelling confirmation question. Set confirmed=true if they agree, or confirmed=false with corrected_spelling if they provide a different spelling.",
                properties={
                    "confirmed": {
                        "type": "boolean",
                        "description": "Whether the patient confirmed the spelling is correct",
                    },
                    "corrected_spelling": {
                        "type": "string",
                        "description": "The corrected spelling if the patient said it was wrong",
                    },
                },
                required=["confirmed"],
                handler=confirm_state_spelling,
                transition_callback=handle_state_confirmation,
            )
        ],
    }


def create_collect_zip_code_node() -> NodeConfig:
    """Create node for zip code collection."""
    return {
        "task_messages": [
            {
                "role": "system",
                "content": "Finally, what is your ZIP code? Please speak slowly and clearly. Do NOT call any function yet - wait for their response.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="collect_zip_code",
                description="Call this ONLY after the patient has told you their ZIP code. The zip_code parameter should be the actual ZIP code they said.",
                properties={
                    "zip_code": {
                        "type": "string",
                        "description": "The ZIP code as stated by the patient",
                    }
                },
                required=["zip_code"],
                handler=collect_zip_code,
                transition_callback=handle_zip_code_collection,
            )
        ],
    }


def create_address_invalid_node() -> NodeConfig:
    """Create node for invalid address handling."""
    return {
        "task_messages": [
            {
                "role": "system",
                "content": "I'm sorry, but I couldn't validate that address. Let's start over with your address information. First, what is your house number?",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="restart_address_collection",
                description="Restart address collection",
                properties={},
                required=[],
                handler=restart_address_collection,
                transition_callback=handle_restart_address,
            )
        ],
    }


def create_collect_phone_node() -> NodeConfig:
    """Create node for phone collection."""
    return {
        "task_messages": [
            {
                "role": "system",
                "content": "Ask for the patient's phone number. Remind them to include the area code.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="collect_phone",
                description="Record patient's phone number",
                properties={"phone_number": {"type": "string"}},
                required=["phone_number"],
                handler=collect_phone,
                transition_callback=handle_phone_collection,
            )
        ],
    }


def create_collect_email_node() -> NodeConfig:
    """Create node for email collection."""
    return {
        "task_messages": [
            {
                "role": "system",
                "content": "Ask for the patient's email address. Let them know we'll use it to send appointment confirmations.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="collect_email",
                description="Record patient's email address",
                properties={"email": {"type": "string"}},
                required=["email"],
                handler=collect_email,
                transition_callback=handle_email_collection,
            )
        ],
    }


def create_schedule_appointment_node() -> NodeConfig:
    """Create node for appointment scheduling."""
    available_times_str = "\n".join([f"- {time}" for time in AVAILABLE_TIMES])
    return {
        "task_messages": [
            {
                "role": "system",
                "content": f"Offer the patient these available appointment times:\n{available_times_str}\n\nAsk which time works best for them.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="select_appointment",
                description="Select appointment time",
                properties={
                    "selected_time": {"type": "string", "enum": AVAILABLE_TIMES}
                },
                required=["selected_time"],
                handler=select_appointment,
                transition_callback=handle_appointment_selection,
            )
        ],
    }


def create_confirm_appointment_node(selected_time: str) -> NodeConfig:
    """Create node for appointment confirmation."""
    return {
        "task_messages": [
            {
                "role": "system",
                "content": f"Confirm the appointment for {selected_time} and let them know they'll receive a confirmation email. Ask if they have any questions before we finish.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="end_intake",
                description="Complete the intake process",
                properties={},
                required=[],
                handler=end_intake,
                transition_callback=handle_end,
            )
        ],
    }


def create_end_node() -> NodeConfig:
    """Create the final node."""
    return {
        "functions": [],
        "task_messages": [
            {
                "role": "system",
                "content": "Thank the patient for their time and remind them about their appointment. End the conversation warmly.",
            }
        ],
        "post_actions": [{"type": "end_conversation"}],
    }


# Complete flow configuration
flow_config = {
    "initial_node": "initial",  # This should be a string key, not the actual node
    "nodes": {
        "initial": create_initial_node(),  # Add the initial node to the nodes dict
        "confirm_first_name": create_confirm_first_name_node(
            "placeholder"
        ),  # Will be updated dynamically
        "collect_last_name": create_collect_last_name_node(),
        "confirm_last_name": create_confirm_last_name_node(
            "placeholder"
        ),  # Will be updated dynamically
        "collect_payer_name": create_collect_payer_name_node(),
        "confirm_payer_name": create_confirm_payer_name_node(
            "placeholder"
        ),  # Will be updated dynamically
        "collect_payer_id": create_collect_payer_id_node(),
        "confirm_payer_id": create_confirm_payer_id_node(
            "placeholder"
        ),  # Will be updated dynamically
        "check_referral": create_check_referral_node(),
        "collect_physician_first_name": create_collect_physician_first_name_node(),
        "confirm_physician_first_name": create_confirm_physician_first_name_node(
            "placeholder"
        ),  # Will be updated dynamically
        "collect_physician_last_name": create_collect_physician_last_name_node(),
        "confirm_physician_last_name": create_confirm_physician_last_name_node(
            "placeholder"
        ),  # Will be updated dynamically
        "collect_complaint": create_collect_complaint_node(),
        # New full address collection nodes
        "collect_full_address": create_collect_full_address_node(),
        "confirm_full_address": create_confirm_full_address_node(
            "placeholder"
        ),  # Will be updated dynamically
        "address_invalid_full": create_address_invalid_full_node(),
        "address_invalid_format": create_address_invalid_format_node(),
        "collect_phone": create_collect_phone_node(),
        "collect_email": create_collect_email_node(),
        "schedule_appointment": create_schedule_appointment_node(),
        "confirm_appointment": create_confirm_appointment_node(
            "placeholder"
        ),  # Will be updated dynamically
        "end": create_end_node(),
    },
}
