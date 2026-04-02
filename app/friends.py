from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy.orm import Session
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.db import get_db
from app.models import (
    User,
    FriendRequest,
    FriendRequestStatus,
    Friendship,
    Block,
    Conversation,
)
from app.auth import get_current_session
from app.schemas import (
    FriendRequestSend,
    FriendRequestAction,
    FriendRequestResponse,
    FriendResponse,
    FriendListResponse,
    BlockUser,
    BlockResponse,
    ConversationResponse,
    ConversationListResponse,
    MessageCheckResponse,
)
from app.security import check_rate_limit

router = APIRouter(prefix="/friends", tags=["friends"])


def get_authenticated_user(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> User:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    session = get_current_session(token, db)
    user = db.query(User).filter(User.id == session.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def get_user_by_username(username: str, db: Session) -> User:
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def get_username_map(user_ids: set[int], db: Session) -> dict[int, str]:
    if not user_ids:
        return {}
    rows = db.query(User.id, User.username).filter(User.id.in_(user_ids)).all()
    return {user_id: username for user_id, username in rows}


def are_friends(user_id: int, other_id: int, db: Session) -> bool:
    return db.query(Friendship).filter(
        or_(
            (Friendship.user_id == user_id) & (Friendship.friend_id == other_id),
            (Friendship.user_id == other_id) & (Friendship.friend_id == user_id),
        )
    ).first() is not None


def is_blocked(user_id: int, other_id: int, db: Session) -> bool:
    return db.query(Block).filter(
        or_(
            (Block.blocker_id == user_id) & (Block.blocked_id == other_id),
            (Block.blocker_id == other_id) & (Block.blocked_id == user_id),
        )
    ).first() is not None


# --- Friend Request Endpoints ---

@router.post("/request/send")
def send_friend_request(
    data: FriendRequestSend,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):
    check_rate_limit(f"friend_request:{user.id}", limit=10, window_seconds=60)

    target = get_user_by_username(data.username, db)

    if user.id == target.id:
        raise HTTPException(status_code=400, detail="Cannot send request to yourself")

    if are_friends(user.id, target.id, db):
        raise HTTPException(status_code=400, detail="Already friends")

    if is_blocked(user.id, target.id, db):
        raise HTTPException(status_code=403, detail="User is blocked")

    existing = db.query(FriendRequest).filter(
        FriendRequest.from_user_id == user.id,
        FriendRequest.to_user_id == target.id,
    ).first()
    if existing:
        if existing.status == FriendRequestStatus.PENDING.value:
            raise HTTPException(status_code=400, detail="Friend request already sent")
        existing.status = FriendRequestStatus.PENDING.value
        db.commit()
        db.refresh(existing)
        return {"message": "Friend request resent", "request_id": existing.id}

    reverse = db.query(FriendRequest).filter(
        FriendRequest.from_user_id == target.id,
        FriendRequest.to_user_id == user.id,
        FriendRequest.status == FriendRequestStatus.PENDING.value,
    ).first()
    if reverse:
        raise HTTPException(status_code=400, detail="This user has already sent you a request")

    request = FriendRequest(
        from_user_id=user.id,
        to_user_id=target.id,
        status=FriendRequestStatus.PENDING.value,
    )
    db.add(request)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Friend request already exists")
    db.refresh(request)

    return {"message": "Friend request sent", "request_id": request.id}


@router.post("/request/accept")
def accept_friend_request(
    data: FriendRequestAction,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):

    request = db.query(FriendRequest).filter(
        FriendRequest.id == data.request_id,
        FriendRequest.to_user_id == user.id,
        FriendRequest.status == FriendRequestStatus.PENDING.value,
    ).first()
    if not request:
        raise HTTPException(status_code=404, detail="Friend request not found")

    request.status = FriendRequestStatus.ACCEPTED.value

    friendship1 = Friendship(user_id=request.from_user_id, friend_id=request.to_user_id)
    friendship2 = Friendship(user_id=request.to_user_id, friend_id=request.from_user_id)
    db.add(friendship1)
    db.add(friendship2)

    conversation = Conversation(
        user1_id=min(request.from_user_id, request.to_user_id),
        user2_id=max(request.from_user_id, request.to_user_id),
    )
    db.add(conversation)

    db.commit()
    return {"message": "Friend request accepted"}


@router.post("/request/decline")
def decline_friend_request(
    data: FriendRequestAction,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):

    request = db.query(FriendRequest).filter(
        FriendRequest.id == data.request_id,
        FriendRequest.to_user_id == user.id,
        FriendRequest.status == FriendRequestStatus.PENDING.value,
    ).first()
    if not request:
        raise HTTPException(status_code=404, detail="Friend request not found")

    request.status = FriendRequestStatus.DECLINED.value
    db.commit()
    return {"message": "Friend request declined"}


@router.post("/request/cancel")
def cancel_friend_request(
    data: FriendRequestAction,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):

    request = db.query(FriendRequest).filter(
        FriendRequest.id == data.request_id,
        FriendRequest.from_user_id == user.id,
        FriendRequest.status == FriendRequestStatus.PENDING.value,
    ).first()
    if not request:
        raise HTTPException(status_code=404, detail="Friend request not found")

    request.status = FriendRequestStatus.CANCELLED.value
    db.commit()
    return {"message": "Friend request cancelled"}


@router.get("/requests/incoming", response_model=list[FriendRequestResponse])
def get_incoming_requests(
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):

    requests = db.query(FriendRequest).filter(
        FriendRequest.to_user_id == user.id,
        FriendRequest.status == FriendRequestStatus.PENDING.value,
    ).all()

    username_map = get_username_map({req.from_user_id for req in requests}, db)

    results = []
    for req in requests:
        results.append(FriendRequestResponse(
            id=req.id,
            from_user_id=req.from_user_id,
            to_user_id=req.to_user_id,
            status=req.status,
            created_at=req.created_at.isoformat(),
            from_username=username_map.get(req.from_user_id),
        ))
    return results


@router.get("/requests/outgoing", response_model=list[FriendRequestResponse])
def get_outgoing_requests(
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):

    requests = db.query(FriendRequest).filter(
        FriendRequest.from_user_id == user.id,
        FriendRequest.status == FriendRequestStatus.PENDING.value,
    ).all()

    username_map = get_username_map({req.to_user_id for req in requests}, db)

    results = []
    for req in requests:
        results.append(FriendRequestResponse(
            id=req.id,
            from_user_id=req.from_user_id,
            to_user_id=req.to_user_id,
            status=req.status,
            created_at=req.created_at.isoformat(),
            to_username=username_map.get(req.to_user_id),
        ))
    return results


# --- Friend Management ---

@router.get("/list", response_model=FriendListResponse)
def list_friends(
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):

    friendships = db.query(Friendship).filter(Friendship.user_id == user.id).all()

    username_map = get_username_map({f.friend_id for f in friendships}, db)

    friends = []
    for f in friendships:
        username = username_map.get(f.friend_id)
        if username:
            friends.append(FriendResponse(id=f.friend_id, username=username))

    return FriendListResponse(friends=friends, total=len(friends))


@router.delete("/remove/{username}")
def remove_friend(
    username: str,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):
    friend = get_user_by_username(username, db)

    friendship1 = db.query(Friendship).filter(
        Friendship.user_id == user.id, Friendship.friend_id == friend.id
    ).first()
    friendship2 = db.query(Friendship).filter(
        Friendship.user_id == friend.id, Friendship.friend_id == user.id
    ).first()

    if not friendship1 and not friendship2:
        raise HTTPException(status_code=404, detail="Not friends")

    if friendship1:
        db.delete(friendship1)
    if friendship2:
        db.delete(friendship2)

    conv = db.query(Conversation).filter(
        or_(
            (Conversation.user1_id == min(user.id, friend.id)) & (Conversation.user2_id == max(user.id, friend.id)),
        )
    ).first()
    if conv:
        db.delete(conv)

    db.commit()
    return {"message": "Friend removed"}


# --- Block ---

@router.post("/block")
def block_user(
    data: BlockUser,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):
    target = get_user_by_username(data.username, db)

    if user.id == target.id:
        raise HTTPException(status_code=400, detail="Cannot block yourself")

    existing = db.query(Block).filter(
        Block.blocker_id == user.id, Block.blocked_id == target.id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Already blocked")

    block = Block(blocker_id=user.id, blocked_id=target.id)
    db.add(block)

    friendship1 = db.query(Friendship).filter(
        Friendship.user_id == user.id, Friendship.friend_id == target.id
    ).first()
    friendship2 = db.query(Friendship).filter(
        Friendship.user_id == target.id, Friendship.friend_id == user.id
    ).first()
    if friendship1:
        db.delete(friendship1)
    if friendship2:
        db.delete(friendship2)

    pending = db.query(FriendRequest).filter(
        FriendRequest.status == FriendRequestStatus.PENDING.value,
        or_(
            (FriendRequest.from_user_id == user.id) & (FriendRequest.to_user_id == target.id),
            (FriendRequest.from_user_id == target.id) & (FriendRequest.to_user_id == user.id),
        ),
    ).all()
    for req in pending:
        db.delete(req)

    db.commit()
    return {"message": f"User {target.username} blocked"}


@router.delete("/unblock/{username}")
def unblock_user(
    username: str,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):
    target = get_user_by_username(username, db)

    block = db.query(Block).filter(
        Block.blocker_id == user.id, Block.blocked_id == target.id
    ).first()
    if not block:
        raise HTTPException(status_code=404, detail="User is not blocked")

    db.delete(block)
    db.commit()
    return {"message": f"User {target.username} unblocked"}


@router.get("/blocked", response_model=list[BlockResponse])
def list_blocked_users(
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):

    blocks = db.query(Block).filter(Block.blocker_id == user.id).all()

    username_map = get_username_map({b.blocked_id for b in blocks}, db)

    results = []
    for b in blocks:
        results.append(BlockResponse(
            id=b.id,
            blocker_id=b.blocker_id,
            blocked_id=b.blocked_id,
            blocked_username=username_map.get(b.blocked_id, "unknown"),
            created_at=b.created_at.isoformat(),
        ))
    return results


# --- Anti-Spam Check ---

@router.get("/can-message/{username}", response_model=MessageCheckResponse)
def can_message(
    username: str,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):
    target = get_user_by_username(username, db)

    if user.id == target.id:
        return MessageCheckResponse(allowed=True)

    if is_blocked(user.id, target.id, db):
        return MessageCheckResponse(allowed=False, reason="One of you has blocked the other")

    if not are_friends(user.id, target.id, db):
        return MessageCheckResponse(allowed=False, reason="You must be friends to message this user")

    return MessageCheckResponse(allowed=True)


# --- Conversations ---

@router.get("/conversations", response_model=ConversationListResponse)
def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):
    query = db.query(Conversation).filter(
        or_(Conversation.user1_id == user.id, Conversation.user2_id == user.id)
    )

    total = query.count()
    conversations = query.order_by(Conversation.updated_at.desc()) \
        .offset((page - 1) * page_size) \
        .limit(page_size) \
        .all()

    other_user_ids = set()
    for conv in conversations:
        if conv.user1_id == user.id:
            other_user_ids.add(conv.user2_id)
        else:
            other_user_ids.add(conv.user1_id)

    username_map = get_username_map(other_user_ids, db)

    results = []
    for conv in conversations:
        if conv.user1_id == user.id:
            other_id = conv.user2_id
            unread = conv.user1_unread
        else:
            other_id = conv.user1_id
            unread = conv.user2_unread

        results.append(ConversationResponse(
            id=conv.id,
            other_user_id=other_id,
            other_username=username_map.get(other_id, "unknown"),
            unread_count=unread,
            updated_at=conv.updated_at.isoformat(),
        ))

    return ConversationListResponse(
        conversations=results,
        total=total,
        page=page,
        page_size=page_size,
    )
