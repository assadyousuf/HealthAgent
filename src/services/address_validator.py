import os
import time
import asyncio
import aiohttp
from typing import Dict, Optional, Any
from dotenv import load_dotenv
from loguru import logger

# Load environment variables
load_dotenv(override=True)


class AddressValidator:
    """
    A class to validate addresses using the USPS API v3 with OAuth 2.0.
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        use_test_env: bool = False,
    ):
        """
        Initialize the AddressValidator with USPS API v3 credentials.

        Args:
            client_id (Optional[str]): USPS API Client ID. Defaults to env var USPS_CLIENT_ID.
            client_secret (Optional[str]): USPS API Client Secret. Defaults to env var USPS_CLIENT_SECRET.
            use_test_env (bool): Whether to use the USPS Test Environment. Defaults to False.
                                 Can be overridden by env var USPS_USE_TEST_ENV.
        """
        self.client_id = client_id or os.getenv("USPS_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("USPS_CLIENT_SECRET")

        # Determine if using test environment
        env_use_test_env = os.getenv("USPS_USE_TEST_ENV", "false").lower()
        self.use_test_env = use_test_env or (env_use_test_env == "true")

        if not self.client_id or not self.client_secret:
            logger.error(
                "USPS_CLIENT_ID or USPS_CLIENT_SECRET not provided or found in environment variables."
            )
            raise ValueError("USPS Client ID and Client Secret are required.")

        self.base_url = (
            "https://apis-tem.usps.com"
            if self.use_test_env
            else "https://apis.usps.com"
        )
        self.oauth_url = f"{self.base_url}/oauth2/v3/token"
        self.address_api_url = f"{self.base_url}/addresses/v3/address"

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._session: Optional[aiohttp.ClientSession] = None
        self._lock = asyncio.Lock()  # To prevent multiple token fetches concurrently

        logger.info(
            f"AddressValidator initialized. Using {'Test' if self.use_test_env else 'Production'} USPS API environment."
        )

    async def _get_http_session(self) -> aiohttp.ClientSession:
        """Initializes and returns an aiohttp.ClientSession."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _get_access_token(self) -> Optional[str]:
        """
        Retrieves an OAuth access token from USPS, caching it until expiration.
        This method is now thread-safe using asyncio.Lock.
        """
        async with self._lock:  # Ensure only one coroutine attempts to refresh the token at a time
            if self._access_token and time.time() < self._token_expires_at:
                return self._access_token

            logger.info("Access token is missing or expired, fetching new token...")
            session = await self._get_http_session()
            payload = {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            }
            headers = {"Content-Type": "application/json"}

            try:
                async with session.post(
                    self.oauth_url, json=payload, headers=headers
                ) as response:
                    response_data = await response.json()
                    if response.status == 200 and "access_token" in response_data:
                        self._access_token = response_data["access_token"]
                        expires_in = int(
                            response_data.get("expires_in", 3599)
                        )  # Default to 59 mins (3540s) if not specified
                        self._token_expires_at = (
                            time.time() + expires_in - 60
                        )  # Subtract 1 min buffer
                        logger.info(
                            f"Successfully obtained new access token. Expires in {expires_in}s."
                        )
                        return self._access_token
                    else:
                        error_detail = (
                            response_data.get("error_description")
                            or response_data.get("error")
                            or str(response_data)
                        )
                        logger.error(
                            f"Failed to obtain access token. Status: {response.status}, Response: {error_detail}"
                        )
                        self._access_token = None
                        self._token_expires_at = 0
                        return None
            except aiohttp.ClientError as e:
                logger.error(f"HTTP client error during token fetch: {e}")
                self._access_token = None
                self._token_expires_at = 0
                return None
            except Exception as e:
                logger.error(f"Unexpected error during token fetch: {e}")
                self._access_token = None
                self._token_expires_at = 0
                return None

    async def validate_address(
        self,
        street1: str,
        city: str,
        state: str,  # Expects 2-letter abbreviation
        zip5: str,
        street2: Optional[str] = None,
        zip4: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validate an address using the USPS API v3.

        Args:
            street1 (str): Primary street address line.
            street2 (Optional[str]): Secondary street address line (e.g., Apt, Suite).
            city (str): City name.
            state (str): State (2-letter abbreviation).
            zip5 (str): 5-digit ZIP code.
            zip4 (Optional[str]): 4-digit ZIP+4 code.

        Returns:
            Dict[str, Any]: Validation result containing:
                - 'status': "VALID", "VALID_WITH_CHANGES", "INVALID", "AMBIGUOUS",
                            "VALID_WITH_ISSUES", "API_ERROR", "ERROR".
                - 'reason': A descriptive message.
                - 'validated_address': Standardized address if considered valid/correctable, else None.
                                     Keys: 'street1', 'street2', 'city', 'state', 'zip5', 'zip4'.
        """
        access_token = await self._get_access_token()
        if not access_token:
            return {
                "status": "API_ERROR",
                "reason": "Failed to obtain USPS API access token.",
                "validated_address": None,
            }

        session = await self._get_http_session()
        params = {
            "streetAddress": street1,
            "city": city,
            "state": state,
            "ZIPCode": zip5,
        }
        if street2:
            params["secondaryAddress"] = street2
        if (
            zip4
        ):  # The API example includes ZIPPlus4 in the request for address validation.
            params["ZIPPlus4"] = zip4

        headers = {
            "Authorization": f"Bearer {access_token}",
            "accept": "application/json",
        }

        try:
            logger.info(f"Sending address validation request to USPS: {params}")
            async with session.get(
                self.address_api_url, params=params, headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"USPS Address API response: {data}")

                    # Default to input if not found in response or response is minimal
                    addr_info = data.get("address", {})

                    # Corrected address components
                    res_street1 = addr_info.get("streetAddress", street1)
                    res_street2 = addr_info.get(
                        "secondaryAddress", street2 if street2 else ""
                    )  # Ensure empty string not None
                    res_city = addr_info.get("city", city)
                    res_state = addr_info.get("state", state)
                    res_zip5 = addr_info.get("ZIPCode", zip5)
                    res_zip4 = addr_info.get("ZIPPlus4", zip4 if zip4 else "")

                    validated_addr_payload = {
                        "street1": res_street1,
                        "street2": (
                            res_street2 if res_street2 else None
                        ),  # Convert empty string back to None if it was initially
                        "city": res_city,
                        "state": res_state,
                        "zip5": res_zip5,
                        "zip4": res_zip4 if res_zip4 else None,
                    }

                    # Check DPVConfirmation for primary validation status
                    dpv_confirmation = data.get("addressAdditionalInfo", {}).get(
                        "DPVConfirmation", "N"
                    )

                    input_addr_str = f"{street1} {street2 if street2 else ''}, {city}, {state} {zip5}{'-'+zip4 if zip4 else ''}".strip()
                    output_addr_str = f"{res_street1} {res_street2 if res_street2 else ''}, {res_city}, {res_state} {res_zip5}{'-'+res_zip4 if res_zip4 else ''}".strip()

                    # Determine status based on DPV and corrections
                    if (
                        dpv_confirmation == "Y"
                    ):  # Address is DPV confirmed as deliverable.
                        if (
                            input_addr_str.upper() != output_addr_str.upper()
                            or data.get("addressCorrections")
                        ):
                            return {
                                "status": "VALID_WITH_CHANGES",
                                "reason": "Address validated with corrections. "
                                + (
                                    data.get("addressCorrections", [{}])[0].get(
                                        "correctionText", ""
                                    )
                                    if data.get("addressCorrections")
                                    else ""
                                ),
                                "validated_address": validated_addr_payload,
                            }
                        return {
                            "status": "VALID",
                            "reason": "Address validated successfully.",
                            "validated_address": validated_addr_payload,
                        }
                    elif (
                        dpv_confirmation == "S"
                    ):  # Confirmed, but secondary number missing / incorrect.
                        return {
                            "status": "VALID_WITH_ISSUES",  # Or "AMBIGUOUS" if secondary is crucial
                            "reason": "Address confirmed, but requires attention to the secondary address unit (e.g., apartment, suite). "
                            + (
                                data.get("addressCorrections", [{}])[0].get(
                                    "correctionText", ""
                                )
                                if data.get("addressCorrections")
                                else "Please verify the apartment or suite number."
                            ),
                            "validated_address": validated_addr_payload,
                        }
                    elif (
                        dpv_confirmation == "D"
                    ):  # Confirmed, but primary number missing.
                        return {
                            "status": "VALID_WITH_ISSUES",
                            "reason": "Address confirmed, but the primary street number is missing or invalid. "
                            + (
                                data.get("addressCorrections", [{}])[0].get(
                                    "correctionText", ""
                                )
                                if data.get("addressCorrections")
                                else "Please verify the street number."
                            ),
                            "validated_address": validated_addr_payload,
                        }
                    elif dpv_confirmation == "N":  # Not DPV confirmed.
                        # Check for 'addressMatches' which suggests alternatives for ambiguous/invalid.
                        # The new API doesn't seem to have a direct 'addressMatches' like the old one for multiple suggestions.
                        # It might return an error directly or a single corrected version if possible.
                        # If DPV is 'N', it's generally invalid.
                        reason_parts = [
                            "Address could not be validated as deliverable."
                        ]
                        if data.get("addressAdditionalInfo", {}).get("DPVFootnotes"):
                            reason_parts.append(
                                "Footnotes: "
                                + data.get("addressAdditionalInfo", {}).get(
                                    "DPVFootnotes"
                                )
                            )
                        if data.get("addressCorrections"):
                            reason_parts.append(
                                "Corrections: "
                                + data.get("addressCorrections", [{}])[0].get(
                                    "correctionText", ""
                                )
                            )

                        return {
                            "status": "INVALID",
                            "reason": " ".join(reason_parts),
                            "validated_address": None,  # Or validated_addr_payload if some standardization occurred but still DPV 'N'
                        }
                    else:  # Unknown DPV code or issue
                        return {
                            "status": "UNKNOWN_DPV",  # A new status to reflect this. Bot needs to handle it.
                            "reason": f"Address validation returned an unhandled DPV status: {dpv_confirmation}.",
                            "validated_address": validated_addr_payload,  # Might still have some useful info
                        }

                elif (
                    response.status == 400
                ):  # Bad Request, often means invalid input format or unfindable
                    error_data = await response.json()
                    error_messages = [
                        err.get("message", "Unknown error detail")
                        for err in error_data.get("errors", [])
                    ]
                    logger.warning(
                        f"USPS Address API Bad Request (400): {error_messages}. Input: {params}"
                    )
                    return {
                        "status": "INVALID",  # Treat as invalid if API says bad request for address
                        "reason": (
                            "USPS API reported an issue with the address provided: "
                            + "; ".join(error_messages)
                            if error_messages
                            else "The address could not be found or was badly formatted."
                        ),
                        "validated_address": None,
                    }
                elif response.status == 401:  # Unauthorized - token issue
                    logger.error(
                        f"USPS Address API Unauthorized (401). Token might be invalid or expired."
                    )
                    self._access_token = None  # Force token refresh on next call
                    self._token_expires_at = 0
                    return {
                        "status": "API_ERROR",
                        "reason": "USPS API authorization failed. Please check credentials or token.",
                        "validated_address": None,
                    }
                else:
                    error_text = await response.text()
                    logger.error(
                        f"USPS Address API request failed. Status: {response.status}, Response: {error_text}"
                    )
                    return {
                        "status": "API_ERROR",
                        "reason": f"USPS API request failed with status {response.status}.",
                        "validated_address": None,
                    }
        except aiohttp.ClientError as e:
            logger.error(f"HTTP client error during address validation: {e}")
            return {
                "status": "API_ERROR",
                "reason": f"Network error during address validation: {e}",
                "validated_address": None,
            }
        except Exception as e:
            logger.error(f"Unexpected error during address validation: {e}")
            return {
                "status": "ERROR",
                "reason": f"An unexpected error occurred: {e}",
                "validated_address": None,
            }

    async def close_session(self):
        """Closes the aiohttp.ClientSession."""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("Aiohttp session closed.")
        self._session = None
