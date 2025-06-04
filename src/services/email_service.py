import smtplib
import ssl
import os
import logging
from email.mime.text import MIMEText
from typing import Dict, Any, List
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class EmailService:
    """
    Service for sending email notifications about patient appointments.
    Note: If using an email provider like Gmail with 2-Factor Authentication (2FA) enabled,
    the SMTP_SENDER_PASSWORD environment variable should be set to an App Password
    generated from your email account settings.
    """

    def __init__(self):
        """
        Initialize the email service with SMTP configuration from environment variables.
        SMTP_SENDER_PASSWORD should be an App Password if your email provider (e.g., Gmail with 2FA) requires it.
        """
        self.sender_email = os.getenv("SMTP_SENDER_EMAIL")
        self.sender_password = os.getenv("SMTP_SENDER_PASSWORD")
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))

        # Validate configuration
        if not all([self.sender_email, self.sender_password]):
            logger.warning(
                "Email service not fully configured. SMTP credentials missing. "
                "Ensure SMTP_SENDER_EMAIL and SMTP_SENDER_PASSWORD (potentially an App Password) are set."
            )
        else:
            logger.info("EmailService initialized for sending emails.")

    async def send_appointment_confirmation(
        self, recipient_email: str, appointment_details: Dict[str, str]
    ) -> bool:
        """
        Send appointment confirmation email to the specified recipient.

        Args:
            recipient_email: The email address of the recipient (patient).
            appointment_details: Dictionary with appointment details.

        Returns:
            bool: True if email sent successfully, False otherwise
        """
        if not self._is_configured():
            logger.error(
                "Email service sender not properly configured. Cannot send email."
            )
            return False

        if not recipient_email:
            logger.error("No recipient email provided. Cannot send email.")
            return False

        try:
            subject = "Your Upcoming Appointment Confirmation"
            body = self._create_email_body(appointment_details)

            # Create email message
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = self.sender_email
            msg["To"] = recipient_email

            # Send email using SMTP
            context = ssl.create_default_context()

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.ehlo()  # Extended Hello
                server.starttls(context=context)  # Upgrade connection to TLS
                server.ehlo()  # Re-identify over secure connection
                server.login(self.sender_email, self.sender_password)
                server.sendmail(self.sender_email, recipient_email, msg.as_string())

            logger.info(
                f"Appointment confirmation email sent successfully to {recipient_email}"
            )
            return True

        except smtplib.SMTPAuthenticationError as e:
            logger.error(
                f"SMTP Authentication Error: {e}. "
                "Check sender email/password. If using a service like Gmail with 2FA, "
                "ensure an App Password is configured and used as SMTP_SENDER_PASSWORD."
            )
            return False
        except smtplib.SMTPServerDisconnected as e:
            logger.error(
                f"SMTP Server Disconnected: {e}. Check server address, port, or network connection."
            )
            return False
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error occurred: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error while sending email: {e}")
            return False

    def _create_email_body(self, appointment_details: Dict[str, str]) -> str:
        """Create the email body content with only appointment information."""

        body = f"""Dear Patient,

This email confirms your upcoming medical appointment.

Appointment Details:
-------------------
Doctor: {appointment_details.get('doctor', 'N/A')}
Date & Time: {appointment_details.get('time', 'N/A')}
Specialty: {appointment_details.get('specialty', 'N/A')}

If you have any questions or need to reschedule, please contact our office.

Thank you,
Assort Health Clinic
"""
        return body

    def _is_configured(self) -> bool:
        """Check if the email service's sender details are properly configured."""
        return all(
            [
                self.sender_email,
                self.sender_password,
                self.smtp_server,
                self.smtp_port,
            ]
        )

    def get_configuration_status(self) -> Dict[str, Any]:
        """Get the configuration status for debugging purposes."""
        return {
            "sender_email_configured": bool(self.sender_email),
            "sender_password_configured": bool(self.sender_password),
            "smtp_server": self.smtp_server,
            "smtp_port": self.smtp_port,
            "sender_fully_configured": self._is_configured(),
        }
