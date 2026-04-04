/*
 * e2ee.js — client-side end-to-end encryption module
 *
 * Uses Web Crypto API:
 *   - ECDH P-256 for key agreement
 *   - HKDF (SHA-256) for key derivation
 *   - AES-256-GCM for authenticated encryption
 *
 * The private key never leaves the client.
 * The server only stores the public key for distribution.
 */

const E2EE = (() => {

  // ---- helpers ----

  function arrayBufToBase64(buf) {
    const bytes = new Uint8Array(buf);
    let binary = "";
    for (let i = 0; i < bytes.length; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
  }

  function base64ToArrayBuf(b64) {
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes.buffer;
  }

  // format a sha-256 digest as spaced hex groups (for fingerprint display)
  function formatFingerprint(hashBuf) {
    const arr = new Uint8Array(hashBuf);
    let hex = "";
    arr.forEach((b) => {
      hex += b.toString(16).padStart(2, "0");
    });
    // group into blocks of 4
    const groups = [];
    for (let i = 0; i < hex.length; i += 4) {
      groups.push(hex.slice(i, i + 4));
    }
    return groups.join(" ");
  }

  // ---- key generation ----

  // generate a new ECDH P-256 identity keypair
  async function generateIdentityKeypair() {
    const keyPair = await crypto.subtle.generateKey(
      { name: "ECDH", namedCurve: "P-256" },
      true, // extractable so we can export/store
      ["deriveKey", "deriveBits"]
    );
    return keyPair;
  }

  // export public key as raw bytes -> base64
  async function exportPublicKey(publicKey) {
    const raw = await crypto.subtle.exportKey("raw", publicKey);
    return arrayBufToBase64(raw);
  }

  // export private key as JWK for localStorage storage
  async function exportPrivateKey(privateKey) {
    const jwk = await crypto.subtle.exportKey("jwk", privateKey);
    return jwk;
  }

  // import a raw (base64) public key back into a CryptoKey
  async function importPublicKey(b64) {
    const raw = base64ToArrayBuf(b64);
    return crypto.subtle.importKey(
      "raw",
      raw,
      { name: "ECDH", namedCurve: "P-256" },
      true,
      []
    );
  }

  // import a JWK private key from localStorage
  async function importPrivateKey(jwk) {
    return crypto.subtle.importKey(
      "jwk",
      jwk,
      { name: "ECDH", namedCurve: "P-256" },
      true,
      ["deriveKey", "deriveBits"]
    );
  }

  // ---- local key storage ----

  function saveKeypairLocally(username, publicKeyB64, privateKeyJwk) {
    const keyData = {
      publicKey: publicKeyB64,
      privateKey: privateKeyJwk,
      createdAt: new Date().toISOString(),
    };
    localStorage.setItem(`e2ee_keypair_${username}`, JSON.stringify(keyData));
  }

  function loadKeypairLocally(username) {
    const raw = localStorage.getItem(`e2ee_keypair_${username}`);
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  // store known public keys for contacts so we can detect changes
  function saveContactKey(myUsername, contactUsername, publicKeyB64) {
    const storageKey = `e2ee_contact_${myUsername}_${contactUsername}`;
    const existing = localStorage.getItem(storageKey);
    const record = {
      publicKey: publicKeyB64,
      verified: false,
      savedAt: new Date().toISOString(),
    };

    let keyChanged = false;
    if (existing) {
      try {
        const old = JSON.parse(existing);
        if (old.publicKey !== publicKeyB64) {
          keyChanged = true;
          record.previousKey = old.publicKey;
          // keep verified status only if key hasn't changed
          record.verified = false;
        } else {
          record.verified = old.verified || false;
        }
      } catch {
        // corrupted data, just overwrite
      }
    }

    localStorage.setItem(storageKey, JSON.stringify(record));
    return keyChanged;
  }

  function loadContactKey(myUsername, contactUsername) {
    const raw = localStorage.getItem(`e2ee_contact_${myUsername}_${contactUsername}`);
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  function markContactVerified(myUsername, contactUsername) {
    const storageKey = `e2ee_contact_${myUsername}_${contactUsername}`;
    const raw = localStorage.getItem(storageKey);
    if (!raw) return false;
    try {
      const record = JSON.parse(raw);
      record.verified = true;
      localStorage.setItem(storageKey, JSON.stringify(record));
      return true;
    } catch {
      return false;
    }
  }

  // ---- fingerprint computation ----

  async function computeFingerprint(publicKeyB64) {
    const raw = base64ToArrayBuf(publicKeyB64);
    const hash = await crypto.subtle.digest("SHA-256", raw);
    return formatFingerprint(hash);
  }

  // ---- session key derivation (ECDH + HKDF) ----

  async function deriveSessionKey(myPrivateKey, theirPublicKeyB64, contextInfo) {
    const theirPubKey = await importPublicKey(theirPublicKeyB64);

    // step 1: ECDH to get shared secret bits
    const sharedBits = await crypto.subtle.deriveBits(
      { name: "ECDH", public: theirPubKey },
      myPrivateKey,
      256
    );

    // step 2: import shared bits as HKDF key material
    const hkdfKey = await crypto.subtle.importKey(
      "raw",
      sharedBits,
      "HKDF",
      false,
      ["deriveKey"]
    );

    // step 3: HKDF to derive the actual AES-256-GCM key
    // use context info (e.g. sorted usernames) as info param for domain separation
    const encoder = new TextEncoder();
    const infoData = encoder.encode(contextInfo || "e2ee-session-key");

    const aesKey = await crypto.subtle.deriveKey(
      {
        name: "HKDF",
        hash: "SHA-256",
        salt: new Uint8Array(32), // fixed zero salt is ok here since ECDH output is already random
        info: infoData,
      },
      hkdfKey,
      { name: "AES-GCM", length: 256 },
      false,
      ["encrypt", "decrypt"]
    );

    return aesKey;
  }

  // build context string from two usernames (sorted so both sides get same key)
  function buildContext(user1, user2) {
    const sorted = [user1, user2].sort();
    return `e2ee:${sorted[0]}:${sorted[1]}`;
  }

  // ---- message encryption / decryption ----

  // encrypt a plaintext message with AES-256-GCM
  // metadata is bound as associated data (AAD) so tampering with it is detected
  async function encryptMessage(aesKey, plaintext, metadata) {
    const encoder = new TextEncoder();
    const plaintextBytes = encoder.encode(plaintext);

    // 12-byte random IV for each message (standard for GCM)
    const iv = crypto.getRandomValues(new Uint8Array(12));

    // build AAD from metadata — includes sender, receiver, counter, etc.
    const aadString = JSON.stringify(metadata);
    const aadBytes = encoder.encode(aadString);

    const ciphertext = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv: iv, additionalData: aadBytes },
      aesKey,
      plaintextBytes
    );

    return {
      ciphertext: arrayBufToBase64(ciphertext),
      iv: arrayBufToBase64(iv),
      metadata: metadata,
    };
  }

  // decrypt an encrypted message, verifying AAD integrity
  async function decryptMessage(aesKey, encryptedMsg) {
    const ciphertextBuf = base64ToArrayBuf(encryptedMsg.ciphertext);
    const iv = base64ToArrayBuf(encryptedMsg.iv);

    const encoder = new TextEncoder();
    const aadString = JSON.stringify(encryptedMsg.metadata);
    const aadBytes = encoder.encode(aadString);

    try {
      const plaintextBuf = await crypto.subtle.decrypt(
        { name: "AES-GCM", iv: new Uint8Array(iv), additionalData: aadBytes },
        aesKey,
        ciphertextBuf
      );
      const decoder = new TextDecoder();
      return decoder.decode(plaintextBuf);
    } catch (err) {
      throw new Error("Decryption failed — message may be tampered or wrong key");
    }
  }

  // ---- replay protection ----

  // simple counter-based replay detection
  // stores the highest seen counter per conversation partner
  const replayCounters = {};

  function getCounterKey(myUsername, contactUsername) {
    return `replay_${myUsername}_${contactUsername}`;
  }

  function getNextSendCounter(myUsername, contactUsername) {
    const key = `send_counter_${myUsername}_${contactUsername}`;
    let current = parseInt(localStorage.getItem(key) || "0", 10);
    current += 1;
    localStorage.setItem(key, current.toString());
    return current;
  }

  function checkReplayAndUpdate(myUsername, contactUsername, counter) {
    const key = getCounterKey(myUsername, contactUsername);

    // also keep a set of recently seen counters in memory for dedup
    if (!replayCounters[key]) {
      const stored = localStorage.getItem(`highest_${key}`);
      replayCounters[key] = {
        highest: stored ? parseInt(stored, 10) : 0,
        seen: new Set(),
      };
    }

    const state = replayCounters[key];

    // reject if counter is not higher than what we've seen
    if (counter <= state.highest) {
      // could be a replay or reorder — check seen set for recent ones
      if (state.seen.has(counter)) {
        return false; // duplicate
      }
      // allow slightly out-of-order within a window of 50
      if (state.highest - counter > 50) {
        return false; // too old
      }
    }

    state.seen.add(counter);
    if (counter > state.highest) {
      state.highest = counter;
      localStorage.setItem(`highest_${key}`, counter.toString());
    }

    // keep the seen set from growing forever
    if (state.seen.size > 200) {
      const arr = Array.from(state.seen).sort((a, b) => a - b);
      state.seen = new Set(arr.slice(-100));
    }

    return true;
  }

  // ---- public API ----

  return {
    generateIdentityKeypair,
    exportPublicKey,
    exportPrivateKey,
    importPublicKey,
    importPrivateKey,
    saveKeypairLocally,
    loadKeypairLocally,
    saveContactKey,
    loadContactKey,
    markContactVerified,
    computeFingerprint,
    deriveSessionKey,
    buildContext,
    encryptMessage,
    decryptMessage,
    getNextSendCounter,
    checkReplayAndUpdate,
    arrayBufToBase64,
    base64ToArrayBuf,
  };
})();
