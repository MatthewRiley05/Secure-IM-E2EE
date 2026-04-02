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


# --- Friend Request Schemas ---

class FriendRequestSend(BaseModel):
    username: str


class FriendRequestAction(BaseModel):
    request_id: int


class FriendRequestResponse(BaseModel):
    id: int
    from_user_id: int
    to_user_id: int
    status: str
    created_at: str
    from_username: str | None = None
    to_username: str | None = None


# --- Friend Schemas ---

class FriendResponse(BaseModel):
    id: int
    username: str


class FriendListResponse(BaseModel):
    friends: list[FriendResponse]
    total: int


# --- Block Schemas ---

class BlockUser(BaseModel):
    username: str


class BlockResponse(BaseModel):
    id: int
    blocker_id: int
    blocked_id: int
    blocked_username: str
    created_at: str


# --- Conversation Schemas ---

class ConversationResponse(BaseModel):
    id: int
    other_user_id: int
    other_username: str
    unread_count: int
    updated_at: str


class ConversationListResponse(BaseModel):
    conversations: list[ConversationResponse]
    total: int
    page: int
    page_size: int


class MessageCheckResponse(BaseModel):
    allowed: bool
    reason: str | None = None