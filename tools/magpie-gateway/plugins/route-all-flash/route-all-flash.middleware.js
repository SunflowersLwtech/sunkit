// Splits agent traffic by WHO is calling, as magpie gateway middleware
// (onRequest: before routing). The gateway resolves model aliases first
// (auto/x -> group/auto-x), and Info carries no caller key, so the split
// uses what the body itself carries: cc-connect's append_system_prompt
// ("刘维的个人助理…") for the Feishu assistant, and Claude Code's
// metadata.user_id (a JSON string: device_id, account_uuid, session_id)
// for the sessions kept on their own model. Info does carry the agent
// magpie reads from the User-Agent (ctx.agent), which names fleet-watch.
//
//   feishu assistant        -> group/flash-paid
//   deepseek/*, always-up,  -> untouched (real routes of their own)
//   group/flash-paid        -> itself
//   zcode/*                 -> untouched (the CLI's own plan)
//   fleet-watch's health probes (ctx.agent "fleet-watch", and a body that
//   is the probe itself: see isProbe)
//                           -> options.probe, else claude/claude-opus-5-5:
//                             sent to group/flash-ds they landed on its
//                             tier billed by the request (Copilot, 200 a
//                             month) once the tiers before it were out,
//                             one probe per group an hour, more while one
//                             fails; a seat is billed by the token. A probe
//                             of the free route itself (fleet-watch probes
//                             group/flash-ds only while it is down) is left
//                             as asked, so it tests that route
//   a session in options.sessions
//                           -> its own Claude model as the claude
//                             provider's (claude/claude-opus-5-5), so it
//                             reaches the claude provider and, when every
//                             seat is at its account cap, that provider's
//                             fallback takes it
//   a session or device in options.secretary, while options.seatUntil is
//   a moment still ahead (Date.now() < seatUntil)
//                           -> claude/claude-opus-5-5 too: the secretary
//                             gets a seat only while a timer renews that
//                             lease from the seats' own 5-hour usage, so it
//                             never eats a window on its own
//   everything else         -> group/flash-ds
//
//   {"free": "group/flash-ds", "paid": "group/flash-paid",
//    "sessions": ["<session id>", …], "secretary": ["<device or session>", …],
//    "seatUntil": <epoch ms>, "probe": "<provider/model>", "off": false}

const FREE = "group/flash-ds"
const PAID = "group/flash-paid"
const SEAT = "claude/claude-opus-5-5"
const PROBE = "fleet-watch"
const PASSTHROUGH = /^(deepseek\/|always-up|devin\/|group\/flash-paid|zcode\/|workbuddy\/|litellm-claude-api\/)/  // 11-09: cc-compactor 的压缩请求发 litellm-claude-api/*，不放行就被改写到 flash-ds（现为 WorkBuddy），专用 Haiku 通道一个都走不到
const FEISHU = "刘维的个人助理"

function isFeishu(body) {
  try {
    return JSON.stringify(body).includes(FEISHU)
  } catch (e) {
    return false
  }
}

// who is Claude Code's conversation, from the body's metadata.user_id:
// its session id and the device it runs on, "" when the body names none.
function whoIs(body) {
  const out = { session: "", device: "" }
  try {
    const raw = body && body.metadata && body.metadata.user_id
    if (!raw) return out
    const u = JSON.parse(raw)
    if (u && typeof u === "object") {
      if (typeof u.session_id === "string") out.session = u.session_id
      if (typeof u.device_id === "string") out.device = u.device_id
      return out
    }
  } catch (e) {
    // not JSON: the older "user_<hash>_account_<uuid>_session_<uuid>"
    const m = /_session_([0-9A-Fa-f-]{36})/.exec(String(body.metadata.user_id))
    if (m) out.session = m[1]
  }
  return out
}

// seatModel is m as the claude provider's own model, so that provider's
// fallback applies: claude-opus-5-5 and group/claude-opus-5-5 both become
// claude/claude-opus-5-5. "" for a model that isn't a Claude one.
function seatModel(m) {
  if (/^claude\//.test(m)) return m
  const hit = /^(?:group\/|auto\/|group\/auto-)?(claude-[a-z0-9][a-z0-9.-]*)$/.exec(m)
  return hit ? "claude/" + hit[1] : ""
}

function listed(v, x) {
  return x !== "" && Array.isArray(v) && v.indexOf(x) >= 0
}

// the question server/fleet-watch.py's probe() asks, with 12 hex digits
const PROBE_TEXT = /^Health check [0-9a-f]{12}\. Reply with the word PONG\.$/
const PROBE_MAX_TOKENS = 256

function empty(v) {
  return v === undefined || v === null || v === "" || (Array.isArray(v) && v.length === 0)
}

// isProbe: one of fleet-watch's health probes. magpie names the agent from
// the User-Agent (fleet-watch/1), which any holder of a gateway key can
// send, so the body must be the probe as well: one user message holding the
// probe's question and nothing else, no system prompt, no tools, and
// max_tokens no more than the probe's 256. Anything else under that name is
// split like any other request, so the name alone gets no one a seat.
function isProbe(body, ctx) {
  if (!ctx || ctx.agent !== PROBE) return false
  if (!empty(body.tools) || !empty(body.system)) return false
  if (typeof body.max_tokens !== "number" || body.max_tokens > PROBE_MAX_TOKENS) return false
  const ms = body.messages
  if (!Array.isArray(ms) || ms.length !== 1 || !ms[0] || ms[0].role !== "user") return false
  let c = ms[0].content
  if (Array.isArray(c)) {
    if (c.length !== 1 || !c[0] || c[0].type !== "text") return false
    c = c[0].text
  }
  return typeof c === "string" && PROBE_TEXT.test(c)
}

export function onRequest(body, ctx) {
  const o = (ctx && ctx.options) || {}
  if (o.off) return
  if (!body || typeof body.model !== "string" || !body.model) return
  const m = body.model
  if (m === PAID || PASSTHROUGH.test(m)) return body
  if (isProbe(body, ctx)) {
    const free = typeof o.free === "string" && o.free ? o.free : FREE
    if (m === free) return body
    body.model = typeof o.probe === "string" && o.probe ? o.probe : SEAT
    return body
  }
  const who = whoIs(body)
  if (listed(o.sessions, who.session)) {
    const seat = seatModel(m)
    if (seat) {
      body.model = seat
      return body
    }
  }
  const leased = typeof o.seatUntil === "number" && Date.now() < o.seatUntil
  if (leased && (listed(o.secretary, who.session) || listed(o.secretary, who.device))) {
    body.model = seatModel(m) || SEAT
    return body
  }
  body.model = isFeishu(body) ? PAID : (typeof o.free === "string" && o.free ? o.free : FREE)
  return body
}
