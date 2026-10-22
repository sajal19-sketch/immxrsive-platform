
"""Send student verification codes using Resend."""

import logging
import os

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)


def send_verification_email(recipient_email: str, otp_code: str):
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    sender = os.environ.get("VERIFICATION_FROM_EMAIL", "").strip()

    if not api_key or not sender:
        logger.error("OTP email sender or API key is not configured")
        raise HTTPException(
            status_code=503,
            detail="Verification email service is not configured."
        )

    payload = {
        "from": sender,
        "to": [recipient_email],
        "subject": "ImmXrsive student verification",
        "html": (
            "<p>Your ImmXrsive verification code is "
            f"<strong>{otp_code}</strong>.</p>"
            "<p>It expires shortly. Do not share it.</p>"
        ),
    }

    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=12,
        )
        response.raise_for_status()

    except httpx.HTTPStatusError as exc:
        error_code = "unknown"
        try:
            error_code = str(exc.response.json().get("name", "unknown"))
        except (ValueError, AttributeError):
            pass

        logger.error(
            "Resend rejected OTP email: HTTP %s, error=%s",
            exc.response.status_code,
            error_code,
        )
        raise HTTPException(
            status_code=503,
            detail="Verification email could not be sent."
        ) from exc

    except httpx.RequestError as exc:
        logger.error("Resend email request failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="Verification email service is temporarily unavailable."
        ) from exc
