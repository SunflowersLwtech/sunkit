// Channel messages that arrive while a Claude Code session is working, as magpie gateway
// middleware (onProvider: only what the named providers are sent changes).
//
// A channel message (mesh, Telegram, …) that reaches Claude Code 2.1.3xx while a turn is
// running goes into the next request as a {role: "system"} message after the tool results:
//   A message arrived from plugin:mesh:mesh while you were working:
//   <channel source="plugin:mesh:mesh" from="…" msg_id="msg_…">…</channel>
//
//   IMPORTANT: This is NOT from your user — … After completing your current task, decide
//   whether/how to respond.
// often in one text block with other notices (a background task's <task-notification>,
// "<tools-used-before-summary>…", an environment update). magpie 0.1.2421 tells a seat's run
// only what saidWithResults and withTaskNotices pick out of the messages after the results:
// the user's mid-turn words ("The user sent a new message while you were working:") and
// background task notices. Every other system text is left out, so the run's model never
// saw the channel message. A message that came while the session was idle is a user turn
// and was never affected. Measured 2026-11-11: on devdesk, 495 of the mesh messages in the
// week's transcripts came mid-turn this way. One session's run (its server-side transcript on
// the gateway) held none of the 9 that came mid-turn between 22:30 and 00:40 UTC,
// against all 7 that came as user turns. Upstream main (28a79bc33) has the same rule.
//
// Each channel message in a system message after tool results is moved to the end of the
// last tool_result before it, inside <system-reminder> tags, word for word. That is where
// withTaskNotices puts a task notification, and where Claude Code itself puts a mid-turn
// notice for models without system messages. magpie hands that result to the run, so the
// run's model reads the channel message with the result. Its "NOT from your user" note
// goes with it. The rest of the system text stays where it was. A system message left
// with nothing goes, and its cache_control goes onto the tool_result.
//
// A channel message is taken only where Claude Code puts one: at the start of the text,
// after a blank line, or right after "</tools-used-before-summary>\n", with its next line
// opening <channel source=". Claude Code 2.1.322's own recognizer takes one only at the
// start of a text in the same way. A hook's output that echoes such a block inside its
// own line stays where it was; lifted into the result, a forged block would read like a
// real channel message there.
//
// magpie keeps a run only while the conversation it last heard is the start of the new
// request (follows: a hash of every message). The rewrite is a function of the body alone,
// so every request moves the same messages to the same places and the hash agrees from
// one turn to the next. A message already in a running conversation's history when the
// middleware is turned on would change that conversation's past, and magpie would let the
// run go and tell a new one the whole conversation. `since` keeps that from happening:
//   - absent (null, ""): nothing moves, and the log says so once. `magpie plugin add`
//     turns a new entry on with no options before `magpie plugin options` can set any, so
//     the entry it adds must be inert;
//   - 0: every channel message moves, one without a msg_id too;
//   - a time (an ISO date-time ending in Z or ±hh:mm, or epoch ms as a number or digits):
//     only channel messages whose msg_id (a ULID, so a send time) is at it or later move;
//     one without a msg_id stays. The msg_id is read from the <channel …> tag only, so a
//     message without one that quotes another message's msg_id still stays;
//   - anything else (a negative number, -0, a date-time with no zone, which the host would
//     read in its own local time and so land hours off, a string that names no moment):
//     nothing moves.
// Set `since` to a moment just after the middleware is turned on.
//
//   {"providers": ["claude"], "since": "2026-11-11T02:00:00Z", "log": true, "off": false}

const CHANNEL = /(^|\n\n|<\/tools-used-before-summary>\n)(A message arrived from [^\n]+? while you were working:\n<channel source="[\s\S]*?<\/channel>(?:\n\nIMPORTANT: This is NOT from your user[^\n]*)?)/g
// in the segment's own opening tag (attribute values carry no ">": mesh escapes it)
const MSG_ID = /^A message arrived from [^\n]+? while you were working:\n<channel source="[^>]*?\bmsg_id="msg_([0-9A-HJKMNP-TV-Z]{26})"/
// a date-time that names its zone
const ZONED = /(?:Z|[+-]\d{2}:\d{2})$/
const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

/** The send time (epoch ms) of a ULID: its first ten characters. */
export function ulidTime(ulid) {
  let t = 0
  for (const c of ulid.slice(0, 10)) {
    const v = CROCKFORD.indexOf(c)
    if (v < 0) return NaN
    t = t * 32 + v
  }
  return t
}

// undefined when absent, NaN when it names no moment
function sinceOf(v) {
  if (v === undefined || v === null || v === "") return undefined
  // -0 < 0 is false, and since > 0 too: it would move every message
  if (typeof v === "number") return Object.is(v, -0) ? NaN : v
  const s = String(v).trim()
  // Date.parse("0") is a day in 2000 and Date.parse("-5") a date too, so digits are epoch ms;
  // a leading minus is a negative number (or -0), which names no moment here
  if (/^-?\d+$/.test(s)) return s[0] === "-" ? NaN : Number(s)
  return ZONED.test(s) ? Date.parse(s) : NaN
}

// The channel messages in text, where Claude Code puts them: [start, end) and the words.
function channelSegments(text) {
  const out = []
  const re = new RegExp(CHANNEL.source, "g")
  let m
  while ((m = re.exec(text)) !== null) {
    const start = m.index + m[1].length
    out.push({ start, end: start + m[2].length, text: m[2] })
  }
  return out
}

function textBlocks(m) {
  if (typeof m.content === "string") return [{ get: () => m.content, set: (s) => { m.content = s } }]
  if (!Array.isArray(m.content)) return []
  return m.content
    .filter((b) => b && b.type === "text" && typeof b.text === "string")
    .map((b) => ({ block: b, get: () => b.text, set: (s) => { b.text = s } }))
}

function lastToolResult(m) {
  if (!m || m.role !== "user" || !Array.isArray(m.content)) return undefined
  for (let i = m.content.length - 1; i >= 0; i--) {
    const b = m.content[i]
    if (b && b.type === "tool_result") return b
  }
  return undefined
}

function appendTo(result, text) {
  const c = result.content
  if (typeof c === "string") result.content = c === "" ? text : c + "\n\n" + text
  else if (Array.isArray(c)) c.push({ type: "text", text })
  else result.content = [{ type: "text", text }]
}

let saidInert = false

export function onProvider(body, ctx) {
  const o = (ctx && ctx.options) || {}
  if (o.off) return
  const providers = Array.isArray(o.providers) && o.providers.length ? o.providers : ["claude"]
  const p = (ctx && ctx.provider) || {}
  if (!providers.includes(p.id) && !providers.includes(p.account)) return
  if (!ctx || ctx.protocol !== "anthropic" || !body || !Array.isArray(body.messages)) return
  const since = sinceOf(o.since)
  if (since === undefined) {
    // what `magpie plugin add` leaves until `plugin options` gives it a since
    if (!saidInert && o.log !== false && typeof console !== "undefined") {
      saidInert = true
      console.log("channel-midturn: no since in its options, so nothing moves; set since to a time, or to 0 to move every channel message")
    }
    return
  }
  if (Number.isNaN(since) || since < 0) return

  const msgs = body.messages
  let lastReply = -1
  for (let i = msgs.length - 1; i >= 0; i--) if (msgs[i] && msgs[i].role === "assistant") { lastReply = i; break }
  let changed = false
  const moved = []
  const drop = new Set()
  for (let i = 0; i < msgs.length; i++) {
    const m = msgs[i]
    if (!m || m.role !== "system") continue
    // the results this system message came after: the user message before it, past any
    // other system messages; none (no results since the reply) leaves it where it is
    let j = i - 1
    while (j >= 0 && msgs[j] && msgs[j].role === "system") j--
    const result = j >= 0 ? lastToolResult(msgs[j]) : undefined
    if (!result) continue
    const take = []
    for (const t of textBlocks(m)) {
      const text = t.get()
      if (text.indexOf("A message arrived from ") < 0) continue
      let rest = ""
      let at = 0
      for (const seg of channelSegments(text)) {
        const id = MSG_ID.exec(seg.text)
        // since 0 moves every one; a time, those sent at it or later
        if (since > 0 && (!id || !(ulidTime(id[1]) >= since))) continue
        rest += text.slice(at, seg.start)
        at = seg.end
        take.push(seg.text)
        if (i > lastReply) moved.push(id ? "msg_" + id[1] : "?")
      }
      if (at === 0) continue
      rest = (rest + text.slice(at)).replace(/\n{3,}/g, "\n\n").trim()
      if (rest !== "") t.set(rest)
      else if (t.block) {
        if (t.block.cache_control && !result.cache_control) result.cache_control = t.block.cache_control
        m.content = m.content.filter((b) => b !== t.block)
      } else t.set("")
    }
    if (take.length === 0) continue
    appendTo(result, "<system-reminder>\n" + take.join("\n\n") + "\n</system-reminder>")
    if ((Array.isArray(m.content) && m.content.length === 0) || m.content === "") drop.add(m)
    changed = true
  }
  if (!changed) return
  if (drop.size) body.messages = msgs.filter((m) => !drop.has(m))
  if (moved.length && o.log !== false && typeof console !== "undefined") {
    console.log(`channel-midturn: ${moved.length} channel message(s) moved into the results for provider=${p.id} (${moved.join(", ")})`)
  }
  return body
}
