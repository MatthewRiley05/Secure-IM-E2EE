from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRegister(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr | None = None
    password: str = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    id: int
    username: str
    email: EmailStr | None = None
    model_config = ConfigDict(from_attributes=True)


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


# --- Key Management Schemas ---

class PublicKeyUpload(BaseModel):
    public_key: str  # base64-encoded raw public key bytes

class PublicKeyResponse(BaseModel):
    user_id: int
    username: str
    public_key: str
    key_type: str
    uploaded_at: str
    key_changed: bool = False  # true if key differs from what was stored before

class FingerprintResponse(BaseModel):
    username: str
    fingerprint: str  # hex-formatted SHA-256 of the raw public key
    public_key: str


# --- Messaging Schemas ---

class MessageSendRequest(BaseModel):
    receiver_username: str
    ciphertext: dict
    ttl_seconds: int | None = Field(default=None, ge=1, le=604800)


class MessageStatusResponse(BaseModel):
    id: int
    status: str
    delivered_at: str | None = None
    read_at: str | None = None


class MessageItemResponse(BaseModel):
    id: int
    sender_username: str
    receiver_username: str
    ciphertext: dict
    status: str
    created_at: str
    delivered_at: str | None = None
    read_at: str | None = None
    expires_at: str | None = None


class MessageListResponse(BaseModel):
    messages: list[MessageItemResponse]
    total: int
    page: int
    page_size: int


class PendingMessageResponse(BaseModel):
    messages: list[MessageItemResponse]
    total: int


class MarkReadResponse(BaseModel):
    conversation_id: int
    marked_read: int


class SendMessageResponse(BaseModel):
    message_id: int
    status: str
    created_at: str
    expires_at: str | None = None
