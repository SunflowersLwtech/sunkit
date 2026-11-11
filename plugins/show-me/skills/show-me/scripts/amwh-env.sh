# show-me 走 answer-me-with-html 时的运行环境。Bash 工具不保留 shell 状态，所以每条调 am 的命令都带上：
#   . <SKILL_DIR>/scripts/amwh-env.sh && node "$AMWH_DIR/scripts/am.mjs" <子命令> …
# （<SKILL_DIR> = Claude Code 加载本 skill 时给出的 base directory；插件安装后形如
#   ~/.claude/plugins/cache/sunkit/show-me/<版本>/skills/show-me，见 references/tooling.md 开头）
# 设三样，缺一样就返回非 0 并说明原因：
#   AMWH_DIR              answer-me-with-html@sunkit 插件里 skill 的目录（从 Claude 的插件登记表读，目录名带版本号，别硬编码）
#   AM_NO_UPDATE_CHECK=1  关掉 am 每天一次向 GitHub raw 查新版本的后台进程（UPDATE.url / highlightsUrl；隐私默认：别让每次渲染都变成一次外呼）
#   AM_NO_OPEN=1          关掉 am render 写完页面后自动开浏览器（shouldOpen：交付的是文件或链接，不在本机开）
# am 自己找浏览器的顺序是 AM_CHROME → CHROME_PATHS 各平台常见路径；没有系统 Chrome 的机器上它找不到就报错，
# 那时把 AM_CHROME 指到 Playwright 缓存的 chrome-headless-shell，并在包装脚本里补 --use-mock-keychain --password-store=basic
# （archify-env.sh 里 ARCHIFY_CHROME 的做法可以照抄）。截图/导出才需要浏览器，纯 render 不需要。
# 跨平台：mac / Linux / Windows 都只依赖 Node >= 20。sh / bash / zsh 都能 source。

_sm_cfg="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
AMWH_DIR=$(node -e '
const fs = require("fs"), path = require("path")
try {
  const d = JSON.parse(fs.readFileSync(process.argv[1] + "/plugins/installed_plugins.json", "utf8"))
  const e = [].concat((d.plugins || d)["answer-me-with-html@sunkit"] || [])[0]
  if (!e) process.exit(0)
  // 插件根是 git-subdir 拉的 upstream skills/：SKILL.md 在 <root>/answer-me-with-html/ 下
  for (const c of [e.installPath + "/answer-me-with-html", e.installPath]) {
    if (fs.existsSync(c + "/scripts/am.mjs")) { console.log(c); break }
  }
} catch {}' "$_sm_cfg")
if [ -z "$AMWH_DIR" ]; then
  echo "amwh-env: 本机没装 answer-me-with-html@sunkit（$_sm_cfg/plugins/installed_plugins.json 里没有，或装好的目录里没有 scripts/am.mjs）。安装：/plugin marketplace add SunflowersLwtech/sunkit 再 /plugin install answer-me-with-html@sunkit（装上默认禁用，属正常，见 SKILL.md §5）；装不上就改走 diagram-design 或手写 SVG" >&2
  unset _sm_cfg; return 1 2>/dev/null || exit 1
fi

export AMWH_DIR
export AM_NO_UPDATE_CHECK=1
export AM_NO_OPEN=1
unset _sm_cfg
