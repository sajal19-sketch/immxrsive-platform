import os
import resend

def send_verification_email(recipient_email: str, otp_code: str):
    key = os.environ.get('RESEND_API_KEY')
    if not key:
        raise RuntimeError('RESEND_API_KEY not configured. Contact the operator.')
    resend.api_key = key
    try:
        resend.Emails.send({
            'from': os.environ.get('RESEND_FROM_EMAIL','onboarding@resend.dev'),
            'to': recipient_email,
            'subject': 'ImmXrsive Algoma verification code',
            'text': f'Your ImmXrsive verification code is {otp_code}. It expires shortly. If you did not request this, ignore this message.'
        })
    except Exception:
        raise RuntimeError('Email delivery failed. Check configured sender/domain and try again.')
