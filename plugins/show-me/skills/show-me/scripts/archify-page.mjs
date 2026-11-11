// show-me 的 archify 交付页：把 archify 产出的一张或几张交互 HTML 拼成一页——手机上读整图和卡片，电脑上点开交互版。
//
//   . <SKILL_DIR>/scripts/archify-env.sh && \
//     node <SKILL_DIR>/scripts/archify-page.mjs --out <page.html> --title "<页标题>" <a.html> [<b.html> …]
//   （<SKILL_DIR> = Claude Code 加载本 skill 时给出的 base directory，见 references/tooling.md 开头）
//
// 每张图一节：archify 里的图名；查看器自己导出的整图 SVG（Archify.exportMenu.run('svg')，即菜单里的「SVG · 自动」，随宿主深浅色）；
// archify 的卡片原样搬过来（连同它的卡片样式和深浅两套颜色变量）；「全屏打开交互版」按钮（整份交互 HTML 以 base64 内嵌，点开放进全屏 iframe）。
// 每张图的 SVG 另存一份在 --out 旁边（<页名>-<序号>.svg），要发 PNG、进文档时用。
// 页首结论和每张图的图注按 SKILL.md §3 自己补进生成的 HTML（找 <!-- show-me: … --> 注释）；本脚本只管拼装。
// 浏览器用 ARCHIFY_CHROME（archify-env.sh 生成的包装脚本，带 --use-mock-keychain --password-store=basic），经 Chrome DevTools 协议驱动，
// 只用 Node 自带的 WebSocket（Node ≥ 22），不需要 playwright。
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const argv = process.argv.slice(2)
const take = (k) => { const i = argv.indexOf(k); if (i < 0) return null; const v = argv[i + 1]; argv.splice(i, 2); return v }
const out = take('--out'), title = take('--title')
const inputs = argv.map((f) => path.resolve(f))
const die = (m) => { console.error(`archify-page: ${m}`); process.exit(1) }
if (!out || !title || !inputs.length) die('用法: --out <page.html> --title "<页标题>" <archify.html>…')
for (const f of inputs) if (!fs.existsSync(f)) die(`找不到 ${f}`)
const chrome = process.env.ARCHIFY_CHROME
if (!chrome || !fs.existsSync(chrome)) die('ARCHIFY_CHROME 没设或不存在：先 source 本技能 scripts/ 目录下的 archify-env.sh')
if (typeof WebSocket !== 'function') die(`Node ${process.version} 没有内置 WebSocket，要 Node ≥ 22`)

// ---------- 最小的 CDP 客户端 ----------
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'archify-page-'))
const proc = spawn(chrome, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--no-first-run',
  '--no-default-browser-check', '--disable-gpu', '--hide-scrollbars', '--disable-background-networking', 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'] })
const cleanup = () => { try { proc.kill('SIGKILL') } catch {} ; fs.rmSync(profile, { recursive: true, force: true }) }
process.on('exit', cleanup)
const wsUrl = await new Promise((resolve, reject) => {
  let buf = ''
  const t = setTimeout(() => reject(new Error('浏览器 20 秒内没报 DevTools 地址')), 20000)
  proc.stderr.on('data', (d) => { buf += d; const m = buf.match(/DevTools listening on (ws:\/\/\S+)/); if (m) { clearTimeout(t); resolve(m[1]) } })
  proc.on('exit', (c) => { clearTimeout(t); reject(new Error(`浏览器启动即退出（code ${c}）：${buf.slice(-400)}`)) })
}).catch((e) => die(e.message))
const ws = new WebSocket(wsUrl)
await new Promise((r, j) => { ws.onopen = r; ws.onerror = () => j(new Error('连不上 DevTools')) }).catch((e) => die(e.message))
let seq = 0
const pending = new Map()
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.reject(new Error(`${p.method}: ${m.error.message}`)) : p.resolve(m.result) }
}
const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
  const id = ++seq
  pending.set(id, { resolve, reject, method })
  ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }))
})
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
async function evaluate(sid, expression) {
  const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true }, sid)
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text)
  return r.result.value
}
async function open(file, scheme) {
  const { targetId } = await send('Target.createTarget', { url: 'about:blank' })
  const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true })
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false }, sessionId)
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: scheme }] }, sessionId)
  await send('Page.navigate', { url: pathToFileURL(file).href }, sessionId)
  for (let i = 0; i < 100; i++) {
    if (await evaluate(sessionId, `document.readyState === 'complete' && !!(window.Archify && Archify.exportMenu)`).catch(() => false)) break
    if (i === 99) throw new Error(`${path.basename(file)} 20 秒内没加载出 archify 查看器（不是 archify 产出的 HTML？）`)
    await sleep(200)
  }
  await sleep(1200) // 查看器加载完还要排一次版
  return { targetId, sessionId }
}

// 卡片样式只取 .card* 规则，再取它们用到的颜色变量（深浅各一套）
const CARD_STYLE = `(() => {
  const rules = []
  for (const s of document.styleSheets) { try { for (const r of s.cssRules) if (r.selectorText && /^\\s*\\.card/.test(r.selectorText) && !/html\\[/.test(r.selectorText)) rules.push(r.cssText) } catch (e) {} }
  const cs = getComputedStyle(document.documentElement), vars = {}
  for (const v of new Set(rules.join('\\n').match(/--[a-z0-9-]+/g) || [])) vars[v] = cs.getPropertyValue(v).trim()
  return { css: rules.join('\\n'), vars }
})()`
const EXPORT = `(async () => {
  let blob = null
  const orig = URL.createObjectURL, click = HTMLAnchorElement.prototype.click
  URL.createObjectURL = (b) => { if (b instanceof Blob && /svg/.test(b.type)) blob = b; return orig.call(URL, b) }
  HTMLAnchorElement.prototype.click = function () {}
  try { await Archify.exportMenu.run('svg') } finally { URL.createObjectURL = orig; HTMLAnchorElement.prototype.click = click }
  const cards = document.querySelector('.cards')
  return { svg: blob ? await blob.text() : null, name: (document.querySelector('h1') || {}).textContent || document.title, cards: cards ? cards.outerHTML : '' }
})()`

const sections = []
let style = null
for (const file of inputs) {
  const light = await open(file, 'light')
  const got = await evaluate(light.sessionId, EXPORT)
  if (!got.svg) die(`${path.basename(file)}：查看器没交出 SVG`)
  if (!style) {
    style = await evaluate(light.sessionId, CARD_STYLE)
    const dark = await open(file, 'dark')
    style.dark = (await evaluate(dark.sessionId, CARD_STYLE)).vars
    await send('Target.closeTarget', { targetId: dark.targetId })
  }
  await send('Target.closeTarget', { targetId: light.targetId })
  sections.push({ ...got, html: fs.readFileSync(file) })
}
ws.close()

// ---------- 拼页 ----------
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c])
const vars = (o) => Object.entries(o).filter(([, v]) => v).map(([k, v]) => `${k}:${v};`).join(' ')
const stem = path.join(path.dirname(path.resolve(out)), path.basename(out, path.extname(out)))
const body = sections.map((s, i) => {
  fs.writeFileSync(`${stem}-${i + 1}.svg`, s.svg)
  const w = (s.svg.match(/<svg[^>]*\swidth="(\d+(?:\.\d+)?)"/) || [])[1]
  return `
<section id="d${i + 1}">
  <h2>${esc(s.name.trim())}</h2>
  <!-- show-me: 图注 1 句（这张图回答什么）+ ≤3 句图上画不出来的东西 -->
  <figure class="static"><img${w ? ` style="max-width:${w}px"` : ''} src="data:image/svg+xml;base64,${Buffer.from(s.svg).toString('base64')}" alt="${esc(s.name.trim())}（整图）"></figure>
  <button type="button" class="open" data-src="src-d${i + 1}">全屏打开交互版：可拖动、缩放、点节点看上下游</button>
  ${s.cards}
  <script type="text/plain" id="src-d${i + 1}">${s.html.toString('base64')}</script>
</section>`
}).join('\n')
const page = `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
<style>
:root { --bg:#f4f6f8; --fg:#16202a; --muted:#5b6774; --line:#d9dee4; ${vars(style.vars)} }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#0b1020; --fg:#e6ebf2; --muted:#9aa6b4; --line:#263042; ${vars(style.dark)} } }
:root[data-theme="dark"] { --bg:#0b1020; --fg:#e6ebf2; --muted:#9aa6b4; --line:#263042; ${vars(style.dark)} }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif; }
main { max-width:1240px; margin:0 auto; padding:24px 16px 48px; }
header h1 { font-size:24px; margin:0 0 4px; }
header p, .lead { margin:0 0 12px; color:var(--muted); font-size:15px; }
section { margin-top:32px; padding-top:16px; border-top:1px solid var(--line); }
h2 { font-size:19px; margin:0 0 4px; }
.static { margin:0 0 12px; }
.static img { display:block; width:100%; height:auto; margin:0 auto; border:1px solid var(--line); border-radius:10px; }
.open { font:inherit; font-size:14px; padding:8px 14px; border-radius:8px; border:1px solid var(--line); background:var(--panel, transparent); color:var(--fg); cursor:pointer; }
.cards h3, .cards ul { margin:0; padding:0; }
/* archify 的卡片样式，从它渲染出的样式表原样取来 */
${style.css}
#overlay { position:fixed; inset:0; z-index:10; background:var(--bg); display:none; }
#overlay.on { display:block; }
#overlay iframe { width:100%; height:100%; border:0; }
#overlay .close { position:fixed; z-index:11; left:12px; bottom:12px; font:inherit; font-size:14px; padding:8px 14px; border-radius:8px; border:1px solid var(--line); background:var(--fg); color:var(--bg); }
</style>
</head>
<body>
<main>
<header>
  <h1>${esc(title)}</h1>
  <!-- show-me: 页首结论 ≤3 句，每句一个判断 -->
</header>
${body}
</main>
<div id="overlay"><iframe title="交互版"></iframe><button type="button" class="close">关闭交互版</button></div>
<script>
const ov = document.getElementById('overlay'), fr = ov.querySelector('iframe')
document.querySelectorAll('.open').forEach((b) => b.addEventListener('click', () => {
  const b64 = document.getElementById(b.dataset.src).textContent
  fr.srcdoc = new TextDecoder().decode(Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)))
  ov.classList.add('on'); document.body.style.overflow = 'hidden'
}))
ov.querySelector('.close').addEventListener('click', () => { ov.classList.remove('on'); fr.srcdoc = ''; document.body.style.overflow = '' })
</script>
</body>
</html>
`
fs.writeFileSync(out, page)
const mb = Buffer.byteLength(page) / 1048576
console.log(`${out}  ${mb.toFixed(2)} MB，${sections.length} 张图；SVG：${sections.map((_, i) => `${path.basename(stem)}-${i + 1}.svg`).join(' ')}`)
if (mb > 4.5) console.log(`⚠ 超过 4.5 MB：多数静态托管单页上限 5 MB 左右，拆成几页（每张交互图约 1.1 MB）`)
process.exit(0)
