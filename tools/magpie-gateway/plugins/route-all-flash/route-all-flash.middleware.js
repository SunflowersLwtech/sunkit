// Splits agent traffic by WHO is calling, as magpie gateway middleware
// (onRequest: before routing). The gateway resolves model aliases first
// (auto/x -> group/auto-x), and Info carries no caller key, so the split
// uses what the body itself carries: cc-connect's append_system_prompt
// ("刘维的个人助理…") for the Feishu assistant, and Claude Code's
// metadata.user_id (a JSON string: device_id, account_uuid, session_id)
// for the sessions kept on their own model.
//
//   feishu assistant        -> group/flash-paid (DeepSeek official first,
//                             dashscope behind it)
//   deepseek/*, always-up,  -> untouched (real routes of their own)
//   group/flash-paid        -> itself
//   zcode/*                 -> untouched (the CLI's own plan)
//   a session in options.sessions
//                           -> its own Claude model as the claude
//                             provider's (claude/claude-opus-5-5), so it
//                             reaches the claude provider and, when every
//                             seat is at its account cap, that provider's
//                             fallback takes it (dashscope DeepSeek)
//   a session or device in options.secretary, while options.seatUntil is
//   a moment still ahead (Date.now() < seatUntil)
//                           -> claude/claude-opus-5-5 too: the secretary
//                             gets a seat only while a timer renews that
//                             lease from the seats' own 5-hour usage, so it
//                             never eats a window on its own
//   everything else         -> group/flash-ds (dashscope only)
//
//   {"free": "group/flash-ds", "paid": "group/flash-paid",
//    "sessions": ["<session id>", …], "secretary": ["<device or session>", …],
//    "seatUntil": <epoch ms>, "off": false}

const FREE = "group/flash-ds"
const PAID = "group/flash-paid"
const SEAT = "claude/claude-opus-5-5"
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

export function onRequest(body, ctx) {
  const o = (ctx && ctx.options) || {}
  if (o.off) return
  if (!body || typeof body.model !== "string" || !body.model) return
  const m = body.model
  if (m === PAID || PASSTHROUGH.test(m)) return body
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
