const state = {
  token: localStorage.getItem("token") || "",
  currentUser: localStorage.getItem("username") || "",
};

const el = {
  authSection: document.getElementById("auth-section"),
  dashboard: document.getElementById("dashboard"),
  systemOutput: document.getElementById("system-output"),
  registerOutput: document.getElementById("register-output"),
  sessionUser: document.getElementById("session-user"),
  canMessageResult: document.getElementById("can-message-result"),
  incomingRequests: document.getElementById("incoming-requests"),
  outgoingRequests: document.getElementById("outgoing-requests"),
  friendsList: document.getElementById("friends-list"),
  blockedList: document.getElementById("blocked-list"),
  conversationsList: document.getElementById("conversations-list"),
  // e2ee elements
  keyStatus: document.getElementById("key-status"),
  myFingerprint: document.getElementById("my-fingerprint"),
  contactFingerprintResult: document.getElementById("contact-fingerprint-result"),
  encryptOutput: document.getElementById("encrypt-output"),
  decryptOutput: document.getElementById("decrypt-output"),
};

function setSystemMessage(message, data) {
  const ts = new Date().toLocaleTimeString();
  const suffix = data ? `\n${JSON.stringify(data, null, 2)}` : "";
  el.systemOutput.textContent = `[${ts}] ${message}${suffix}`;
}

function authHeaders() {
  return state.token ? { Authorization: `Bearer ${state.token}` } : {};
}

async function api(path, options = {}) {
  const opts = {
    method: options.method || "GET",
    headers: {
      ...(options.json ? { "Content-Type": "application/json" } : {}),
      ...authHeaders(),
      ...(options.headers || {}),
    },
    body: options.json ? JSON.stringify(options.json) : undefined,
  };

  const res = await fetch(path, opts);
  const text = await res.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = text;
  }

  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    if (payload && payload.detail) {
      if (typeof payload.detail === "string") {
        msg = payload.detail;
      } else if (Array.isArray(payload.detail)) {
        // pydantic validation errors come as an array
        msg = payload.detail.map((e) => e.msg || JSON.stringify(e)).join("; ");
      }
    }
    throw new Error(msg);
  }
  return payload;
}

function renderAuthState() {
  const loggedIn = Boolean(state.token);
  el.authSection.classList.toggle("hidden", loggedIn);
  el.dashboard.classList.toggle("hidden", !loggedIn);
  el.sessionUser.textContent = loggedIn
    ? `Logged in as ${state.currentUser}`
    : "Not logged in";
}

function actionButton(label, onClick, className = "") {
  const btn = document.createElement("button");
  btn.textContent = label;
  if (className) btn.className = className;
  btn.addEventListener("click", onClick);
  return btn;
}

function emptyList(container, message) {
  container.innerHTML = "";
  const li = document.createElement("li");
  li.className = "muted";
  li.textContent = message;
  container.appendChild(li);
}

// ============ E2EE integration ============

// generate or load identity keypair, upload public key to server
async function initE2EE() {
  if (!state.token || !state.currentUser) return;

  let keyData = E2EE.loadKeypairLocally(state.currentUser);

  if (!keyData) {
    // first time — generate a fresh keypair
    setSystemMessage("Generating identity keypair...");
    const keyPair = await E2EE.generateIdentityKeypair();
    const pubB64 = await E2EE.exportPublicKey(keyPair.publicKey);
    const privJwk = await E2EE.exportPrivateKey(keyPair.privateKey);
    E2EE.saveKeypairLocally(state.currentUser, pubB64, privJwk);
    keyData = { publicKey: pubB64, privateKey: privJwk };
    setSystemMessage("Identity keypair generated and saved locally");
  }

  // upload public key to the server
  try {
    const result = await api("/keys/upload", {
      method: "POST",
      json: { public_key: keyData.publicKey },
    });
    if (el.keyStatus) {
      el.keyStatus.textContent = "Identity key active";
      el.keyStatus.className = "key-status-ok";
    }
    if (result.key_changed) {
      setSystemMessage("Warning: your identity key was updated on the server");
    }
  } catch (err) {
    if (el.keyStatus) {
      el.keyStatus.textContent = "Key upload failed";
      el.keyStatus.className = "key-status-err";
    }
    setSystemMessage(`Key upload failed: ${err.message}`);
  }

  // show own fingerprint
  if (el.myFingerprint) {
    const fp = await E2EE.computeFingerprint(keyData.publicKey);
    el.myFingerprint.textContent = fp;
  }
}

// fetch a contact's key and check for changes
async function fetchContactKey(contactUsername) {
  const result = await api(`/keys/${encodeURIComponent(contactUsername)}`);
  const keyChanged = E2EE.saveContactKey(state.currentUser, contactUsername, result.public_key);

  if (keyChanged || result.key_changed) {
    return { ...result, warning: true };
  }
  return { ...result, warning: false };
}

// ============ friends list (with fingerprint + verify) ============

async function refreshFriends() {
  try {
    const data = await api("/friends/list");
    el.friendsList.innerHTML = "";
    if (!data.friends.length) return emptyList(el.friendsList, "No friends yet");

    for (const friend of data.friends) {
      const li = document.createElement("li");
      li.className = "friend-item";

      const nameSpan = document.createElement("span");
      nameSpan.className = "friend-name";
      nameSpan.textContent = friend.username;
      li.appendChild(nameSpan);

      // check verification status from local storage
      const contactData = E2EE.loadContactKey(state.currentUser, friend.username);
      if (contactData && contactData.verified) {
        const verifiedBadge = document.createElement("span");
        verifiedBadge.className = "verified-badge";
        verifiedBadge.textContent = "Verified";
        li.appendChild(verifiedBadge);
      }

      const controls = document.createElement("div");
      controls.className = "row";

      controls.append(
        actionButton("Fingerprint", async () => {
          try {
            const keyInfo = await fetchContactKey(friend.username);
            const fp = await E2EE.computeFingerprint(keyInfo.public_key);
            let msg = `${friend.username}'s fingerprint:\n${fp}`;
            if (keyInfo.warning) {
              msg = `WARNING: ${friend.username}'s identity key has CHANGED!\n` +
                    `This could mean they reinstalled or someone is intercepting.\n\n` + msg;
            }
            const localData = E2EE.loadContactKey(state.currentUser, friend.username);
            if (localData && localData.verified) {
              msg += "\n\nStatus: Verified";
            } else {
              msg += "\n\nStatus: Not verified";
            }
            setSystemMessage(msg);
          } catch (err) {
            setSystemMessage(`Could not get fingerprint: ${err.message}`);
          }
        }),
        actionButton("Verify", async () => {
          try {
            // fetch key first to make sure we have it
            await fetchContactKey(friend.username);
            E2EE.markContactVerified(state.currentUser, friend.username);
            setSystemMessage(`Marked ${friend.username} as verified`);
            await refreshFriends(); // re-render to show badge
          } catch (err) {
            setSystemMessage(`Verify failed: ${err.message}`);
          }
        }),
        actionButton("Remove", async () => {
          await api(`/friends/remove/${encodeURIComponent(friend.username)}`, { method: "DELETE" });
          setSystemMessage("Friend removed");
          await refreshAll();
        }, "danger"),
        actionButton("Block", async () => {
          await api("/friends/block", { method: "POST", json: { username: friend.username } });
          setSystemMessage(`Blocked ${friend.username}`);
          await refreshAll();
        }, "danger")
      );

      li.appendChild(controls);
      el.friendsList.appendChild(li);
    }
  } catch (err) {
    setSystemMessage(`Friends refresh failed: ${err.message}`);
  }
}

// ============ encryption demo section ============

async function handleEncryptDemo() {
  const contactInput = document.getElementById("encrypt-contact");
  const messageInput = document.getElementById("encrypt-message");
  if (!contactInput || !messageInput) return;

  const contact = contactInput.value.trim();
  const plaintext = messageInput.value.trim();
  if (!contact || !plaintext) {
    setSystemMessage("Enter both a contact username and message");
    return;
  }

  try {
    // load our private key
    const keyData = E2EE.loadKeypairLocally(state.currentUser);
    if (!keyData) {
      setSystemMessage("No local keypair found — please log in again");
      return;
    }
    const myPrivKey = await E2EE.importPrivateKey(keyData.privateKey);

    // fetch contact's public key
    const contactKeyInfo = await fetchContactKey(contact);

    if (contactKeyInfo.warning) {
      setSystemMessage(
        `WARNING: ${contact}'s key has changed! Verify before trusting this session.`
      );
    }

    // derive shared session key
    const context = E2EE.buildContext(state.currentUser, contact);
    const sessionKey = await E2EE.deriveSessionKey(
      myPrivKey,
      contactKeyInfo.public_key,
      context
    );

    // build metadata for AAD binding
    const counter = E2EE.getNextSendCounter(state.currentUser, contact);
    const metadata = {
      sender: state.currentUser,
      receiver: contact,
      counter: counter,
      timestamp: Date.now(),
    };

    // encrypt
    const encrypted = await E2EE.encryptMessage(sessionKey, plaintext, metadata);

    if (el.encryptOutput) {
      el.encryptOutput.textContent = JSON.stringify(encrypted, null, 2);
    }
    setSystemMessage(`Message encrypted (counter=${counter})`);
  } catch (err) {
    setSystemMessage(`Encryption failed: ${err.message}`);
  }
}

async function handleDecryptDemo() {
  const ciphertextInput = document.getElementById("decrypt-ciphertext");
  if (!ciphertextInput) return;

  const raw = ciphertextInput.value.trim();
  if (!raw) {
    setSystemMessage("Paste encrypted message JSON to decrypt");
    return;
  }

  let encrypted;
  try {
    encrypted = JSON.parse(raw);
  } catch {
    setSystemMessage("Invalid JSON — paste the full encrypted message object");
    return;
  }

  try {
    const sender = encrypted.metadata?.sender;
    if (!sender) {
      setSystemMessage("Encrypted message is missing sender in metadata");
      return;
    }

    // replay check
    const counter = encrypted.metadata?.counter;
    if (counter !== undefined) {
      const ok = E2EE.checkReplayAndUpdate(state.currentUser, sender, counter);
      if (!ok) {
        setSystemMessage(`REJECTED: replay or duplicate detected (counter=${counter})`);
        if (el.decryptOutput) {
          el.decryptOutput.textContent = "REJECTED — replayed message";
        }
        return;
      }
    }

    // load our private key
    const keyData = E2EE.loadKeypairLocally(state.currentUser);
    if (!keyData) {
      setSystemMessage("No local keypair found");
      return;
    }
    const myPrivKey = await E2EE.importPrivateKey(keyData.privateKey);

    // fetch sender's public key
    const senderKeyInfo = await fetchContactKey(sender);

    if (senderKeyInfo.warning) {
      setSystemMessage(`WARNING: ${sender}'s key has changed since last time!`);
    }

    // derive session key (same ECDH shared secret)
    const context = E2EE.buildContext(state.currentUser, sender);
    const sessionKey = await E2EE.deriveSessionKey(
      myPrivKey,
      senderKeyInfo.public_key,
      context
    );

    // decrypt
    const plaintext = await E2EE.decryptMessage(sessionKey, encrypted);

    if (el.decryptOutput) {
      el.decryptOutput.textContent = plaintext;
    }
    setSystemMessage(`Message decrypted successfully (counter=${counter})`);
  } catch (err) {
    setSystemMessage(`Decryption failed: ${err.message}`);
    if (el.decryptOutput) {
      el.decryptOutput.textContent = "Decryption failed — wrong key or tampered data";
    }
  }
}

// ============ other refresh functions (unchanged logic) ============

async function refreshIncoming() {
  try {
    const data = await api("/friends/requests/incoming");
    el.incomingRequests.innerHTML = "";
    if (!data.length) return emptyList(el.incomingRequests, "No incoming requests");

    data.forEach((req) => {
      const li = document.createElement("li");
      li.append(`${req.from_username || req.from_user_id}`);

      const controls = document.createElement("div");
      controls.className = "row";
      controls.append(
        actionButton("Accept", async () => {
          await api("/friends/request/accept", { method: "POST", json: { request_id: req.id } });
          setSystemMessage("Friend request accepted");
          await refreshAll();
        }),
        actionButton("Decline", async () => {
          await api("/friends/request/decline", { method: "POST", json: { request_id: req.id } });
          setSystemMessage("Friend request declined");
          await refreshAll();
        }, "danger")
      );

      li.appendChild(controls);
      el.incomingRequests.appendChild(li);
    });
  } catch (err) {
    setSystemMessage(`Incoming requests failed: ${err.message}`);
  }
}

async function refreshOutgoing() {
  try {
    const data = await api("/friends/requests/outgoing");
    el.outgoingRequests.innerHTML = "";
    if (!data.length) return emptyList(el.outgoingRequests, "No outgoing requests");

    data.forEach((req) => {
      const li = document.createElement("li");
      li.append(`${req.to_username || req.to_user_id}`);
      li.appendChild(
        actionButton("Cancel", async () => {
          await api("/friends/request/cancel", { method: "POST", json: { request_id: req.id } });
          setSystemMessage("Friend request cancelled");
          await refreshAll();
        }, "danger")
      );
      el.outgoingRequests.appendChild(li);
    });
  } catch (err) {
    setSystemMessage(`Outgoing requests failed: ${err.message}`);
  }
}

async function refreshBlocked() {
  try {
    const data = await api("/friends/blocked");
    el.blockedList.innerHTML = "";
    if (!data.length) return emptyList(el.blockedList, "No blocked users");

    data.forEach((block) => {
      const li = document.createElement("li");
      li.append(block.blocked_username);
      li.appendChild(
        actionButton("Unblock", async () => {
          await api(`/friends/unblock/${encodeURIComponent(block.blocked_username)}`, { method: "DELETE" });
          setSystemMessage(`Unblocked ${block.blocked_username}`);
          await refreshAll();
        })
      );
      el.blockedList.appendChild(li);
    });
  } catch (err) {
    setSystemMessage(`Blocked refresh failed: ${err.message}`);
  }
}

async function refreshConversations() {
  try {
    const data = await api("/friends/conversations?page=1&page_size=20");
    el.conversationsList.innerHTML = "";
    if (!data.conversations.length) return emptyList(el.conversationsList, "No conversations yet");

    data.conversations.forEach((conv) => {
      const li = document.createElement("li");
      li.append(`${conv.other_username}`);
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = `Unread: ${conv.unread_count}`;
      li.appendChild(badge);
      el.conversationsList.appendChild(li);
    });
  } catch (err) {
    setSystemMessage(`Conversation refresh failed: ${err.message}`);
  }
}

async function refreshAll() {
  if (!state.token) return;
  await Promise.all([
    refreshIncoming(),
    refreshOutgoing(),
    refreshFriends(),
    refreshBlocked(),
    refreshConversations(),
  ]);
}

// ============ event listeners ============

document.getElementById("register-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const payload = await api("/register", {
      method: "POST",
      json: {
        username: document.getElementById("register-username").value.trim(),
        email: document.getElementById("register-email").value.trim() || null,
        password: document.getElementById("register-password").value,
      },
    });
    el.registerOutput.textContent = JSON.stringify({
      otp_secret: payload.otp_secret,
      otp_uri: payload.otp_uri,
    }, null, 2);
    setSystemMessage(`Registered ${payload.username}. Save OTP secret now.`);
  } catch (err) {
    setSystemMessage(`Register failed: ${err.message}`);
  }
});

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = document.getElementById("login-username").value.trim();
  try {
    const payload = await api("/login", {
      method: "POST",
      json: {
        username,
        password: document.getElementById("login-password").value,
        otp_code: document.getElementById("login-otp").value.trim(),
      },
    });
    state.token = payload.token;
    state.currentUser = username;
    localStorage.setItem("token", state.token);
    localStorage.setItem("username", username);
    renderAuthState();
    setSystemMessage(`Logged in as ${username}`);
    await initE2EE();
    await refreshAll();
  } catch (err) {
    setSystemMessage(`Login failed: ${err.message}`);
  }
});

document.getElementById("logout-btn").addEventListener("click", async () => {
  try {
    if (state.token) {
      await api("/logout", { method: "POST", json: { token: state.token }, headers: {} });
    }
  } catch (err) {
    setSystemMessage(`Logout warning: ${err.message}`);
  } finally {
    state.token = "";
    state.currentUser = "";
    localStorage.removeItem("token");
    localStorage.removeItem("username");
    renderAuthState();
    setSystemMessage("Logged out");
  }
});

document.getElementById("send-request-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const username = document.getElementById("friend-username").value.trim();
    await api("/friends/request/send", { method: "POST", json: { username } });
    setSystemMessage(`Sent friend request to ${username}`);
    document.getElementById("friend-username").value = "";
    await refreshAll();
  } catch (err) {
    setSystemMessage(`Send request failed: ${err.message}`);
  }
});

document.getElementById("can-message-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const username = document.getElementById("can-message-username").value.trim();
    const result = await api(`/friends/can-message/${encodeURIComponent(username)}`);
    el.canMessageResult.textContent = result.allowed
      ? "Messaging allowed"
      : `Not allowed: ${result.reason || "Unknown reason"}`;
  } catch (err) {
    el.canMessageResult.textContent = `Check failed: ${err.message}`;
  }
});

// fingerprint lookup
const fpForm = document.getElementById("fingerprint-form");
if (fpForm) {
  fpForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = document.getElementById("fingerprint-username").value.trim();
    if (!username) return;
    try {
      const keyInfo = await fetchContactKey(username);
      const fp = await E2EE.computeFingerprint(keyInfo.public_key);
      let result = `${fp}`;
      if (keyInfo.warning) {
        result = `KEY CHANGED!\n${result}`;
      }
      const localData = E2EE.loadContactKey(state.currentUser, username);
      if (localData && localData.verified) {
        result += "\nVerified";
      }
      if (el.contactFingerprintResult) {
        el.contactFingerprintResult.textContent = result;
        el.contactFingerprintResult.className = keyInfo.warning
          ? "output key-warning"
          : "output";
      }
    } catch (err) {
      if (el.contactFingerprintResult) {
        el.contactFingerprintResult.textContent = `Error: ${err.message}`;
      }
    }
  });
}

// encrypt button
const encryptBtn = document.getElementById("encrypt-btn");
if (encryptBtn) {
  encryptBtn.addEventListener("click", handleEncryptDemo);
}

// decrypt button
const decryptBtn = document.getElementById("decrypt-btn");
if (decryptBtn) {
  decryptBtn.addEventListener("click", handleDecryptDemo);
}

document.getElementById("refresh-conversations").addEventListener("click", refreshConversations);

// ============ init ============

renderAuthState();
if (state.token) {
  initE2EE()
    .then(() => refreshAll())
    .catch((err) => setSystemMessage(`Init failed: ${err.message}`));
}
