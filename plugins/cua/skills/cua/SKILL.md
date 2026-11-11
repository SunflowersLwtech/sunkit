---
name: cua
description: >-
  Single entry point for operating any GUI: desktop windows, browsers, Electron
  apps, dialogs, iOS/Android simulators, physical and cloud phones. Routes each
  request to the right detail skill and gets out of the way. Fires on
  「打开网页」「点一下」「截个图」「帮我操作」「填表」「手机上跑一下」「自动化浏览器」
  「控制电脑」「用某个 profile」「在我已登录的账号里」「装个 APK」「看 logcat」
  「模拟器上验证一下」「adb 连不上」「设备被别人占着吗」「双指缩放」「手机上输中文」,
  "open the site", "click", "fill the form", "log in to the site", "use my
  logged-in account", "take a screenshot", "drive the app", "automate the
  browser", browser QA or dogfooding, driving VS Code/Slack/Figma desktop UIs,
  simulator evidence for an app change, simulator or real-device taps, pinch
  zoom, "WebDriverAgent won't start", Apple Events or background input without
  stealing focus. Not for calling an API or reading a URL's raw response
  (「查一下这个接口返回什么」→ curl/xh), and not for terminal/worktree/agent
  management.
---

# CUA — 统一入口

唯一职责：把「操作界面」的请求指派给正确的成员 skill，然后退出。每条规则的细节、
失效模式、账号处理都在成员 skill 里，别在路由层重学一遍。

**第 0 步：先查有没有官方 API。** 任务落在某个外部服务上（读信或收验证码、查用量、
建 key、看审核状态……）时，先找官方 API / CLI / SDK 或现成的已授权接口，能用就
直接调。GUI 是最后手段，只有确实只能 GUI 的那一步才进下表。

## 路由表

| 任务形态 | 用哪个 |
|---|---|
| 公开网页取数据 | 不进 GUI——先 curl / xh 等 HTTP 手段；被反爬挡或必须 JS 渲染再回来 |
| **默认**：打开网页、填表、截图、QA、已登录的站点、多账号并行 | 浏览器自动化 CLI（下方「第三方工具」：agent-browser 或 browser-harness） |
| Electron 应用（VS Code、Slack、Figma、Notion 等 Chromium 内壳）里的页面 | 同上，给 app 带 `--remote-debugging-port` 重启（见「通用边界」） |
| 应用弹出的原生打开/保存面板、浏览器外的窗口与对话框、OS 级输入、不能抢焦点 / PID 定向输入 / Apple Events | `macos-harness`（本插件带文档，CLI 见下方第三方表） |
| 后台输入但要驱动回读验证（effect confirmed / refused）、跨 OS、VM/沙箱 fleet、轨迹录制 | `cua-driver`（第三方，见下） |
| 桌面应用走系统无障碍树，macOS / Windows / Linux 一套流程 | `agent-desktop`（第三方，见下） |
| **手机相关全部**：安卓模拟器 / adb、iOS 模拟器、真机、云真机、投屏、按元素点击、中文输入、双指缩放、截图录屏、装包与日志、深链、移动端 QA | `phone-use`（本插件） |

macOS 桌面 App 里怎么选：页面内容在 Chromium 内核里 → CDP；窗口、菜单、原生面板、
跨 app → `macos-harness`（无障碍 + Apple Events）；要驱动回读证据或轨迹录制 →
`cua-driver`。

## 第三方工具（本插件不带，按上游安装）

| 工具 | 上游 / 许可 | 安装与接入 |
|---|---|---|
| agent-browser | [vercel-labs/agent-browser](https://github.com/vercel-labs/agent-browser)，Apache-2.0 | `npm i -g agent-browser && agent-browser install`；用法用 `agent-browser skills get core` 从 CLI 现取（内容随安装版本走，不会过期） |
| browser-harness | [browser-use/browser-harness](https://github.com/browser-use/browser-harness)，MIT | 按上游 install.md 安装；它附在用户自己跑着的 Chrome/Chromium 上复用已登录会话，不另起实例、不克隆 profile |
| macos-harness | [browser-use/macos-harness](https://github.com/browser-use/macos-harness)，MIT | `uv tool install --python 3.12 --from git+https://github.com/browser-use/macos-harness@v0.1.2 macos-harness`（钉在 v0.1.x：上游 v0.2.0 重写了接口，六动词只在 v0.1.x 有）；本插件带的 `macos-harness` skill 是它的说明文档加本地新写的章节，出处见该目录的 UPSTREAM.md 与 LICENSE |
| agent-desktop | [vercel-labs/agent-desktop](https://github.com/vercel-labs/agent-desktop)，Apache-2.0 | 按上游 README 安装；`agent-desktop skills get platform` 取当前平台的用法 |
| cua-driver | [trycua/cua](https://github.com/trycua/cua)，MIT | 按上游文档装 CLI 或 MCP server；随发行版分发的 skill 包不要手改 |

## 通用边界

- 装好本插件后，成员 skill（macos-harness、phone-use）可以直接用 Skill 工具调；
  本文件只负责在不确定该用哪个时指派。
- 宿主自带的 computer-use / 浏览器 MCP（如 Claude desktop、Claude in Chrome）按
  其自身描述直接生效，不经过本表。
- **给 Electron 应用加调试端口要重启应用**，会打断正在用的人：先说明再动手。隐藏
  窗口启动会让「启动代码里自己显示窗口」的应用卡在 `visibilityState=hidden`、rAF
  不跑，之后所有界面操作都超时——出现「命令成功了但页面不动」先查这个。应用弹出的
  原生打开/保存面板 CDP 看不见（工具可能照样报成功），交给 `macos-harness` 的无障碍
  路径。
- 有的应用策略性拒绝调试端口（如飞书/Lark 桌面版把 `RemoteDebuggingAllowed` 关了），
  CDP 根本连不上：优先找官方 API / CLI；只读看界面用无障碍快照，第一次快照没有网页
  内容就隔两秒再取。
- **远控窗口（RustDesk / AnyDesk / VNC）对 GUI 自动化只是一块像素**：无障碍树只有
  一个容器、坐标在全屏↔窗口切换后失效、会话本身会掉。目标机器若能经 SSH / API 原生
  到达，优先走那条路，别盲点远程像素。
- **判断「人是否正在用这台机器」不能只看空闲时间**：模拟输入事件和远控输入都会把
  HIDIdleTime 清零，读起来和真人在操作一样。看电源管理日志里 UserIsActive 记录的
  来源进程；前台是谁用窗口服务查前台进程的 bundle 路径——AppleScript 报的进程名对
  Electron 应用一律是 `Electron`，分不出是谁。要断言「全程没抢前台」就连续采样，
  只记变化：前后各取一次会漏掉瞬时抢占，也会被别人的操作骗。前台动作会移动真实鼠标
  指针且不还原，下这种手之前先过这一关。
- 截图 / 导出 PNG 的脚本用 Playwright 时，`channel="chrome"` 依赖本机装了
  Chrome；没有就用 `executable_path` 指向 Playwright 自带的 headless 浏览器。
