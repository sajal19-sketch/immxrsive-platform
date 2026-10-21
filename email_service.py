"""Send verified student OTP. The API key is stored only in Render environment."""
import os
import httpx
from fastapi import HTTPException

def send_verification_email(recipient_email: str, otp_code: str):
    key=os.environ.get('RESEND_API_KEY','')
    sender=os.environ.get('VERIFICATION_FROM_EMAIL','onboarding@resend.dev')
    if not key:raise HTTPException(503,'Verification email service is not configured.')
    try:
        response=httpx.post('https://api.resend.com/emails',headers={
          'Authorization':f'Bearer {key}', 'Content-Type':'application/json'},json={
          'from':sender,'to':[recipient_email], 'subject':'ImmXrsive student verification',
          'html':f'<p>Your ImmXrsive one-time code is <strong>{otp_code}</strong>.</p><p>It expires shortly. Do not share it.</p>'
        },timeout=12)
        response.raise_for_status()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503,'Verification email could not be sent. Contact the team; verify your sender domain and try again.')
