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
    const msg = payload && payload.detail ? payload.detail : `HTTP ${res.status}`;
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

async function refreshFriends() {
  try {
    const data = await api("/friends/list");
    el.friendsList.innerHTML = "";
    if (!data.friends.length) return emptyList(el.friendsList, "No friends yet");

    data.friends.forEach((friend) => {
      const li = document.createElement("li");
      li.append(friend.username);

      const controls = document.createElement("div");
      controls.className = "row";
      controls.append(
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
    });
  } catch (err) {
    setSystemMessage(`Friends refresh failed: ${err.message}`);
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

document.getElementById("refresh-conversations").addEventListener("click", refreshConversations);

renderAuthState();
if (state.token) {
  refreshAll().catch((err) => setSystemMessage(`Initial refresh failed: ${err.message}`));
}
