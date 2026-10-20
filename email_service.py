import smtplib
from email.message import EmailMessage

# Put your actual email and 16-letter App Password here
SENDER_EMAIL = "your.personal.email@gmail.com"
APP_PASSWORD = "fvimrutpuehbcozx" 

def send_verification_email(recipient_email: str, otp_code: str):
    """Sends the 6-digit OTP to the Algoma email address using TLS."""
    msg = EmailMessage()
    msg['Subject'] = 'Your ImmXrsive Verification Code'
    msg['From'] = SENDER_EMAIL
    msg['To'] = recipient_email
    
    msg.set_content(f"""
    Hello,
    
    Your verification code for the ImmXrsive Platform is: {otp_code}
    
    This code will expire in 10 minutes. 
    
    If you did not request this, please ignore this email.
    """)

    try:
        # Connect to Gmail's SMTP server using port 587 (STARTTLS)
        with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
            smtp.ehlo()
            smtp.starttls() # Secure the connection
            smtp.ehlo()
            smtp.login(SENDER_EMAIL, APP_PASSWORD)
            smtp.send_message(msg)
            print(f"Successfully sent email to {recipient_email}")
    except Exception as e:
        print(f"Failed to send email: {e}")