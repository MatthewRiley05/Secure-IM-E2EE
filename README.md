# Secure-IM-E2EE

Secure IM is a FastAPI-based secure messaging demo that combines:
- account auth with password + TOTP
- friends/blocking + conversation list
- browser-side end-to-end encryption (ECDH + HKDF + AES-GCM)
- server-side ciphertext relay/storage for offline delivery

## Features

- User registration and login with OTP
- Session token auth and session expiry cleanup
- Friend requests, blocking, anti-spam friend-only messaging rule
- Identity public key upload/distribution and fingerprint verification
- 1:1 encrypted messaging flow
- Offline message queue (`sent` -> `delivered` on recipient fetch)
- Conversation unread counters
- Optional self-destruct TTL for messages
- Expiry cleanup for self-destructed messages

## Tech Stack

- Backend: FastAPI + SQLAlchemy
- Database: SQLite (`im_server.db`)
- Frontend: static HTML/CSS/JS
- Client crypto: Web Crypto API (ECDH P-256, AES-256-GCM, HKDF)
- Transport Security: Nginx reverse proxy with TLS/SSL (self-signed for dev, CA-signed for production)

## Security Architecture

### End-to-End Encryption (E2EE)
- **Key Agreement**: ECDH P-256 (client-side)
- **Key Derivation**: HKDF-SHA256
- **Message Encryption**: AES-256-GCM with authenticated associated data (AAD)
- **Replay Protection**: Counter-based with out-of-order tolerance (50-message window)
- **Private Keys**: Never leave client (stored in browser localStorage)
- **Server Role**: Ciphertext relay only (cannot decrypt messages)

### Transport Security (TLS/SSL)
- **Connection**: Client ↔ Nginx (TLS 1.2/1.3) ↔ FastAPI
- **Certificates**: Self-signed for development (provided), CA-signed for production
- **Headers**: HSTS, X-Frame-Options, X-Content-Type-Options, X-XSS-Protection
- **Cipher Suites**: HIGH:!aNULL:!MD5 (modern standards)

### Authentication
- **Password**: Bcrypt with per-user salt (passlib)
- **Session**: Secure random tokens with 1-hour expiry
- **Two-Factor**: TOTP (RFC 6238) via authenticator app
- **Rate Limiting**: 5 registrations/min, 10 logins/min, 10 friend requests/min per user

## Quick Start (Recommended for University Submission) ⭐

**Simplest setup - no Docker required!**

### Windows 11:
```cmd
setup.bat
run.bat
```

### macOS / Linux:
```bash
./setup.sh
./run.sh
```

**Then open**: https://localhost:8443/ui

✅ That's it! See [QUICKSTART.md](QUICKSTART.md) for detailed walkthrough.

---

## Alternative: Manual Setup for Development

1. Create and activate virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate      # Linux/macOS
# or
.\.venv\Scripts\Activate.ps1   # Windows PowerShell
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Generate certificates:

```bash
# Generate self-signed TLS certificate
openssl req -x509 -newkey rsa:4096 -nodes \
  -out certs/cert.pem -keyout certs/key.pem -days 365 \
  -subj "/C=US/ST=State/L=City/O=Secure-IM/CN=localhost"
```

4. Start server with TLS:

```bash
# Run on https://localhost:8443
uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8443 \
  --ssl-keyfile=certs/key.pem \
  --ssl-certfile=certs/cert.pem \
  --reload
```

5. Open:
- **Web UI**: https://localhost:8443/ui
- **API docs**: https://localhost:8443/docs
- **API root**: https://localhost:8443/

⚠️ **Note**: Server runs on HTTPS with self-signed certificate (browser will show warning - this is normal).

## Messaging API (Part 4)

- `POST /messages/send`
  - Sends encrypted payload to a friend.
  - Request includes optional `ttl_seconds` for self-destruct.
- `GET /messages/conversation/{username}?page=1&page_size=20`
  - Conversation history with pagination.
  - Marks fetched incoming messages as delivered/read.
- `GET /messages/inbox/pending?limit=50`
  - Fetches undelivered messages for current user.
  - Marks them as delivered.
- `POST /messages/read/{username}`
  - Marks unread messages in that conversation as read.
  - Resets unread counter.
- `GET /messages/status/{message_id}`
  - Returns message delivery/read status.
- `POST /messages/cleanup`
  - Triggers manual cleanup for expired self-destruct messages.

All messaging endpoints require header:

```text
Authorization: Bearer <token>
```

## Step-by-Step Usage Guide

1. Register user A and user B (`/register`).
2. Save each user's OTP secret in an authenticator app.
3. Login both users (`/login`) with current 6-digit OTP code.
4. Send friend request from A to B, accept from B.
5. Open `/ui` for A and B (different browsers/incognito recommended).
6. Open chat to friend username and send encrypted messages.
7. Test offline flow:
   - logout B (or close B tab)
   - send from A to B
   - login B again, pending messages are delivered on poll/fetch
8. Test self-destruct:
   - send with TTL (e.g. 10 seconds)
   - wait for expiry and refresh chat
   - expired message is removed by cleanup hooks

## Testing Workflow (Aligned with Project Requirements)

The project PDF asks for both functional demonstration and at least 2 security test cases. Use this workflow for development, demo prep, and report evidence.

### 1) Environment setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Run automated backend tests

```bash
python3 -m pytest tests/test_messages.py -q
```

Current test file covers:
- Core messaging flow (`sent` -> `delivered`, unread/read)
- Friend request lifecycle (send/accept/decline/cancel)
- Block/unblock behavior and friend visibility impact
- Conversation/pending retrieval behavior
- TTL self-destruct cleanup
- Key change detection visibility
- Security case: OTP invalid-code rejection
- Security case: blocked/non-friend message rejection

### 3) Manual UI demonstration flow (for report/video)

Use two browser sessions (normal + incognito) as two users.

1. Register and log in both users with password + OTP.
2. Upload identity keys automatically via UI; verify key state appears active.
3. Send friend request from user A; accept from user B.
4. Show fingerprint lookup + verify contact flow.
5. Send encrypted message A -> B and show:
   - conversation list ordering
   - unread counter increments and resets after read
   - delivery status transition (`sent` to `delivered`)
6. Test offline queue:
   - close/log out user B
   - send from A
   - log in B and show pending retrieval
7. Test self-destruct:
   - send with short TTL
   - wait for expiry
   - trigger cleanup and show message removed
8. Test block/anti-spam policy:
   - block contact and show messaging is denied
   - unblock and verify friend visibility restored

### 4) Suggested report mapping

- **Functional tests**: map each requirement (R1-R25) to endpoint/UI evidence.
- **Security tests (at least 2)**:
  - invalid OTP login rejected
  - blocked user or non-friend cannot send messages
  - optional extra: key-change warning shown (`key_changed=true`)

### 5) Optional quality checks

```bash
python3 -m compileall app scripts tests
node --check app/static/app.js
```

## Notes

- OTP secret (about 32 chars) is provisioning data, not login input.
- Login uses the current 6-digit TOTP code.
- Server stores ciphertext and metadata only; private keys stay in browser local storage.
- Open chat auto-refreshes during inbox polling so delivery/read status updates appear without reopening chat.
- Chat `Close` button clears only the active UI chat state.
- Message-row `Copy` copies exactly the text shown in that row.
- Message-row `Delete` is UI-only (removes from current view state, not server/database).

## Security Semantics

- Delivered semantics (Option B): `delivered` is set when the recipient client fetches via `/messages/inbox/pending` or `/messages/conversation/{username}`.
- Metadata disclosure: the server can observe sender/receiver identifiers, message timing, queue length, delivery/read timing, and ciphertext sizes; it cannot decrypt message plaintext.
- Replay/duplicate protection: server rejects duplicate `(sender, receiver, counter)` and client also performs local replay checks.
- TTL binding: `ttl_seconds` must match `ciphertext.metadata.ttl_seconds`; mismatches are rejected.

## TLS Deployment Requirement

Run the API behind HTTPS in deployment. One simple local example is reverse-proxying uvicorn with TLS termination.

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Example nginx TLS proxy snippet:

```nginx
server {
    listen 443 ssl;
    server_name your-domain.example;

    ssl_certificate /path/fullchain.pem;
    ssl_certificate_key /path/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```
