import base64
import os
import time

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.main import app
from app.security import rate_limit_store


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "test_im_server.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    rate_limit_store.clear()

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def register_and_login(client: TestClient, username: str, password: str) -> str:
    register_res = client.post(
        "/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
        },
    )
    assert register_res.status_code == 200
    otp_secret = register_res.json()["otp_secret"]

    otp_code = pyotp.TOTP(otp_secret).now()
    login_res = client.post(
        "/login",
        json={
            "username": username,
            "password": password,
            "otp_code": otp_code,
        },
    )
    assert login_res.status_code == 200
    return login_res.json()["token"]


def make_friends(client: TestClient, token_a: str, token_b: str, username_b: str):
    send_res = client.post(
        "/friends/request/send",
        headers=_auth(token_a),
        json={"username": username_b},
    )
    assert send_res.status_code == 200
    req_id = send_res.json()["request_id"]

    accept_res = client.post(
        "/friends/request/accept",
        headers=_auth(token_b),
        json={"request_id": req_id},
    )
    assert accept_res.status_code == 200


def upload_public_key(client: TestClient, token: str, raw_key: bytes | None = None) -> dict:
    key_bytes = raw_key or os.urandom(65)
    key_b64 = base64.b64encode(key_bytes).decode("ascii")
    res = client.post("/keys/upload", headers=_auth(token), json={"public_key": key_b64})
    assert res.status_code == 200
    return res.json()


def test_ui_workflow_happy_path(client: TestClient):
    token_jake = register_and_login(client, "jake", "Password123")
    token_alice = register_and_login(client, "alice_ui", "Password123")

    upload_public_key(client, token_jake)
    upload_public_key(client, token_alice)

    fp_res = client.get("/keys/fingerprint/alice_ui", headers=_auth(token_jake))
    assert fp_res.status_code == 200
    assert fp_res.json()["username"] == "alice_ui"
    assert fp_res.json()["fingerprint"]

    send_req = client.post(
        "/friends/request/send",
        headers=_auth(token_jake),
        json={"username": "alice_ui"},
    )
    assert send_req.status_code == 200
    request_id = send_req.json()["request_id"]

    outgoing = client.get("/friends/requests/outgoing", headers=_auth(token_jake))
    incoming = client.get("/friends/requests/incoming", headers=_auth(token_alice))
    assert outgoing.status_code == 200
    assert incoming.status_code == 200
    assert any(r["id"] == request_id for r in outgoing.json())
    assert any(r["id"] == request_id and r["from_username"] == "jake" for r in incoming.json())

    accept = client.post(
        "/friends/request/accept",
        headers=_auth(token_alice),
        json={"request_id": request_id},
    )
    assert accept.status_code == 200

    can_msg = client.get("/friends/can-message/alice_ui", headers=_auth(token_jake))
    assert can_msg.status_code == 200
    assert can_msg.json()["allowed"] is True

    send_res = client.post(
        "/messages/send",
        headers=_auth(token_jake),
        json={
            "receiver_username": "alice_ui",
            "ciphertext": {
                "ciphertext": "abc",
                "iv": "xyz",
                "metadata": {"sender": "jake", "receiver": "alice_ui", "counter": 1},
            },
        },
    )
    assert send_res.status_code == 200
    message_id = send_res.json()["message_id"]

    conversations = client.get("/friends/conversations", headers=_auth(token_alice))
    assert conversations.status_code == 200
    assert conversations.json()["conversations"][0]["other_username"] == "jake"
    assert conversations.json()["conversations"][0]["unread_count"] == 1

    pending = client.get("/messages/inbox/pending", headers=_auth(token_alice))
    assert pending.status_code == 200
    assert pending.json()["total"] == 1
    assert pending.json()["messages"][0]["status"] == "delivered"

    mark_read = client.post("/messages/read/jake", headers=_auth(token_alice))
    assert mark_read.status_code == 200
    assert mark_read.json()["marked_read"] == 1

    status = client.get(f"/messages/status/{message_id}", headers=_auth(token_jake))
    assert status.status_code == 200
    assert status.json()["status"] == "delivered"
    assert status.json()["read_at"] is not None


def test_friend_request_decline_and_cancel_lifecycle(client: TestClient):
    token_alice = register_and_login(client, "alice_req", "Password123")
    token_bob = register_and_login(client, "bob_req", "Password123")

    send1 = client.post(
        "/friends/request/send",
        headers=_auth(token_alice),
        json={"username": "bob_req"},
    )
    assert send1.status_code == 200
    request_id_1 = send1.json()["request_id"]

    decline = client.post(
        "/friends/request/decline",
        headers=_auth(token_bob),
        json={"request_id": request_id_1},
    )
    assert decline.status_code == 200

    send2 = client.post(
        "/friends/request/send",
        headers=_auth(token_alice),
        json={"username": "bob_req"},
    )
    assert send2.status_code == 200
    request_id_2 = send2.json()["request_id"]

    cancel = client.post(
        "/friends/request/cancel",
        headers=_auth(token_alice),
        json={"request_id": request_id_2},
    )
    assert cancel.status_code == 200

    outgoing = client.get("/friends/requests/outgoing", headers=_auth(token_alice))
    incoming = client.get("/friends/requests/incoming", headers=_auth(token_bob))
    assert outgoing.status_code == 200
    assert incoming.status_code == 200
    assert outgoing.json() == []
    assert incoming.json() == []


def test_block_unblock_hides_and_restores_friend_visibility(client: TestClient):
    token_alice = register_and_login(client, "alice_block", "Password123")
    token_bob = register_and_login(client, "bob_block", "Password123")
    make_friends(client, token_alice, token_bob, "bob_block")

    before = client.get("/friends/list", headers=_auth(token_alice))
    assert before.status_code == 200
    assert any(f["username"] == "bob_block" for f in before.json()["friends"])

    block = client.post(
        "/friends/block",
        headers=_auth(token_alice),
        json={"username": "bob_block"},
    )
    assert block.status_code == 200

    hidden = client.get("/friends/list", headers=_auth(token_alice))
    assert hidden.status_code == 200
    assert not any(f["username"] == "bob_block" for f in hidden.json()["friends"])

    blocked = client.get("/friends/blocked", headers=_auth(token_alice))
    assert blocked.status_code == 200
    assert any(b["blocked_username"] == "bob_block" for b in blocked.json())

    unblock = client.delete("/friends/unblock/bob_block", headers=_auth(token_alice))
    assert unblock.status_code == 200

    restored = client.get("/friends/list", headers=_auth(token_alice))
    assert restored.status_code == 200
    assert any(f["username"] == "bob_block" for f in restored.json()["friends"])


def test_key_change_detection_for_contact(client: TestClient):
    token_alice = register_and_login(client, "alice_key", "Password123")
    token_bob = register_and_login(client, "bob_key", "Password123")

    first = upload_public_key(client, token_alice, raw_key=b"A" * 65)
    assert first["key_changed"] is False

    lookup_before = client.get("/keys/alice_key", headers=_auth(token_bob))
    assert lookup_before.status_code == 200
    assert lookup_before.json()["key_changed"] is False

    second = upload_public_key(client, token_alice, raw_key=b"B" * 65)
    assert second["key_changed"] is True

    lookup_after = client.get("/keys/alice_key", headers=_auth(token_bob))
    assert lookup_after.status_code == 200
    assert lookup_after.json()["key_changed"] is True


def test_security_invalid_otp_rejected(client: TestClient):
    register_res = client.post(
        "/register",
        json={
            "username": "otp_user",
            "email": "otp_user@example.com",
            "password": "Password123",
        },
    )
    assert register_res.status_code == 200
    otp_secret = register_res.json()["otp_secret"]
    valid_code = pyotp.TOTP(otp_secret).now()
    invalid_code = f"{(int(valid_code) + 1) % 1000000:06d}"

    login_res = client.post(
        "/login",
        json={
            "username": "otp_user",
            "password": "Password123",
            "otp_code": invalid_code,
        },
    )
    assert login_res.status_code == 401


def test_message_send_pending_delivery_and_status(client: TestClient):
    token_alice = register_and_login(client, "alice", "Password123")
    token_bob = register_and_login(client, "bob", "Password123")
    make_friends(client, token_alice, token_bob, "bob")

    send_res = client.post(
        "/messages/send",
        headers=_auth(token_alice),
        json={
            "receiver_username": "bob",
            "ciphertext": {
                "ciphertext": "abc",
                "iv": "xyz",
                "metadata": {"sender": "alice", "receiver": "bob", "counter": 1},
            },
        },
    )
    assert send_res.status_code == 200
    message_id = send_res.json()["message_id"]
    assert send_res.json()["status"] == "sent"

    conv_bob = client.get("/friends/conversations", headers=_auth(token_bob))
    assert conv_bob.status_code == 200
    assert conv_bob.json()["conversations"][0]["unread_count"] == 1

    pending_res = client.get("/messages/inbox/pending", headers=_auth(token_bob))
    assert pending_res.status_code == 200
    assert pending_res.json()["total"] == 1
    assert pending_res.json()["messages"][0]["status"] == "delivered"

    status_res = client.get(f"/messages/status/{message_id}", headers=_auth(token_alice))
    assert status_res.status_code == 200
    assert status_res.json()["status"] == "delivered"


def test_non_friend_cannot_send(client: TestClient):
    token_alice = register_and_login(client, "alice2", "Password123")
    register_and_login(client, "bob2", "Password123")

    send_res = client.post(
        "/messages/send",
        headers=_auth(token_alice),
        json={
            "receiver_username": "bob2",
            "ciphertext": {
                "ciphertext": "abc",
                "iv": "xyz",
                "metadata": {"sender": "alice2", "receiver": "bob2", "counter": 1},
            },
        },
    )
    assert send_res.status_code == 403


def test_blocked_user_cannot_send(client: TestClient):
    token_alice = register_and_login(client, "alice3", "Password123")
    token_bob = register_and_login(client, "bob3", "Password123")
    make_friends(client, token_alice, token_bob, "bob3")

    block_res = client.post(
        "/friends/block",
        headers=_auth(token_bob),
        json={"username": "alice3"},
    )
    assert block_res.status_code == 200

    send_res = client.post(
        "/messages/send",
        headers=_auth(token_alice),
        json={
            "receiver_username": "bob3",
            "ciphertext": {
                "ciphertext": "abc",
                "iv": "xyz",
                "metadata": {"sender": "alice3", "receiver": "bob3", "counter": 1},
            },
        },
    )
    assert send_res.status_code == 403


def test_read_marks_unread_zero(client: TestClient):
    token_alice = register_and_login(client, "alice4", "Password123")
    token_bob = register_and_login(client, "bob4", "Password123")
    make_friends(client, token_alice, token_bob, "bob4")

    for idx in range(2):
        send_res = client.post(
            "/messages/send",
            headers=_auth(token_alice),
            json={
                "receiver_username": "bob4",
                "ciphertext": {
                    "ciphertext": "abc",
                    "iv": "xyz",
                    "metadata": {"sender": "alice4", "receiver": "bob4", "counter": idx + 1},
                },
            },
        )
        assert send_res.status_code == 200

    before = client.get("/friends/conversations", headers=_auth(token_bob))
    assert before.status_code == 200
    assert before.json()["conversations"][0]["unread_count"] == 2

    read_res = client.post("/messages/read/alice4", headers=_auth(token_bob))
    assert read_res.status_code == 200
    assert read_res.json()["marked_read"] == 2

    after = client.get("/friends/conversations", headers=_auth(token_bob))
    assert after.status_code == 200
    assert after.json()["conversations"][0]["unread_count"] == 0


def test_self_destruct_cleanup(client: TestClient):
    token_alice = register_and_login(client, "alice5", "Password123")
    token_bob = register_and_login(client, "bob5", "Password123")
    make_friends(client, token_alice, token_bob, "bob5")

    send_res = client.post(
        "/messages/send",
        headers=_auth(token_alice),
        json={
            "receiver_username": "bob5",
            "ciphertext": {
                "ciphertext": "abc",
                "iv": "xyz",
                "metadata": {"sender": "alice5", "receiver": "bob5", "counter": 1},
            },
            "ttl_seconds": 1,
        },
    )
    assert send_res.status_code == 200

    time.sleep(2)
    cleanup_res = client.post("/messages/cleanup", headers=_auth(token_alice))
    assert cleanup_res.status_code == 200
    assert cleanup_res.json()["expired_messages"] >= 1

    conv_res = client.get("/messages/conversation/alice5", headers=_auth(token_bob))
    assert conv_res.status_code == 200
    assert conv_res.json()["total"] == 0
