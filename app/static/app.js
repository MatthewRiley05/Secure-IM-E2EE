const state = {
  token: localStorage.getItem("token") || "",
  currentUser: localStorage.getItem("username") || "",
  activeChatUser: "",
  activeChatPage: 1,
  activeChatMessages: [],
};

let inboxPollTimer = null;

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
  chatOpenForm: document.getElementById("chat-open-form"),
  chatCloseBtn: document.getElementById("chat-close-btn"),
  chatUsername: document.getElementById("chat-username"),
  chatTtl: document.getElementById("chat-ttl"),
  chatMessage: document.getElementById("chat-message"),
  chatSendBtn: document.getElementById("chat-send-btn"),
  chatLoadMore: document.getElementById("chat-load-more"),
  chatCurrent: document.getElementById("chat-current"),
  chatMessages: document.getElementById("chat-messages"),
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

async function encryptForContact(contact, plaintext) {
  const keyData = E2EE.loadKeypairLocally(state.currentUser);
  if (!keyData) {
    throw new Error("No local keypair found — please log in again");
  }
  const myPrivKey = await E2EE.importPrivateKey(keyData.privateKey);
  const contactKeyInfo = await fetchContactKey(contact);

  const context = E2EE.buildContext(state.currentUser, contact);
  const sessionKey = await E2EE.deriveSessionKey(
    myPrivKey,
    contactKeyInfo.public_key,
    context
  );

  const counter = E2EE.getNextSendCounter(state.currentUser, contact);
  const metadata = {
    sender: state.currentUser,
    receiver: contact,
    counter: counter,
    timestamp: Date.now(),
  };

  const encrypted = await E2EE.encryptMessage(sessionKey, plaintext, metadata);
  return { encrypted, counter, warning: contactKeyInfo.warning };
}

async function decryptForView(message, keyCache) {
  try {
    const keyData = E2EE.loadKeypairLocally(state.currentUser);
    if (!keyData) return "[No local private key]";

    const myPrivKey = await E2EE.importPrivateKey(keyData.privateKey);
    const other = message.sender_username === state.currentUser
      ? message.receiver_username
      : message.sender_username;

    if (!keyCache[other]) {
      const localContact = E2EE.loadContactKey(state.currentUser, other);
      if (localContact && localContact.publicKey) {
        keyCache[other] = {
          public_key: localContact.publicKey,
          warning: false,
          key_changed: false,
        };
      } else {
        keyCache[other] = await fetchContactKey(other);
      }
    }

    const context = E2EE.buildContext(state.currentUser, other);
    const sessionKey = await E2EE.deriveSessionKey(
      myPrivKey,
      keyCache[other].public_key,
      context
    );

    return await E2EE.decryptMessage(sessionKey, message.ciphertext);
  } catch {
    return "[Unable to decrypt message]";
  }
}

function formatMessageTime(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString();
}

function messageDigest(msg) {
  return `${msg.id}|${msg.status}|${msg.delivered_at || ""}|${msg.read_at || ""}`;
}

function messagesChanged(prev, next) {
  if (prev.length !== next.length) return true;
  for (let i = 0; i < next.length; i += 1) {
    if (messageDigest(prev[i]) !== messageDigest(next[i])) return true;
  }
  return false;
}

async function copyText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "true");
  ta.style.position = "absolute";
  ta.style.left = "-9999px";
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  document.body.removeChild(ta);
}

async function copyDisplayedMessageText(plaintext) {
  await copyText(plaintext);
  setSystemMessage("Message text copied to clipboard");
}

async function removeMessageFromActiveView(messageId) {
  state.activeChatMessages = state.activeChatMessages.filter((m) => m.id !== messageId);
  await renderChatMessages(state.activeChatMessages);
  setSystemMessage(`Removed message ${messageId} from current chat view`);
}

function closeActiveChat() {
  state.activeChatUser = "";
  state.activeChatPage = 1;
  state.activeChatMessages = [];
  if (el.chatCurrent) {
    el.chatCurrent.textContent = "No conversation selected";
  }
  if (el.chatMessages) {
    el.chatMessages.innerHTML = "";
  }
}

async function renderChatMessages(messages) {
  if (!el.chatMessages) return;
  el.chatMessages.innerHTML = "";

  if (!messages.length) {
    emptyList(el.chatMessages, "No messages yet");
    return;
  }

  const keyCache = {};
  for (const msg of messages) {
    const li = document.createElement("li");
    const plaintext = await decryptForView(msg, keyCache);

    const fromMe = msg.sender_username === state.currentUser;
    const senderLabel = fromMe ? "You" : msg.sender_username;
    const body = document.createElement("div");
    body.className = "stack message-content";

    const text = document.createElement("span");
    text.textContent = `${senderLabel}: ${plaintext}`;
    body.appendChild(text);

    const meta = document.createElement("span");
    meta.className = "muted";
    const statusPart = fromMe ? ` (${msg.status})` : "";
    meta.textContent = `${formatMessageTime(msg.created_at)}${statusPart}`;
    body.appendChild(meta);

    const controls = document.createElement("div");
    controls.className = "row end";
    controls.append(
      actionButton("Copy", async () => {
        try {
          await copyDisplayedMessageText(plaintext);
        } catch (err) {
          setSystemMessage(`Copy failed: ${err.message}`);
        }
      }, "mini"),
      actionButton("Delete", async () => {
        await removeMessageFromActiveView(msg.id);
      }, "mini danger")
    );

    li.appendChild(body);
    li.appendChild(controls);
    el.chatMessages.appendChild(li);
  }
}

async function loadActiveConversation(reset = true, markRead = true) {
  if (!state.activeChatUser) return;
  if (!el.chatCurrent) return;
  const previousMessages = state.activeChatMessages;

  if (reset) {
    state.activeChatPage = 1;
  }

  const data = await api(
    `/messages/conversation/${encodeURIComponent(state.activeChatUser)}?page=${state.activeChatPage}&page_size=20`
  );

  if (!data.messages.length && !reset) {
    setSystemMessage("No older messages");
    return;
  }

  const nextMessages = reset
    ? data.messages
    : [...data.messages, ...previousMessages];
  const shouldRender = messagesChanged(previousMessages, nextMessages);
  state.activeChatMessages = nextMessages;

  if (shouldRender) {
    await renderChatMessages(state.activeChatMessages);
  }
  if (markRead) {
    try {
      await api(`/messages/read/${encodeURIComponent(state.activeChatUser)}`, { method: "POST" });
      await refreshConversations();
    } catch {
      // ignore read-mark errors in UI
    }
  }
}

async function sendChatMessage() {
  if (!state.activeChatUser) {
    setSystemMessage("Open a conversation first");
    return;
  }
  if (!el.chatMessage) return;

  const plaintext = el.chatMessage.value.trim();
  if (!plaintext) {
    setSystemMessage("Type a message first");
    return;
  }

  let ttlSeconds = null;
  if (el.chatTtl && el.chatTtl.value.trim()) {
    const parsed = Number(el.chatTtl.value.trim());
    if (!Number.isInteger(parsed) || parsed < 1 || parsed > 604800) {
      setSystemMessage("TTL must be an integer between 1 and 604800");
      return;
    }
    ttlSeconds = parsed;
  }

  const { encrypted, warning } = await encryptForContact(state.activeChatUser, plaintext);
  if (warning) {
    setSystemMessage(`WARNING: ${state.activeChatUser}'s key has changed`);
  }

  await api("/messages/send", {
    method: "POST",
    json: {
      receiver_username: state.activeChatUser,
      ciphertext: encrypted,
      ttl_seconds: ttlSeconds,
    },
  });

  el.chatMessage.value = "";
  await loadActiveConversation(true);
  await refreshConversations();
}

async function pollPendingMessages() {
  if (!state.token) return;
  try {
    const result = await api("/messages/inbox/pending?limit=50");
    const hasNewPending = result.total > 0;
    if (hasNewPending) {
      setSystemMessage(`Received ${result.total} pending message(s)`);
    }

    if (state.activeChatUser) {
      await loadActiveConversation(true, false);
    } else if (hasNewPending) {
      await refreshConversations();
    }
  } catch {
    // silent background polling
  }
}

function startInboxPolling() {
  if (inboxPollTimer) {
    clearInterval(inboxPollTimer);
  }
  inboxPollTimer = setInterval(() => {
    pollPendingMessages();
  }, 5000);
}

function stopInboxPolling() {
  if (inboxPollTimer) {
    clearInterval(inboxPollTimer);
    inboxPollTimer = null;
  }
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

            if (el.contactFingerprintResult) {
              el.contactFingerprintResult.textContent = msg;
              el.contactFingerprintResult.className = keyInfo.warning
                ? "output key-warning"
                : "output";
            }

            setSystemMessage(msg);
          } catch (err) {
            setSystemMessage(`Could not get fingerprint: ${err.message}`);
            if (el.contactFingerprintResult) {
              el.contactFingerprintResult.textContent = `Error: ${err.message}`;
              el.contactFingerprintResult.className = "output key-warning";
            }
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
    const result = await encryptForContact(contact, plaintext);
    if (result.warning) {
      setSystemMessage(
        `WARNING: ${contact}'s key has changed! Verify before trusting this session.`
      );
    }

    if (el.encryptOutput) {
      el.encryptOutput.textContent = JSON.stringify(result.encrypted, null, 2);
    }
    setSystemMessage(`Message encrypted (counter=${result.counter})`);
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
      const name = document.createElement("span");
      name.textContent = `${conv.other_username} - Last activity: ${formatMessageTime(conv.updated_at) || "Unknown"}`;
      li.appendChild(name);

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
    state.activeChatUser = "";
    state.activeChatPage = 1;
    state.activeChatMessages = [];
    localStorage.setItem("token", state.token);
    localStorage.setItem("username", username);
    renderAuthState();
    setSystemMessage(`Logged in as ${username}`);
    await initE2EE();
    startInboxPolling();
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
    closeActiveChat();
    localStorage.removeItem("token");
    localStorage.removeItem("username");
    stopInboxPolling();
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

if (el.chatCloseBtn) {
  el.chatCloseBtn.addEventListener("click", () => {
    closeActiveChat();
    setSystemMessage("Closed active chat");
  });
}

if (el.chatOpenForm) {
  el.chatOpenForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!el.chatUsername) return;
    const username = el.chatUsername.value.trim();
    if (!username) return;
    state.activeChatUser = username;
    state.activeChatPage = 1;
    if (el.chatCurrent) {
      el.chatCurrent.textContent = `Conversation with ${username}`;
    }
    try {
      await loadActiveConversation(true);
    } catch (err) {
      setSystemMessage(`Open conversation failed: ${err.message}`);
    }
  });
}

if (el.chatSendBtn) {
  el.chatSendBtn.addEventListener("click", async () => {
    try {
      await sendChatMessage();
    } catch (err) {
      setSystemMessage(`Send message failed: ${err.message}`);
    }
  });
}

if (el.chatLoadMore) {
  el.chatLoadMore.addEventListener("click", async () => {
    if (!state.activeChatUser) {
      setSystemMessage("Open a conversation first");
      return;
    }
    state.activeChatPage += 1;
    try {
      await loadActiveConversation(false);
    } catch (err) {
      setSystemMessage(`Load more failed: ${err.message}`);
    }
  });
}

document.getElementById("refresh-conversations").addEventListener("click", async () => {
  await refreshConversations();
  if (state.activeChatUser) {
    try {
      await loadActiveConversation(true, false);
    } catch (err) {
      setSystemMessage(`Active chat refresh failed: ${err.message}`);
    }
  }
});

// ============ init ============

renderAuthState();
if (state.token) {
  initE2EE()
    .then(() => {
      startInboxPolling();
      return refreshAll();
    })
    .catch((err) => setSystemMessage(`Init failed: ${err.message}`));
}
