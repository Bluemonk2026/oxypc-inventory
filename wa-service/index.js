/**
 * OxyPC WhatsApp Service
 * ----------------------
 * Wraps whatsapp-web.js and exposes a simple REST API so the
 * FastAPI Python backend can generate QR codes, check status,
 * and send messages without any Python↔WA lib coupling.
 *
 * Endpoints:
 *   GET  /status          → { status, phone_number, has_qr }
 *   GET  /qr              → { qr_base64 }  (404 if not scanning)
 *   POST /connect         → starts WA client, begins QR flow
 *   POST /disconnect      → destroys WA session
 *   POST /send            → { phone, message }  → sends text message
 *
 * Run:  node index.js
 * Port: 3001 (or WA_PORT env var)
 */

const express = require('express');
const { Client, LocalAuth } = require('whatsapp-web.js');
const QRCode   = require('qrcode');
const path     = require('path');

const app  = express();
const PORT = process.env.WA_PORT || 3001;
app.use(express.json());

// ── Shared state ──────────────────────────────────────────────────────────
const state = {
  status:       'disconnected',   // 'disconnected' | 'scanning' | 'connected'
  qr_base64:    null,
  phone_number: null,
  client:       null,
};

// ── Helper: create and initialize a WA client ────────────────────────────
function createClient() {
  if (state.client) {
    try { state.client.destroy(); } catch (_) {}
  }

  const client = new Client({
    authStrategy: new LocalAuth({
      dataPath: path.join(__dirname, '.wwebjs_auth'),
    }),
    webVersionCache: {
      type: 'remote',
      remotePath: 'https://raw.githubusercontent.com/wppconnect-team/wa-version/main/html/2.3.7074.html',
    },
    puppeteer: {
      headless: true,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu',
        '--disable-extensions',
        '--disable-background-networking',
        '--disable-background-timer-throttling',
        '--disable-renderer-backgrounding',
        // NOTE: --single-process removed — causes detached Frame errors on Windows
      ],
    },
  });

  client.on('qr', async (qr) => {
    try {
      state.qr_base64 = await QRCode.toDataURL(qr);
      state.status    = 'scanning';
      console.log('[WA] QR code generated — waiting for scan');
    } catch (err) {
      console.error('[WA] QR generation error:', err.message);
    }
  });

  client.on('ready', () => {
    state.status       = 'connected';
    state.qr_base64    = null;
    state.phone_number = client.info?.wid?.user || null;
    console.log('[WA] Connected!  Number:', state.phone_number);

    // Attach frame-detach listener now that pupPage is available
    try {
      client.pupPage?.on('framedetached', (frame) => {
        if (!frame.parentFrame()) {
          console.warn('[WA] Main frame detached — WA page reloading, marking reconnecting');
          state.status = 'reconnecting';
        }
      });
    } catch (_) {}
  });

  // ── Capture incoming group messages and forward to FastAPI ───────────────
  client.on('message', async (msg) => {
    try {
      if (!msg.from.endsWith('@g.us')) return;   // group messages only
      if (msg.fromMe) return;                     // ignore own messages
      const chat = await msg.getChat();
      const contact = await msg.getContact();
      const payload = {
        group_id:     msg.from,
        group_name:   chat.name || msg.from,
        sender_phone: contact.id?.user || msg.author || '',
        sender_name:  contact.pushname || contact.name || contact.id?.user || '',
        message_text: msg.body || '',
        message_type: msg.type || 'text',
        timestamp:    msg.timestamp,
      };
      // Non-blocking POST to FastAPI
      fetch('http://localhost:8000/whatsapp/incoming-group-msg', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-WA-Secret': 'oxypc-wa-internal' },
        body: JSON.stringify(payload),
      }).catch(() => {});  // silently ignore if FastAPI is down
    } catch (_) {}
  });

  client.on('authenticated', () => {
    console.log('[WA] Authenticated');
  });

  client.on('auth_failure', (msg) => {
    console.error('[WA] Auth failure:', msg);
    state.status    = 'disconnected';
    state.qr_base64 = null;
    state.client    = null;
  });

  client.on('disconnected', (reason) => {
    console.log('[WA] Disconnected:', reason);
    state.status       = 'disconnected';
    state.qr_base64    = null;
    state.phone_number = null;
    state.client       = null;
  });

  // Detect WA state changes (CONFLICT, TOS_BLOCK, etc.)
  client.on('change_state', (s) => {
    console.log('[WA] State changed:', s);
  });

  client.initialize();
  state.client = client;
  state.status = 'scanning';
  return client;
}

// ── Helper: detect Puppeteer session errors ───────────────────────────────
function isSessionBroken(err) {
  const msg = (err && err.message) ? err.message.toLowerCase() : '';
  return (
    msg.includes('detached frame') ||
    msg.includes('detached') ||          // catches "Attempted to use detached Frame"
    msg.includes('execution context was destroyed') ||
    msg.includes('execution context') ||
    msg.includes('session closed') ||
    msg.includes('target closed') ||
    msg.includes('protocol error') ||
    msg.includes('page has been closed') ||
    msg.includes('frame was detached') ||
    msg.includes('attempted to use')     // Puppeteer prefix for detached/destroyed errors
  );
}

// ── REST Endpoints ────────────────────────────────────────────────────────

// GET /status
app.get('/status', (req, res) => {
  res.json({
    status:       state.status,
    phone_number: state.phone_number,
    has_qr:       !!state.qr_base64,
  });
});

// GET /qr  — returns base64 PNG data-URL
app.get('/qr', (req, res) => {
  if (!state.qr_base64) {
    return res.status(404).json({ error: 'No QR code available' });
  }
  res.json({ qr_base64: state.qr_base64 });
});

// POST /connect  — start WA client (or restart if disconnected)
app.post('/connect', (req, res) => {
  if (state.status === 'connected') {
    return res.json({ status: 'connected', phone_number: state.phone_number });
  }
  createClient();
  res.json({ status: 'scanning', message: 'WhatsApp client starting — QR will be ready shortly' });
});

// POST /disconnect  — destroy session and delete saved auth
app.post('/disconnect', async (req, res) => {
  if (state.client) {
    try { await state.client.destroy(); } catch (_) {}
    state.client = null;
  }
  state.status       = 'disconnected';
  state.qr_base64    = null;
  state.phone_number = null;
  res.json({ status: 'disconnected' });
});

// POST /send  { phone: "91XXXXXXXXXX", message: "text" }
app.post('/send', async (req, res) => {
  const { phone, message } = req.body;

  if (!phone || !message) {
    return res.status(400).json({ error: 'phone and message are required' });
  }
  if (state.status === 'reconnecting') {
    return res.status(503).json({ error: 'WA session is reconnecting — please wait 15 seconds and try again.' });
  }
  if (state.status !== 'connected' || !state.client) {
    return res.status(400).json({ error: 'WhatsApp not connected' });
  }

  try {
    const cleanPhone = phone.replace(/[^0-9]/g, '');
    // Resolve proper WhatsApp ID — handles LID required for new/unknown contacts
    const numberId = await state.client.getNumberId(cleanPhone);
    if (!numberId) {
      return res.status(400).json({ error: `${phone} is not registered on WhatsApp` });
    }
    await state.client.sendMessage(numberId._serialized, message);
    console.log('[WA] Message sent to', numberId._serialized);
    res.json({ success: true, chat_id: numberId._serialized });
  } catch (err) {
    console.error('[WA] Send error:', err.message);
    if (isSessionBroken(err)) {
      state.status = 'reconnecting';
      setTimeout(() => { console.log('[WA] Auto-reconnecting…'); createClient(); }, 3000);
      return res.status(503).json({ error: 'WA session lost — reconnecting automatically. Please wait 15 seconds and try again.' });
    }
    res.status(500).json({ error: err.message });
  }
});

// GET /groups  — list all WhatsApp groups the connected account is in
app.get('/groups', async (req, res) => {
  if (state.status !== 'connected' || !state.client) {
    return res.status(400).json({ error: 'WhatsApp not connected' });
  }
  try {
    const chats = await state.client.getChats();
    const groups = chats
      .filter(c => c.isGroup)
      .map(c => ({
        id:                c.id._serialized,
        name:              c.name,
        participant_count: c.participants ? c.participants.length : 0,
      }));
    res.json({ groups });
  } catch (err) {
    console.error('[WA] Groups fetch error:', err.message);
    if (isSessionBroken(err)) {
      state.status = 'reconnecting';
      setTimeout(() => { console.log('[WA] Auto-reconnecting…'); createClient(); }, 3000);
      return res.status(503).json({ error: 'WA session lost — reconnecting automatically. Please wait 15 seconds and try again.' });
    }
    res.status(500).json({ error: err.message });
  }
});

// POST /send-group  { group_id, message }
app.post('/send-group', async (req, res) => {
  const { group_id, message } = req.body;
  if (!group_id || !message) {
    return res.status(400).json({ error: 'group_id and message are required' });
  }
  if (state.status === 'reconnecting') {
    return res.status(503).json({ error: 'WA session is reconnecting — please wait 15 seconds and try again.' });
  }
  if (state.status !== 'connected' || !state.client) {
    return res.status(400).json({ error: 'WhatsApp not connected' });
  }
  try {
    await state.client.sendMessage(group_id, message);
    console.log('[WA] Group message sent to', group_id);
    res.json({ success: true, group_id });
  } catch (err) {
    console.error('[WA] Group send error:', err.message);
    if (isSessionBroken(err)) {
      state.status = 'reconnecting';
      setTimeout(() => { console.log('[WA] Auto-reconnecting…'); createClient(); }, 3000);
      return res.status(503).json({ error: 'WA session lost — reconnecting automatically. Please wait 15 seconds and try again.' });
    }
    res.status(500).json({ error: err.message });
  }
});

// GET /group-messages/:group_id?limit=50  — fetch recent messages from one group
app.get('/group-messages/:group_id', async (req, res) => {
  if (state.status !== 'connected' || !state.client) {
    return res.status(400).json({ error: 'WhatsApp not connected' });
  }
  const groupId = decodeURIComponent(req.params.group_id);
  const limit   = Math.min(parseInt(req.query.limit) || 50, 200);
  try {
    const chat = await state.client.getChatById(groupId);
    if (!chat) return res.status(404).json({ error: 'Group not found' });
    const messages = await chat.fetchMessages({ limit });
    const result = [];
    for (const msg of messages) {
      if (!msg.body) continue;
      let senderName = '';
      let senderPhone = '';
      try {
        const contact = await msg.getContact();
        senderName  = contact.pushname || contact.name || '';
        senderPhone = contact.id?.user || msg.author || '';
      } catch (_) {
        senderPhone = msg.author || '';
      }
      result.push({
        id:           msg.id._serialized,
        from_me:      msg.fromMe,
        sender_name:  senderName,
        sender_phone: senderPhone,
        message_text: msg.body,
        message_type: msg.type || 'text',
        timestamp:    msg.timestamp,
        group_id:     groupId,
        group_name:   chat.name,
      });
    }
    res.json({ messages: result, group_name: chat.name });
  } catch (err) {
    console.error('[WA] group-messages error:', err.message);
    if (isSessionBroken(err)) {
      state.status = 'reconnecting';
      setTimeout(() => createClient(), 3000);
      return res.status(503).json({ error: 'WA session lost — reconnecting, try again in 15s' });
    }
    res.status(500).json({ error: err.message });
  }
});

// Helper: small delay to avoid overwhelming Puppeteer
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

// POST /sync-group-messages  { group_ids: [...], limit: 50 }
// Fetches messages from multiple groups and returns them all
app.post('/sync-group-messages', async (req, res) => {
  if (state.status !== 'connected' || !state.client) {
    return res.status(400).json({ error: 'WhatsApp not connected' });
  }
  const { group_ids = [], limit = 50 } = req.body;
  if (!group_ids.length) return res.status(400).json({ error: 'group_ids required' });

  const cap           = Math.min(parseInt(limit) || 50, 200);
  const all           = [];
  let   errorCount    = 0;
  let   sessionBroken = false;

  // ── Step 1: Get all chats ONCE (1 Puppeteer call vs 305 getChatById calls) ──
  let chatMap = {};
  try {
    const allChats = await state.client.getChats();
    for (const c of allChats) {
      if (c.isGroup) chatMap[c.id._serialized] = c;
    }
    console.log(`[WA] Loaded ${Object.keys(chatMap).length} groups into cache`);
  } catch (err) {
    console.error('[WA] getChats failed:', err.message);
    if (isSessionBroken(err)) {
      state.status = 'reconnecting';
      setTimeout(() => { console.log('[WA] Auto-reconnecting...'); createClient(); }, 3000);
      return res.status(503).json({ error: 'WA session lost — reconnecting. Try again in 15 seconds.' });
    }
    return res.status(500).json({ error: err.message });
  }

  // ── Step 2: Fetch messages per group with a small delay ───────────────────
  for (const gid of group_ids) {
    if (sessionBroken) { errorCount++; continue; }

    const chat = chatMap[gid];
    if (!chat) { errorCount++; continue; }

    try {
      await sleep(150);   // breathe between groups — prevents WA page reload
      const messages = await chat.fetchMessages({ limit: cap });
      for (const msg of messages) {
        if (!msg.body) continue;
        // Use msg.author directly — avoids 1 Puppeteer call per message
        const senderPhone = (msg.author || '').replace('@c.us', '').replace('@s.whatsapp.net', '');
        all.push({
          from_me:      msg.fromMe,
          sender_name:  '',           // populated later by incoming-msg webhook
          sender_phone: senderPhone,
          message_text: msg.body,
          message_type: msg.type || 'text',
          timestamp:    msg.timestamp,
          group_id:     gid,
          group_name:   chat.name,
        });
      }
      console.log(`[WA] ${chat.name}: ${messages.length} msgs`);
    } catch (err) {
      console.error(`[WA] fetchMessages error for ${gid}:`, err.message);
      errorCount++;
      if (isSessionBroken(err)) {
        console.warn('[WA] Puppeteer session broken mid-sync — stopping, will reconnect');
        sessionBroken = true;
        state.status  = 'reconnecting';
        setTimeout(() => { console.log('[WA] Auto-reconnecting...'); createClient(); }, 3000);
      }
    }
  }

  res.json({
    total:          all.length,
    messages:       all,
    errors:         errorCount,
    session_broken: sessionBroken,
  });
});

// ── Start server ──────────────────────────────────────────────────────────
app.listen(PORT, () => {
  console.log(`\n[OxyPC WA Service] Running on http://localhost:${PORT}`);
  console.log('[OxyPC WA Service] Auto-connecting on start...\n');
  // Auto-try to restore a saved session on startup
  createClient();
});
