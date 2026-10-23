
"""Send verification emails using Gmail API."""

import base64
import logging
import os
from email.message import EmailMessage

import httpx
from fastapi import HTTPException
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.send"


def send_verification_email(recipient_email: str, otp_code: str):
    client_id = os.environ.get("GMAIL_CLIENT_ID", "")
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "")
    refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN", "")
    sender = os.environ.get("GMAIL_SENDER_EMAIL", "")

    if not all([client_id, client_secret, refresh_token, sender]):
        logger.error("Gmail OTP configuration is incomplete")
        raise HTTPException(
            503, "Verification email service is not configured."
        )

    try:
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=[GMAIL_SCOPE],
        )
        credentials.refresh(Request())

        message = EmailMessage()
        message["To"] = recipient_email
        message["From"] = sender
        message["Subject"] = "ImmXrsive verification code"
        message.set_content(
            f"Your ImmXrsive verification code is {otp_code}.\n"
            "Do not share this code."
        )

        raw = base64.urlsafe_b64encode(
            message.as_bytes()
        ).decode("utf-8")

        response = httpx.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={
                "Authorization": f"Bearer {credentials.token}",
                "Content-Type": "application/json",
            },
            json={"raw": raw},
            timeout=15,
        )
        response.raise_for_status()

    except Exception as exc:
        logger.error(
            "Gmail OTP send failed: %s",
            type(exc).__name__
        )
        raise HTTPException(
            503, "Verification email could not be sent."
        ) from exc
