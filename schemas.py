from pydantic import BaseModel, EmailStr
class VerificationRequest(BaseModel):
    email: EmailStr
class VerificationSubmit(BaseModel):
    email: EmailStr
    code: str
