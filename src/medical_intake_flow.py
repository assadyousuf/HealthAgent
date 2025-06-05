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

import os
import sys
from pathlib import Path
from typing import Dict
import usaddress  # Add this import
import re  # Added for email regex parsing

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

# Import email service
from .services.email_service import EmailService
from .services.address_validator import AddressValidator


def get_phonetic_representation(char: str) -> str:
    """Return phonetic representation for letters, specific words for symbols, or char itself."""
    char_lower = char.lower()
    if char_lower in NATO_PHONETIC_ALPHABET:
        return NATO_PHONETIC_ALPHABET[char_lower]
    elif char_lower == ".":
        return "dot"
    elif char_lower == "@":
        return "at sign"
    elif char_lower == "-":
        return "hyphen"
    elif char_lower == "_":
        return "underscore"
    # For digits and other symbols, return them as is to be read normally.
    return char


# Helper for phonetic spelling
NATO_PHONETIC_ALPHABET = {
    "a": "Alpha",
    "b": "Bravo",
    "c": "Charlie",
    "d": "Delta",
    "e": "Echo",
    "f": "Foxtrot",
    "g": "Golf",
    "h": "Hotel",
    "i": "India",
    "j": "Juliett",
    "k": "Kilo",
    "l": "Lima",
    "m": "Mike",
    "n": "November",
    "o": "Oscar",
    "p": "Papa",
    "q": "Quebec",
    "r": "Romeo",
    "s": "Sierra",
    "t": "Tango",
    "u": "Uniform",
    "v": "Victor",
    "w": "Whiskey",
    "x": "X-ray",
    "y": "Yankee",
    "z": "Zulu",
}


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


# Mock provider schedule with doctors
AVAILABLE_APPOINTMENTS = [
    {
        "time": "Monday, December 18 at 9:00 AM",
        "doctor": "Dr. Sarah Johnson",
        "specialty": "Internal Medicine",
    },
    {
        "time": "Monday, December 18 at 10:30 AM",
        "doctor": "Dr. Michael Chen",
        "specialty": "Cardiology",
    },
    {
        "time": "Tuesday, December 19 at 2:00 PM",
        "doctor": "Dr. Emily Rodriguez",
        "specialty": "Family Medicine",
    },
    {
        "time": "Wednesday, December 20 at 11:00 AM",
        "doctor": "Dr. David Thompson",
        "specialty": "Orthopedics",
    },
    {
        "time": "Thursday, December 21 at 3:30 PM",
        "doctor": "Dr. Lisa Park",
        "specialty": "Dermatology",
    },
]

# Extract just the times for backward compatibility
AVAILABLE_TIMES = [apt["time"] for apt in AVAILABLE_APPOINTMENTS]

address_validator = AddressValidator(
    client_id=os.getenv("USPS_CLIENT_ID"), client_secret=os.getenv("USPS_CLIENT_SECRET")
)

# Initialize email service
email_service = EmailService()


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


class EmailPreferenceResult(FlowResult):
    wants_email: bool


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


async def restart_address_collection(args: FlowArgs) -> FlowResult:
    """Restart address collection."""
    return FlowResult(status="restarting")


async def collect_phone(args: FlowArgs) -> ContactResult:
    """Collect phone number."""
    return ContactResult(contact_info=args["phone_number"])


async def collect_email(args: FlowArgs) -> ContactResult:
    """Collect patient's email address."""
    return ContactResult(contact_info=args["email"])


async def confirm_email_spelling(args: FlowArgs) -> SpellingConfirmationResult:
    """Confirm email spelling."""
    return SpellingConfirmationResult(
        confirmed=args["confirmed"],
        corrected_spelling=args.get("corrected_spelling", ""),
    )


async def ask_email_preference(args: FlowArgs) -> EmailPreferenceResult:
    """Ask if patient wants to provide email."""
    return EmailPreferenceResult(wants_email=args["wants_email"])


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
    """Handle full address confirmation using usaddress parsing."""
    # Define a mapping for state names to abbreviations
    # This can be expanded as needed
    state_name_to_abbreviation = {
        "alabama": "AL",
        "alaska": "AK",
        "arizona": "AZ",
        "arkansas": "AR",
        "california": "CA",
        "colorado": "CO",
        "connecticut": "CT",
        "delaware": "DE",
        "florida": "FL",
        "georgia": "GA",
        "hawaii": "HI",
        "idaho": "ID",
        "illinois": "IL",
        "indiana": "IN",
        "iowa": "IA",
        "kansas": "KS",
        "kentucky": "KY",
        "louisiana": "LA",
        "maine": "ME",
        "maryland": "MD",
        "massachusetts": "MA",
        "michigan": "MI",
        "minnesota": "MN",
        "mississippi": "MS",
        "missouri": "MO",
        "montana": "MT",
        "nebraska": "NE",
        "nevada": "NV",
        "new hampshire": "NH",
        "new jersey": "NJ",
        "new mexico": "NM",
        "new york": "NY",
        "north carolina": "NC",
        "north dakota": "ND",
        "ohio": "OH",
        "oklahoma": "OK",
        "oregon": "OR",
        "pennsylvania": "PA",
        "rhode island": "RI",
        "south carolina": "SC",
        "south dakota": "SD",
        "tennessee": "TN",
        "texas": "TX",
        "utah": "UT",
        "vermont": "VT",
        "virginia": "VA",
        "washington": "WA",
        "west virginia": "WV",
        "wisconsin": "WI",
        "wyoming": "WY",
    }

    if result.get("confirmed") and not result.get("corrected_spelling"):
        full_address_str = flow_manager.state.get("full_address", "")
        logger.info(
            f"Address confirmed: '{full_address_str}'. Proceeding to parse and validate."
        )
    elif result.get("corrected_spelling"):
        if result.get("confirmed", False) and result.get("corrected_spelling"):
            logger.warning(
                f"LLM set confirmed=true but also provided corrected_address: '{result.get("corrected_spelling")}'. Prioritizing corrected."
            )
            full_address_str = result.get("corrected_spelling")
            flow_manager.state["full_address"] = (
                full_address_str  # Update state with this correction
            )
        elif not result.get("confirmed") and result.get("corrected_spelling"):
            full_address_str = result.get("corrected_spelling")
            flow_manager.state["full_address"] = (
                full_address_str  # Update state with the correction
            )
            logger.info(
                f"Address correction provided: '{full_address_str}'. Looping back to confirm this new address."
            )
            # Loop back to confirm the new address
            await flow_manager.set_node(
                "confirm_full_address",
                create_confirm_full_address_node(full_address_str),
            )
            return  # Exit early as we are re-confirming
        else:  # Should not happen if logic is correct: confirmed=true and no corrected_spelling, or confirmed=false and corrected_spelling
            logger.error(
                "Invalid state in handle_full_address_confirmation with corrected_spelling."
            )
            await flow_manager.set_node(
                "address_invalid_format", create_address_invalid_format_node()
            )
            return

    else:  # Not confirmed, and no correction given (e.g. user just said "no")
        current_address = flow_manager.state.get("full_address", "")
        logger.info(
            f"Address not confirmed, no correction. Re-confirming: {current_address}"
        )
        await flow_manager.set_node(
            "confirm_full_address",
            create_confirm_full_address_node(current_address),
        )
        return

    if not full_address_str:
        logger.warning(
            "Full address string is empty in handle_full_address_confirmation after confirmation."
        )
        await flow_manager.set_node(
            "address_invalid_format", create_address_invalid_format_node()
        )
        return

    try:
        # Parse the address using usaddress
        # usaddress.tag returns a list of tuples (value, tag) and an 'Ambiguous' type if it fails badly.
        parsed_address_dict = {}
        address_parts = []  # For reconstructing street line 1

        # Use usaddress.repeated_tag for potentially cleaner, structured output
        tagged_address, address_type = usaddress.tag(full_address_str)

        if address_type == "Ambiguous":
            logger.warning(
                f"Address '{full_address_str}' is ambiguous according to usaddress."
            )
            await flow_manager.set_node(
                "address_invalid_format", create_address_invalid_format_node()
            )
            return

        # Define components for street address line 1
        # Order matters for reconstruction. Add more tags if needed.
        street_tags_ordered = [
            "AddressNumberPrefix",
            "AddressNumber",
            "AddressNumberSuffix",
            "StreetNamePreDirectional",
            "StreetNamePreModifier",
            "StreetNamePreType",
            "StreetName",
            "StreetNamePostType",
            "StreetNamePostModifier",
            "StreetNamePostDirectional",
            "SubaddressType",
            "SubaddressIdentifier",  # For apt, suite, etc.
        ]

        temp_street_parts = {}  # Use dict to store parts by tag to ensure order later

        for key, value in tagged_address.items():
            parsed_address_dict[key] = value
            if key in street_tags_ordered:
                temp_street_parts[key] = value

        # Reconstruct street_address_line1 in the correct order
        street_address_line1_parts = [
            temp_street_parts[tag]
            for tag in street_tags_ordered
            if tag in temp_street_parts
        ]
        street_address_line1 = " ".join(street_address_line1_parts)

        city_parsed = tagged_address.get("PlaceName")
        state_full_name_parsed = tagged_address.get("StateName")
        zip_parsed = tagged_address.get("ZipCode")

        logger.info(
            f"Parsed address components: Street='{street_address_line1}', City='{city_parsed}', State Name='{state_full_name_parsed}', ZIP='{zip_parsed}'"
        )

        if not state_full_name_parsed:
            logger.warning(f"State name not parsed from address: '{full_address_str}'")
            await flow_manager.set_node(
                "address_invalid_format", create_address_invalid_format_node()
            )
            return

        state_abbreviation = state_name_to_abbreviation.get(
            state_full_name_parsed.lower()
        )

        if not state_abbreviation:
            logger.warning(
                f"Could not convert state name '{state_full_name_parsed}' to abbreviation. Address: '{full_address_str}'"
            )
            await flow_manager.set_node(
                "address_invalid_format", create_address_invalid_format_node()
            )
            return

        logger.info(
            f"Converted state '{state_full_name_parsed}' to abbreviation '{state_abbreviation}'"
        )

        if not all(
            [street_address_line1, city_parsed, zip_parsed]
        ):  # state_abbreviation is now checked
            logger.warning(
                f"Could not parse all required address components from '{full_address_str}'. Missing: street: {not street_address_line1}, city: {not city_parsed}, zip: {not zip_parsed}"
            )
            await flow_manager.set_node(
                "address_invalid_format", create_address_invalid_format_node()
            )
            return

        # Validate address using the new validator
        # Ensure the arguments match what AddressValidator expects (e.g., street, city, state, zip5)
        is_valid = await address_validator.validate_address(
            street1=street_address_line1,
            city=city_parsed,
            state=state_abbreviation,  # Use the 2-letter abbreviation
            zip5=zip_parsed,
        )

        if is_valid:
            logger.info(
                f"Address validated successfully: {street_address_line1}, {city_parsed}, {state_abbreviation} {zip_parsed}"
            )
            flow_manager.state["address"] = {
                "street": street_address_line1,
                "city": city_parsed,
                "state": state_abbreviation,  # Store abbreviation
                "zip_code": zip_parsed,
            }
            await flow_manager.set_node("collect_phone", create_collect_phone_node())
        else:
            logger.warning(
                f"Address validation failed for: {street_address_line1}, {city_parsed}, {state_abbreviation} {zip_parsed}"
            )
            await flow_manager.set_node(
                "address_invalid_full", create_address_invalid_full_node()
            )

    except usaddress.RepeatedLabelError as e:
        logger.error(
            f"Error parsing address with usaddress (RepeatedLabelError): {full_address_str} - {e}"
        )
        await flow_manager.set_node(
            "address_invalid_format", create_address_invalid_format_node()
        )
    except Exception as e:
        logger.error(
            f"Unexpected error during address parsing or validation: {e} for address '{full_address_str}'"
        )
        await flow_manager.set_node(
            "address_invalid_format", create_address_invalid_format_node()
        )


async def handle_restart_full_address(
    args: Dict, result: FlowResult, flow_manager: FlowManager
):
    """Restart full address collection."""
    flow_manager.state.pop("full_address", None)
    await flow_manager.set_node(
        "collect_full_address", create_collect_full_address_node()
    )


async def handle_phone_collection(
    args: Dict, result: ContactResult, flow_manager: FlowManager
):
    """Store phone and move to email preference check."""
    flow_manager.state["phone_number"] = result["contact_info"]
    await flow_manager.set_node(
        "ask_email_preference", create_ask_email_preference_node()
    )


async def handle_email_preference(
    args: Dict, result: EmailPreferenceResult, flow_manager: FlowManager
):
    """Handle email preference and route accordingly."""
    if result["wants_email"]:
        # User wants to provide email, go to email collection
        await flow_manager.set_node("collect_email", create_collect_email_node())
    else:
        # User doesn't want to provide email, skip to appointment scheduling
        flow_manager.state["email"] = None  # Mark as explicitly skipped
        await flow_manager.set_node(
            "schedule_appointment", create_schedule_appointment_node()
        )


async def handle_email_collection(
    args: Dict, result: ContactResult, flow_manager: FlowManager
):
    """Store email and move to confirmation."""
    # Try to extract email using regex from the initial collection as well
    # This helps if the user says something like "my email is example@example.com thanks"
    raw_email_input = result.get("contact_info", "")
    emails_found = []
    if raw_email_input:
        emails_found = re.findall(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
            raw_email_input,
            re.IGNORECASE,
        )

    extracted_email = ""
    if emails_found:
        extracted_email = emails_found[0].lower()
        if len(emails_found) > 1:
            logger.warning(
                f"Multiple emails found during initial collection: {emails_found}. Using first: {extracted_email}"
            )
        logger.info(f"Extracted email via regex during collection: {extracted_email}")
    elif raw_email_input:  # No regex match, but there was input
        logger.warning(
            f"No email pattern found via regex in initial input: '{raw_email_input}'. Using raw input for now."
        )
        extracted_email = (
            raw_email_input  # Fallback to raw input, hoping LLM gave just the email
        )
    else:
        logger.warning("No email input received in collect_email handler.")
        # Fallback to an empty string or a placeholder to avoid erroring out immediately
        extracted_email = "placeholder@example.com"  # Or handle as an error state

    flow_manager.state["email"] = extracted_email
    await flow_manager.set_node(
        "confirm_email", create_confirm_email_node(extracted_email)
    )


async def handle_email_confirmation(
    args: Dict, result: SpellingConfirmationResult, flow_manager: FlowManager
):
    """Handle email confirmation."""
    user_confirmed = result.get("confirmed", False)
    raw_correction_text = result.get("corrected_spelling", "")

    current_email_in_state = flow_manager.state.get("email", "")

    if user_confirmed and not raw_correction_text:
        # Email confirmed by user, and LLM did not provide any alternative correction text.
        logger.info(f"Email '{current_email_in_state}' confirmed by user.")
        await flow_manager.set_node(
            "schedule_appointment", create_schedule_appointment_node()
        )
    elif raw_correction_text:
        # User indicated 'no' or provided a correction, or LLM provided correction text.
        # Try to extract an email from this correction text using regex.
        emails_found = re.findall(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
            raw_correction_text,
            re.IGNORECASE,
        )

        if emails_found:
            extracted_email = emails_found[
                0
            ].lower()  # Take the first found email, normalize to lowercase
            if len(emails_found) > 1:
                logger.warning(
                    f"Multiple emails found in correction text: '{raw_correction_text}'. Using the first one: {extracted_email}"
                )

            flow_manager.state["email"] = extracted_email
            logger.info(
                f"Email correction extracted via regex: '{extracted_email}'. Looping back to confirm this new email."
            )
            await flow_manager.set_node(
                "confirm_email", create_confirm_email_node(extracted_email)
            )
        else:
            # No valid email found in the correction text by regex.
            logger.warning(
                f"No valid email pattern found in correction text: '{raw_correction_text}'. Asking to re-confirm current email: '{current_email_in_state}'"
            )
            # Re-trigger confirmation for the current email in state, or a placeholder if none.
            await flow_manager.set_node(
                "confirm_email",
                create_confirm_email_node(
                    current_email_in_state
                    if current_email_in_state
                    else "your.email@example.com"
                ),
            )
    else:  # Not confirmed (user_confirmed is False), and no correction text given (e.g., user just said "no")
        logger.info(
            f"Email spelling not confirmed by user, no correction text offered. Re-confirming current email: '{current_email_in_state}'"
        )
        await flow_manager.set_node(
            "confirm_email",
            create_confirm_email_node(
                current_email_in_state
                if current_email_in_state
                else "your.email@example.com"
            ),
        )


async def handle_appointment_selection(
    args: Dict, result: AppointmentResult, flow_manager: FlowManager
):
    """Store appointment time and doctor info, then move to confirmation."""
    selected_time = result["selected_time"]

    # Find the corresponding doctor information
    selected_appointment = next(
        (apt for apt in AVAILABLE_APPOINTMENTS if apt["time"] == selected_time), None
    )

    # Store appointment details
    flow_manager.state["appointment_time"] = selected_time
    if selected_appointment:
        flow_manager.state["doctor_name"] = selected_appointment["doctor"]
        flow_manager.state["doctor_specialty"] = selected_appointment["specialty"]

    await flow_manager.set_node(
        "confirm_appointment",
        create_confirm_appointment_node(
            selected_time,
            selected_appointment["doctor"] if selected_appointment else None,
            selected_appointment["specialty"] if selected_appointment else None,
        ),
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
    """End the intake process and send confirmation email if applicable."""

    # Check if patient provided an email address
    patient_email = flow_manager.state.get("email")

    if patient_email:
        # Prepare appointment details for email
        appointment_details = {
            "doctor": flow_manager.state.get("doctor_name", "N/A"),
            "time": flow_manager.state.get("appointment_time", "N/A"),
            "specialty": flow_manager.state.get("doctor_specialty", "N/A"),
        }

        # Send confirmation email
        try:
            success = await email_service.send_appointment_confirmation(
                recipient_email=patient_email, appointment_details=appointment_details
            )

            if success:
                logger.info(
                    f"Appointment confirmation email sent successfully to {patient_email}"
                )
            else:
                logger.warning(
                    f"Failed to send appointment confirmation email to {patient_email}"
                )

        except Exception as e:
            logger.error(
                f"Error sending appointment confirmation email to {patient_email}: {e}"
            )

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
                "content": "Ask if the patient has a referral from another physician. Do NOT call any function yet - just ask the question. IMPORTANT: After the patient responds 'yes' or 'no', you MUST call the 'check_referral_status' function with their response. Do NOT ask if they want to continue with the intake process. The 'check_referral_status' function will handle the next step.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="check_referral_status",
                description="Call this function ONLY after the patient has responded 'yes' or 'no' to the referral question. Pass their response to the 'has_referral' parameter.",
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
                "content": "Now, what brings you in today? Ask the patient about their chief medical complaint or reason for the visit. Be empathetic and let them explain in their own words. Do NOT mention anything about continuing the intake process - just naturally ask about their reason for visiting. Do NOT call any function yet - wait for their response. Only call collect_chief_complaint after the patient tells you their reason for visiting.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="collect_chief_complaint",
                description="Call this ONLY after the patient has explained their reason for visiting. The complaint parameter should be the actual reason they stated, not your question.",
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
                "content": "Now I need to collect your full address. Please tell me your complete address including street number, street name, city, state, and ZIP code. For example: '123 Main Street, New York, NY 10001'. Do NOT call any function yet - wait for their response. Parse out the address components (street number, street name, city, state, zip code) from the user's response from the users resposne (street number, street name, city, state, zip code).",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="collect_full_address",
                description="Call this ONLY after the patient has told you their full address. The address parameter should be the complete address they said. Only parse out the address component (street number, street name, city, state, zip code) from the user's response.",
                properties={
                    "address": {
                        "type": "string",
                        "description": "The full address (street number, street name, city, state, zip code) as stated by the patient",
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
                "content": f"The patient said their address is '{address}'. You MUST spell it out character by character for confirmation. Say EXACTLY: 'Let me confirm your address character by character. Is it {spaced_address}?' Make sure to pronounce each character and digit separately with clear pauses between them. When you see double spaces, pause slightly longer. When you see 'comma', say the word 'comma'.\n\nDo NOT call any function yet - wait for their response.\n\nCRITICAL INSTRUCTIONS FOR FUNCTION CALL:\n1. After the patient responds, you MUST call the 'confirm_full_address' function ONE TIME.\n2. If the patient says 'yes', 'correct', 'that's right', or similar affirmative, call the function with 'confirmed' set to true, and 'corrected_address' set to an empty string.\n3. If the patient says 'no', provides ANY correction, or indicates the spelling is wrong in ANY way, you MUST call the function with 'confirmed' set to false, and 'corrected_address' set to the complete, corrected address they provided. Do NOT set 'confirmed' to true in this case.\n4. Ensure 'corrected_address' is the full address string, not just a part of it.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="confirm_full_address",
                description="Call this ONLY after the patient responds to your address confirmation. Follow CRITICAL INSTRUCTIONS: set confirmed=true ONLY if they agree. If they provide ANY different spelling or say no, set confirmed=false and provide the full corrected_address.",
                properties={
                    "confirmed": {
                        "type": "boolean",
                        "description": "Set to true ONLY if patient explicitly confirms the exact spelling. Otherwise, set to false.",
                    },
                    "corrected_address": {
                        "type": "string",
                        "description": "The full corrected address if the patient said it was wrong or provided a new one. Only parse out the address component (street number, street name, city, state, zip code) from the user's response. Empty if confirmed.",
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
                "content": "I'm sorry, but I couldn't validate that address. This might be because the ZIP code doesn't match the city. You MUST say this and ask the patient to provide their address again. Say EXACTLY: 'I'm sorry, but I couldn't validate that address. This might be because the ZIP code doesn't match the city. Let's try again. Please tell me your complete address including street number, street name, city, state, and ZIP code.' Do NOT call any function yet - wait for their response. You should expect the user to provide their full address. Once they do, call the `restart_address_collection` function. Do not pass any arguments to it.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="restart_address_collection",
                description="Call this function ONLY AFTER the patient provides their full address again in response to the request for a re-validated address. This function takes no arguments.",
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
                "content": "I'm sorry, but I couldn't understand the format of your address. You MUST say this and ask the patient to provide their address again. Say EXACTLY: 'I'm sorry, but I couldn't understand the format of your address. Please provide your complete address in this format: street number and name, city, state abbreviation and ZIP code. For example: \"123 Main Street, New York, NY 10001\".' Do NOT call any function yet - wait for their response. You should expect the user to provide their full address. Once they do, call the `restart_address_collection` function. Do not pass any arguments to it.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="restart_address_collection",
                description="Call this function ONLY AFTER the patient provides their full address again in response to the request for a re-validated address. This function takes no arguments.",
                properties={},
                required=[],
                handler=restart_address_collection,
                transition_callback=handle_restart_full_address,
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
                "content": "Your first task is to ask for the patient's phone number. Say EXACTLY: 'What is your phone number? Please include the area code.' Do NOT call any function yet. You MUST wait for the patient to provide their phone number. Only AFTER the patient speaks their phone number, should you call the 'collect_phone' function with the number they provided.",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="collect_phone",
                description="Call this ONLY after the patient has actually spoken their phone number. The phone_number parameter must be the number the patient stated.",
                properties={"phone_number": {"type": "string"}},
                required=["phone_number"],
                handler=collect_phone,
                transition_callback=handle_phone_collection,
            )
        ],
    }


def create_ask_email_preference_node() -> NodeConfig:
    """Create node for asking email preference."""
    return {
        "task_messages": [
            {
                "role": "system",
                "content": "Your task is to ask the patient if they want to provide an email. Say EXACTLY: 'Would you like to provide an email address for appointment confirmations and reminders? This is optional, and you can choose not to provide one if you prefer.' Do NOT call any function yet. You MUST wait for the patient to respond with 'yes' or 'no'. Only AFTER the patient responds, call the 'ask_email_preference' function with their choice (true for yes, false for no).",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="ask_email_preference",
                description="Call this ONLY after the patient has explicitly said 'yes' or 'no' to providing an email. Set wants_email to true if they said yes, and false if they said no.",
                properties={
                    "wants_email": {
                        "type": "boolean",
                        "description": "True if patient wants to provide email, False if they prefer not to or said no",
                    }
                },
                required=["wants_email"],
                handler=ask_email_preference,
                transition_callback=handle_email_preference,
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


def create_confirm_email_node(email: str) -> NodeConfig:
    """Create node for confirming email spelling."""

    local_part = ""
    domain_part = ""
    if "@" in email:
        parts = email.split("@", 1)
        local_part = parts[0]
        if len(parts) > 1:
            domain_part = "@" + parts[1]
    else:
        local_part = email  # Treat the whole thing as local part if no @

    spaced_email_parts = []
    for char_local in local_part:
        char_lower = char_local.lower()
        if char_lower in NATO_PHONETIC_ALPHABET:
            # Format as "L as in PhoneticWord"
            spaced_email_parts.append(
                f"{char_local.upper()} as in {NATO_PHONETIC_ALPHABET[char_lower]}"
            )
        elif char_local.isdigit():
            spaced_email_parts.append(
                char_local
            )  # e.g., "3" - LLM will be instructed to read it
        elif char_lower == ".":
            spaced_email_parts.append("dot")
        elif char_lower == "-":
            spaced_email_parts.append("hyphen")
        elif char_lower == "_":
            spaced_email_parts.append("underscore")
        else:
            # Fallback for any other character in the local part
            spaced_email_parts.append(char_local)

    phonetic_local_str = " ".join(spaced_email_parts)

    if domain_part:
        spaced_domain_readable_parts = ["at sign"]
        for char_domain in domain_part[1:]:  # Skip the '@' itself
            if char_domain == ".":
                spaced_domain_readable_parts.append("dot")
            elif char_domain.isalnum():
                spaced_domain_readable_parts.append(char_domain)
            else:
                spaced_domain_readable_parts.append(
                    get_phonetic_representation(char_domain)
                )
        spaced_email = phonetic_local_str + " " + " ".join(spaced_domain_readable_parts)
    else:
        spaced_email = phonetic_local_str

    system_content = f"""
                    You are in an email spelling confirmation loop.
                    The patient's email is supposedly '{email}'.
                    The phonetic spelling you will use for confirmation is: '{spaced_email}'.

                    You MUST spell out the email for confirmation. Say EXACTLY:
                    'Let me confirm your email address. Is it {spaced_email}?'
                    Ensure you pronounce each phonetic element (like 'A as in Alpha', or 'dot', or a digit) clearly, with pauses between each element.

                    Do NOT call any function yet - wait for the patient's response to your question above.

                    AFTER the patient responds:
                    1. You MUST call the 'confirm_email_spelling' function EXACTLY ONCE.
                    2. If the patient clearly says 'yes', 'correct', or a similar direct affirmative AND offers NO different spelling or correction, then call the function with 'confirmed' set to true, and 'corrected_spelling' as an empty string.
                    3. If the patient says 'no', OR if they provide ANY correction, OR if they utter ANY different spelling (even if they also say 'yes'), you MUST call the function with 'confirmed' set to false. In this 'confirmed: false' case, the 'corrected_spelling' parameter is MANDATORY. It MUST be the complete email address derived EXCLUSIVELY from the patient's LATEST corrective statement. Convert their spoken correction (e.g., 'My email is alpha then s as in sam then d as in delta at new domain dot org') into a standard email string format (e.g., 'asd@newdomain.org'). PAY SPECIAL ATTENTION: If the patient spells out characters or uses phonetic clarifications (e.g., "that's an O as in Oscar, not zero", or "L for Lima"), prioritize these clarifications to resolve common speech-to-text ambiguities like O/0, I/1, S/5, G/6, B/8. For example, if Speech-to-Text provides 'zer0' but the user said 'O as in Oscar', ensure 'corrected_spelling' uses 'o'. DO NOT reuse or refer back to the '{email}' you initially proposed if they are correcting it; use ONLY what they just said.
                    4. Adhere to these rules strictly to avoid errors.
                    """

    return {
        "task_messages": [
            {
                "role": "system",
                "content": system_content,
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="confirm_email_spelling",
                description="Call this EXACTLY ONCE after the patient responds to email confirmation. If they confirm the exact spelling you proposed with NO changes, set confirmed=true. If they say NO, or provide ANY correction/alternative spelling, set confirmed=false and corrected_spelling MUST be the new complete email string from their LATEST response.",
                properties={
                    "confirmed": {
                        "type": "boolean",
                        "description": "TRUE only if patient explicitly confirmed your exact proposed spelling AND offered NO correction. FALSE if they said no, or provided ANY different spelling.",
                    },
                    "corrected_spelling": {
                        "type": "string",
                        "description": "MANDATORY if confirmed=false due to a correction. This MUST be the full corrected email address (e.g., 'user@example.com') derived ONLY from the patient's most recent corrective utterance. Empty if confirmed=true.",
                    },
                },
                required=["confirmed"],
                handler=confirm_email_spelling,
                transition_callback=handle_email_confirmation,
            )
        ],
    }


def create_schedule_appointment_node() -> NodeConfig:
    """Create node for appointment scheduling."""
    # Format appointments with doctor information
    available_times_str = "\\n".join(
        [
            f"- {apt['time']} with {apt['doctor']} ({apt['specialty']})"
            for apt in AVAILABLE_APPOINTMENTS
        ]
    )
    return {
        "task_messages": [
            {
                "role": "system",
                "content": f"""Your task is to offer the patient available appointment times and then record their choice.
First, you MUST say EXACTLY: 'Here are the available appointment times:
{available_times_str}

Which time works best for you?'
Make sure to include the doctor name and specialty for each time slot.
Do NOT call any function yet - just speak the available times and the question.
Only after the patient tells you their preferred time, you should call the 'select_appointment' function with their chosen time.""",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="select_appointment",
                description="Call this ONLY after the patient has told you which appointment time they prefer from the list you provided. The selected_time parameter should be the exact time string the patient chose.",
                properties={
                    "selected_time": {"type": "string", "enum": AVAILABLE_TIMES}
                },
                required=["selected_time"],
                handler=select_appointment,
                transition_callback=handle_appointment_selection,
            )
        ],
    }


def create_confirm_appointment_node(
    selected_time: str, doctor_name: str = None, doctor_specialty: str = None
) -> NodeConfig:
    """Create node for appointment confirmation."""
    if doctor_name and doctor_specialty:
        confirmation_text = f"Perfect! I have you scheduled for {selected_time} with {doctor_name} from {doctor_specialty}. We'll contact you with appointment details and any reminders."
        question_text = "Do you have any questions before we finish?"
        full_statement = f"{confirmation_text} {question_text}"
    else:
        # Fallback, ideally this isn't hit if data is consistent
        confirmation_text = f"Okay, I have your appointment for {selected_time} confirmed. We'll contact you with appointment details."
        question_text = "Do you have any other questions?"
        full_statement = f"{confirmation_text} {question_text}"

    return {
        "task_messages": [
            {
                "role": "system",
                "content": f"""You have successfully scheduled the appointment. Your task is now to confirm this with the patient and ask if they have any final questions.
You MUST say EXACTLY: '{full_statement}'
Do NOT call any function yet. Wait for the patient to respond to your question.
If they have no questions (e.g., say 'no', 'nope', 'all set'), then call 'end_intake'.
If they ask a question, answer it briefly if you can, and then call 'end_intake'.""",
            }
        ],
        "functions": [
            FlowsFunctionSchema(
                name="end_intake",
                description="Call this function ONLY after you have stated the appointment confirmation and asked if the patient has questions, AND the patient has responded (e.g., said 'no questions' or after you've answered a brief question).",
                properties={},  # No properties needed for end_intake
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
                "content": "Thank the patient for their time and remind them about their appointment with their assigned doctor. Let them know we'll contact them with appointment reminders using their preferred contact method. Mention that they will receive a confirmation email shortly if they provided an email address. End the conversation warmly.",
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
        "ask_email_preference": create_ask_email_preference_node(),
        "collect_email": create_collect_email_node(),
        "confirm_email": create_confirm_email_node(
            "placeholder"
        ),  # Will be updated dynamically
        "schedule_appointment": create_schedule_appointment_node(),
        "confirm_appointment": create_confirm_appointment_node(
            "placeholder"
        ),  # Will be updated dynamically
        "end": create_end_node(),
    },
}
