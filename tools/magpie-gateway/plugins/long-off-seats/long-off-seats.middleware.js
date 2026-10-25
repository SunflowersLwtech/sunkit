// Keeps long conversations off the Claude Team seats, as magpie gateway middleware (onRequest:
// before routing, so the request goes to a group the seats aren't in).
//
// The seats are served by magpie's subscription bridge, a Claude Code process on the server per
// conversation. A conversation that arrives on a seat from elsewhere (it ran on another member,
// another seat ran out, its run was let go) is told whole to a new process, which writes all of it
// to the cache once. On the first night (2026-10-25) ten long sessions moving onto the seats wrote
// up to 835K tokens each and used up two seats' five hours in under 40 minutes; a new session
// starts at about 55K-66K. So a request estimated at `threshold` tokens or more that asks for one of
// the Claude groups is sent to that group's copy without the seats (`map`); shorter ones, new
// sessions among them, keep the seats first. A model named with its provider (claude/…) is left as
// asked.
//
// The estimate walks every string in the body: ASCII at 3.5 characters a token, any other
// character (CJK) a token each, an image 1,600 tokens. It stops once past the threshold.
//
//   {"threshold": 200000, "map": {"claude-opus-5-5": "group/long-opus", …}, "off": false}

const MAP = {
  "claude-opus-5-5": "group/long-opus",
  "claude-fable-5-1": "group/long-opus",
  "claude-sonnet-5-5": "group/long-sonnet",
  "claude-haiku-5-5": "group/long-haiku",
}
const IMAGE = 1600

export function estimate(body, stop = Infinity) {
  let ascii = 0
  let other = 0
  let images = 0
  const tokens = () => ascii / 3.5 + other + images * IMAGE
  const walk = (v, key, parent) => {
    if (tokens() >= stop) return
    if (typeof v === "string") {
      if (key === "data" && parent && (parent.type === "base64" || parent.media_type)) { images++; return }
      if (v.startsWith("data:image/")) { images++; return }
      const wide = v.replace(/[\x00-\x7f]+/g, "").length
      ascii += v.length - wide
      other += wide
      return
    }
    if (Array.isArray(v)) { for (const x of v) walk(x, key, parent); return }
    if (v && typeof v === "object") for (const k of Object.keys(v)) { if (k !== "model") walk(v[k], k, v) }
  }
  walk(body)
  return Math.round(tokens())
}

export function onRequest(body, ctx) {
  const o = (ctx && ctx.options) || {}
  if (o.off || !body || typeof body.model !== "string") return
  const map = o.map && typeof o.map === "object" ? o.map : MAP
  const asked = body.model.trim().replace(/\[1m\]$/i, "").replace(/^group\//, "")
  const to = map[asked]
  if (!to) return
  const threshold = Number(o.threshold) > 0 ? Number(o.threshold) : 200000
  if (estimate(body, threshold) < threshold) return
  body.model = to
  return body
}
