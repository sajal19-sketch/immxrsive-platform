from pydantic import BaseModel, EmailStr, field_validator
from typing import List

class VerificationRequest(BaseModel):
    email: EmailStr

    @field_validator("email", mode="after")
    @classmethod
    def must_be_algoma(cls, v: str) -> str:
        if not v.lower().endswith("@algomau.ca"):
            raise ValueError("Email must end with @algomau.ca")
        return v.lower()

class VerificationSubmit(BaseModel):
    email: EmailStr
    code: str

class ProfileUpdate(BaseModel):
    email: str  # Changed from EmailStr to prevent Render DNS blocking
    name: str
    headline: str
    skills: List[str]
    availability: List[str]