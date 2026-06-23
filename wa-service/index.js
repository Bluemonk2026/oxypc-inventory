/**
 * OxyPC WhatsApp Service — MULTI-SESSION
 * --------------------------------------
 * Wraps whatsapp-web.js and exposes a REST API so the FastAPI backend can
 * generate QR codes, check status, and send messages.
 *
 * Each application user links their OWN WhatsApp number. Sessions are keyed by
 * `clientId` (= the OxyPC username), each with its own whatsapp-web.js Client,
 * its own LocalAuth folder (.wwebjs_auth/session-<user>), QR, status and phone.
 *
 * Every endpoint accepts a `user` parameter:
 *   - GET  endpoints: ?user=<username>
 *   - POST endpoints: { "user": "<username>", ... }
 * If omitted, the session id falls back to "default" (backward compatible).
 *
 * Endpoints:
 *   GET  /status?user=            → { status, phone_number, has_qr }
 *   GET  /qr?user=                → { qr_base64 }  (404 if not scanning)
 *   GET  /sessions                → { sessions: [{user,status,phone_number}] }
 *   POST /connect      {user}     → starts WA client, begins QR flow
 *   POST /disconnect   {user}     → destroys WA session
 *   POST /send         {user,phone,message}
 *   GET  /groups?user=
 *   POST /send-group   {user,group_id,message}
 *   GET  /group-messages/:group_id?user=&limit=
 *   POST /sync-group-messages {user,group_ids,limit}
 *
 * Run:  node index.js     Port: 3001 (or WA_PORT env var)
 */

const express = require('express');
const { Client, LocalAuth } = require('whatsapp-web.js');
const QRCode   = require('qrcode');
const path     = require('path');
const fs       = require('fs');

const app  = express();
const PORT = process.env.WA_PORT || 3001;
const AUTH_DIR = path.join(__dirname, '.wwebjs_auth');
app.use(express.json());

// ── Per-user session registry ─────────────────────────────────────────────
// sessions[clientId] = { status, qr_base64, phone_number, client }
const sessions = {};

function sanitizeId(u) {
  // whatsapp-web.js clientId must be [A-Za-z0-9_-]
  return (String(u || 'default').replace(/[^A-Za-z0-9_-]/g, '_') || 'default');
}

function userOf(req) {
  const raw = (req.query && req.query.user) || (req.body && req.body.user) || 'default';
  return sanitizeId(raw);
}

function getSession(id) {
  if (!sessions[id]) {
    sessions[id] = { status: 'disconnected', qr_base64: null, phone_number: null, client: null };
  }
  return sessions[id];
}

// ── Helper: create and initialize a per-user WA client ────────────────────
function createClient(id) {
  const s = getSession(id);
  if (s.client) {
    try { s.client.destroy(); } catch (_) {}
  }

  const client = new Client({
    authStrategy: new LocalAuth({
      clientId: id,               // → .wwebjs_auth/session-<id>  (isolates each user)
      dataPath: AUTH_DIR,
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
      s.qr_base64 = await QRCode.toDataURL(qr);
      s.status    = 'scanning';
      console.log(`[WA:${id}] QR code generated — waiting for scan`);
    } catch (err) {
      console.error(`[WA:${id}] QR generation error:`, err.message);
    }
  });

  client.on('ready', () => {
    s.status       = 'connected';
    s.qr_base64    = null;
    s.phone_number = client.info?.wid?.user || null;
    console.log(`[WA:${id}] Connected!  Number:`, s.phone_number);

    try {
      client.pupPage?.on('framedetached', (frame) => {
        if (!frame.parentFrame()) {
          console.warn(`[WA:${id}] Main frame detached — marking reconnecting`);
          s.status = 'reconnecting';
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
        user:         id,                          // which OxyPC user's session received it
        group_id:     msg.from,
        group_name:   chat.name || msg.from,
        sender_phone: contact.id?.user || msg.author || '',
        sender_name:  contact.pushname || contact.name || contact.id?.user || '',
        message_text: msg.body || '',
        message_type: msg.type || 'text',
        timestamp:    msg.timestamp,
      };
      fetch('http://localhost:8000/whatsapp/incoming-group-msg', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-WA-Secret': 'oxypc-wa-internal' },
        body: JSON.stringify(payload),
      }).catch(() => {});  // silently ignore if FastAPI is down
    } catch (_) {}
  });

  client.on('authenticated', () => {
    console.log(`[WA:${id}] Authenticated`);
  });

  client.on('auth_failure', (m) => {
    console.error(`[WA:${id}] Auth failure:`, m);
    s.status    = 'disconnected';
    s.qr_base64 = null;
    s.client    = null;
  });

  client.on('disconnected', (reason) => {
    console.log(`[WA:${id}] Disconnected:`, reason);
    s.status       = 'disconnected';
    s.qr_base64    = null;
    s.phone_number = null;
    s.client       = null;
  });

  client.on('change_state', (st) => {
    console.log(`[WA:${id}] State changed:`, st);
  });

  client.initialize();
  s.client = client;
  s.status = 'scanning';
  return client;
}

// ── Helper: detect Puppeteer session errors ───────────────────────────────
function isSessionBroken(err) {
  const msg = (err && err.message) ? err.message.toLowerCase() : '';
  return (
    msg.includes('detached frame') ||
    msg.includes('detached') ||
    msg.includes('execution context was destroyed') ||
    msg.includes('execution context') ||
    msg.includes('session closed') ||
    msg.includes('target closed') ||
    msg.includes('protocol error') ||
    msg.includes('page has been closed') ||
    msg.includes('frame was detached') ||
    msg.includes('attempted to use')
  );
}

function reconnectSoon(id) {
  setTimeout(() => { console.log(`[WA:${id}] Auto-reconnecting…`); createClient(id); }, 3000);
}

// ── REST Endpoints ────────────────────────────────────────────────────────

// GET /status?user=
app.get('/status', (req, res) => {
  const s = getSession(userOf(req));
  res.json({ status: s.status, phone_number: s.phone_number, has_qr: !!s.qr_base64 });
});

// GET /sessions — overview of every known session (admin)
app.get('/sessions', (req, res) => {
  res.json({
    sessions: Object.keys(sessions).map((id) => ({
      user:         id,
      status:       sessions[id].status,
      phone_number: sessions[id].phone_number,
      has_qr:       !!sessions[id].qr_base64,
    })),
  });
});

// GET /qr?user=
app.get('/qr', (req, res) => {
  const s = getSession(userOf(req));
  if (!s.qr_base64) return res.status(404).json({ error: 'No QR code available' });
  res.json({ qr_base64: s.qr_base64 });
});

// POST /connect  {user}
app.post('/connect', (req, res) => {
  const id = userOf(req);
  const s  = getSession(id);
  if (s.status === 'connected') {
    return res.json({ status: 'connected', phone_number: s.phone_number });
  }
  createClient(id);
  res.json({ status: 'scanning', message: 'WhatsApp client starting — QR will be ready shortly' });
});

// POST /disconnect  {user}
app.post('/disconnect', async (req, res) => {
  const id = userOf(req);
  const s  = getSession(id);
  if (s.client) {
    try { await s.client.destroy(); } catch (_) {}
    s.client = null;
  }
  s.status = 'disconnected';
  s.qr_base64 = null;
  s.phone_number = null;
  res.json({ status: 'disconnected' });
});

// POST /send  { user, phone, message }
app.post('/send', async (req, res) => {
  const id = userOf(req);
  const s  = getSession(id);
  const { phone, message } = req.body;

  if (!phone || !message) return res.status(400).json({ error: 'phone and message are required' });
  if (s.status === 'reconnecting') {
    return res.status(503).json({ error: 'WA session is reconnecting — please wait 15 seconds and try again.' });
  }
  if (s.status !== 'connected' || !s.client) return res.status(400).json({ error: 'WhatsApp not connected' });

  try {
    const cleanPhone = phone.replace(/[^0-9]/g, '');
    const numberId = await s.client.getNumberId(cleanPhone);
    if (!numberId) return res.status(400).json({ error: `${phone} is not registered on WhatsApp` });
    await s.client.sendMessage(numberId._serialized, message);
    console.log(`[WA:${id}] Message sent to`, numberId._serialized);
    res.json({ success: true, chat_id: numberId._serialized });
  } catch (err) {
    console.error(`[WA:${id}] Send error:`, err.message);
    if (isSessionBroken(err)) {
      s.status = 'reconnecting';
      reconnectSoon(id);
      return res.status(503).json({ error: 'WA session lost — reconnecting automatically. Please wait 15 seconds and try again.' });
    }
    res.status(500).json({ error: err.message });
  }
});

// GET /groups?user=
app.get('/groups', async (req, res) => {
  const id = userOf(req);
  const s  = getSession(id);
  if (s.status !== 'connected' || !s.client) return res.status(400).json({ error: 'WhatsApp not connected' });
  try {
    const chats = await s.client.getChats();
    const groups = chats.filter(c => c.isGroup).map(c => ({
      id:                c.id._serialized,
      name:              c.name,
      participant_count: c.participants ? c.participants.length : 0,
    }));
    res.json({ groups });
  } catch (err) {
    console.error(`[WA:${id}] Groups fetch error:`, err.message);
    if (isSessionBroken(err)) {
      s.status = 'reconnecting'; reconnectSoon(id);
      return res.status(503).json({ error: 'WA session lost — reconnecting automatically. Please wait 15 seconds and try again.' });
    }
    res.status(500).json({ error: err.message });
  }
});

// POST /send-group  { user, group_id, message }
app.post('/send-group', async (req, res) => {
  const id = userOf(req);
  const s  = getSession(id);
  const { group_id, message } = req.body;
  if (!group_id || !message) return res.status(400).json({ error: 'group_id and message are required' });
  if (s.status === 'reconnecting') {
    return res.status(503).json({ error: 'WA session is reconnecting — please wait 15 seconds and try again.' });
  }
  if (s.status !== 'connected' || !s.client) return res.status(400).json({ error: 'WhatsApp not connected' });
  try {
    await s.client.sendMessage(group_id, message);
    console.log(`[WA:${id}] Group message sent to`, group_id);
    res.json({ success: true, group_id });
  } catch (err) {
    console.error(`[WA:${id}] Group send error:`, err.message);
    if (isSessionBroken(err)) {
      s.status = 'reconnecting'; reconnectSoon(id);
      return res.status(503).json({ error: 'WA session lost — reconnecting automatically. Please wait 15 seconds and try again.' });
    }
    res.status(500).json({ error: err.message });
  }
});

// GET /group-messages/:group_id?user=&limit=50
app.get('/group-messages/:group_id', async (req, res) => {
  const id = userOf(req);
  const s  = getSession(id);
  if (s.status !== 'connected' || !s.client) return res.status(400).json({ error: 'WhatsApp not connected' });
  const groupId = decodeURIComponent(req.params.group_id);
  const limit   = Math.min(parseInt(req.query.limit) || 50, 200);
  try {
    const chat = await s.client.getChatById(groupId);
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
    console.error(`[WA:${id}] group-messages error:`, err.message);
    if (isSessionBroken(err)) {
      s.status = 'reconnecting'; reconnectSoon(id);
      return res.status(503).json({ error: 'WA session lost — reconnecting, try again in 15s' });
    }
    res.status(500).json({ error: err.message });
  }
});

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

// POST /sync-group-messages  { user, group_ids: [...], limit: 50 }
app.post('/sync-group-messages', async (req, res) => {
  const id = userOf(req);
  const s  = getSession(id);
  if (s.status !== 'connected' || !s.client) return res.status(400).json({ error: 'WhatsApp not connected' });
  const { group_ids = [], limit = 50 } = req.body;
  if (!group_ids.length) return res.status(400).json({ error: 'group_ids required' });

  const cap           = Math.min(parseInt(limit) || 50, 200);
  const all           = [];
  let   errorCount    = 0;
  let   sessionBroken = false;

  let chatMap = {};
  try {
    const allChats = await s.client.getChats();
    for (const c of allChats) {
      if (c.isGroup) chatMap[c.id._serialized] = c;
    }
    console.log(`[WA:${id}] Loaded ${Object.keys(chatMap).length} groups into cache`);
  } catch (err) {
    console.error(`[WA:${id}] getChats failed:`, err.message);
    if (isSessionBroken(err)) {
      s.status = 'reconnecting'; reconnectSoon(id);
      return res.status(503).json({ error: 'WA session lost — reconnecting. Try again in 15 seconds.' });
    }
    return res.status(500).json({ error: err.message });
  }

  for (const gid of group_ids) {
    if (sessionBroken) { errorCount++; continue; }
    const chat = chatMap[gid];
    if (!chat) { errorCount++; continue; }
    try {
      await sleep(150);
      const messages = await chat.fetchMessages({ limit: cap });
      for (const msg of messages) {
        if (!msg.body) continue;
        const senderPhone = (msg.author || '').replace('@c.us', '').replace('@s.whatsapp.net', '');
        all.push({
          from_me:      msg.fromMe,
          sender_name:  '',
          sender_phone: senderPhone,
          message_text: msg.body,
          message_type: msg.type || 'text',
          timestamp:    msg.timestamp,
          group_id:     gid,
          group_name:   chat.name,
        });
      }
      console.log(`[WA:${id}] ${chat.name}: ${messages.length} msgs`);
    } catch (err) {
      console.error(`[WA:${id}] fetchMessages error for ${gid}:`, err.message);
      errorCount++;
      if (isSessionBroken(err)) {
        console.warn(`[WA:${id}] Puppeteer session broken mid-sync — stopping, will reconnect`);
        sessionBroken = true;
        s.status      = 'reconnecting';
        reconnectSoon(id);
      }
    }
  }

  res.json({ total: all.length, messages: all, errors: errorCount, session_broken: sessionBroken });
});

// ── Restore previously-linked sessions on startup ──────────────────────────
function restoreSessions() {
  let names = [];
  try {
    names = fs.readdirSync(AUTH_DIR)
      .filter(n => n.startsWith('session-'))
      .map(n => n.slice('session-'.length))
      .filter(Boolean);
  } catch (_) { /* dir may not exist yet */ }
  if (!names.length) {
    console.log('[WA] No saved per-user sessions to restore.');
    return;
  }
  for (const id of names) {
    console.log('[WA] Restoring session for user:', id);
    createClient(id);
  }
}

// ── Start server ──────────────────────────────────────────────────────────
app.listen(PORT, () => {
  console.log(`\n[OxyPC WA Service] Running on http://localhost:${PORT}  (multi-session)`);
  console.log('[OxyPC WA Service] Restoring saved sessions…\n');
  restoreSessions();
});
