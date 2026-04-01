from pydantic import BaseModel, EmailStr, Field


class UserRegister(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr | None = None
    password: str = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    id: int
    username: str
    email: EmailStr | None = None

    class Config:
        from_attributes = True


class RegisterResponse(BaseModel):
    id: int
    username: str
    email: EmailStr | None = None
    otp_secret: str
    otp_uri: str


class UserLogin(BaseModel):
    username: str
    password: str
    otp_code: str = Field(min_length=6, max_length=6)


class LogoutRequest(BaseModel):
    token: str


class LoginResponse(BaseModel):
    message: str
    token: str
    expires_at: str