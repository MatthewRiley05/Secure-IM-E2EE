import json
from datetime import datetime

from app.db import SessionLocal
from app.models import Conversation, Friendship, Message, MessageStatus, User
from app.security import generate_otp_secret, hash_password


def get_or_create_user(db, username: str, email: str, password: str) -> User:
    user = db.query(User).filter(User.username == username).first()
    if user:
        return user

    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        otp_secret=generate_otp_secret(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def ensure_friendship(db, user_a: User, user_b: User) -> None:
    existing_ab = db.query(Friendship).filter(
        Friendship.user_id == user_a.id,
        Friendship.friend_id == user_b.id,
    ).first()
    if not existing_ab:
        db.add(Friendship(user_id=user_a.id, friend_id=user_b.id))

    existing_ba = db.query(Friendship).filter(
        Friendship.user_id == user_b.id,
        Friendship.friend_id == user_a.id,
    ).first()
    if not existing_ba:
        db.add(Friendship(user_id=user_b.id, friend_id=user_a.id))

    db.commit()


def get_or_create_conversation(db, user_a: User, user_b: User) -> Conversation:
    user1 = min(user_a.id, user_b.id)
    user2 = max(user_a.id, user_b.id)
    conversation = db.query(Conversation).filter(
        Conversation.user1_id == user1,
        Conversation.user2_id == user2,
    ).first()
    if conversation:
        return conversation

    conversation = Conversation(user1_id=user1, user2_id=user2)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def seed_messages(db, alice: User, bob: User, conversation: Conversation) -> int:
    existing_count = db.query(Message).filter(Message.conversation_id == conversation.id).count()
    if existing_count > 0:
        return 0

    now_ms = int(datetime.utcnow().timestamp() * 1000)
    samples = [
        {
            "sender": alice,
            "receiver": bob,
            "counter": 1,
            "status": MessageStatus.DELIVERED.value,
            "is_read": True,
            "payload": {
                "ciphertext": "demo_ciphertext_1",
                "iv": "demo_iv_1",
                "metadata": {
                    "sender": "alice",
                    "receiver": "bob",
                    "counter": 1,
                    "timestamp": now_ms,
                },
            },
        },
        {
            "sender": bob,
            "receiver": alice,
            "counter": 1,
            "status": MessageStatus.SENT.value,
            "is_read": False,
            "payload": {
                "ciphertext": "demo_ciphertext_2",
                "iv": "demo_iv_2",
                "metadata": {
                    "sender": "bob",
                    "receiver": "alice",
                    "counter": 1,
                    "timestamp": now_ms + 1000,
                },
            },
        },
    ]

    created = 0
    for sample in samples:
        msg = Message(
            conversation_id=conversation.id,
            sender_id=sample["sender"].id,
            receiver_id=sample["receiver"].id,
            ciphertext_json=json.dumps(sample["payload"]),
            status=sample["status"],
            is_read=sample["is_read"],
        )
        db.add(msg)
        created += 1

    if conversation.user1_id == alice.id:
        conversation.user1_unread = 1
    else:
        conversation.user2_unread = 1

    db.commit()
    return created


def main() -> None:
    db = SessionLocal()
    try:
        alice = get_or_create_user(db, "alice", "alice@example.com", "Password123")
        bob = get_or_create_user(db, "bob", "bob@example.com", "Password123")

        ensure_friendship(db, alice, bob)
        conversation = get_or_create_conversation(db, alice, bob)
        created = seed_messages(db, alice, bob, conversation)

        print("Demo seed completed")
        print(f"Users: alice, bob")
        print(f"Conversation ID: {conversation.id}")
        print(f"New messages inserted: {created}")
        print("Passwords: Password123 / Password123")
        print("Use /register in UI if you need OTP provisioning for fresh login flows.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
