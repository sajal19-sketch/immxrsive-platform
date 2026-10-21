import resend
import os

# Securely load the API key from Render's environment variables
resend.api_key = os.environ.get("RESEND_API_KEY")

def send_verification_email(recipient_email: str, otp_code: str):
    """Sends the 6-digit OTP to the Algoma email address using Resend API."""
    
    # When using a free Resend account, the 'from' address MUST be onboarding@resend.dev
    try:
        params = {
            "from": "onboarding@resend.dev",
            "to": recipient_email,
            "subject": "Your ImmXrsive Verification Code",
            "html": f"""
            <div style="font-family: sans-serif; max-width: 500px; margin: 0 auto;">
                <h2>ImmXrsive Platform</h2>
                <p>Hello,</p>
                <p>Your verification code is: <strong style="font-size: 20px;">{otp_code}</strong></p>
                <p>This code will expire in 10 minutes.</p>
                <p style="color: #666; font-size: 12px;">If you did not request this, please ignore this email.</p>
            </div>
            """
        }
        
        # Send the email via Resend
        email = resend.Emails.send(params)
        print(f"Successfully sent email via Resend to {recipient_email}")
        
    except Exception as e:
        print(f"Failed to send email via Resend: {e}")