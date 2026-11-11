# show-me 走 archify 时的运行环境。Bash 工具不保留 shell 状态，所以每条调 archify 的命令都带上：
#   . <SKILL_DIR>/scripts/archify-env.sh && node "$ARCHIFY_DIR/bin/archify.mjs" <子命令> …
# （<SKILL_DIR> = Claude Code 加载本 skill 时给出的 base directory；插件安装后形如
#   ~/.claude/plugins/cache/sunkit/show-me/<版本>/skills/show-me，见 references/tooling.md 开头）
# 做三件事，任何一件做不到就返回非 0 并说明原因：
#   ARCHIFY_DIR            archify@sunkit 插件的安装目录（从 Claude 的插件登记表读，目录名带版本号，别硬编码）
#   ARCHIFY_CHROME         一个包装脚本：exec 缓存里的 chrome-headless-shell 并带上 --use-mock-keychain --password-store=basic。
#                          archify 自己启动浏览器时不带这两个参数（bin/visual-check.mjs 的 chromeVisualBrowserArgs），
#                          不带就会去读登录钥匙串，每启动一次在用户屏幕上弹一次钥匙串授权框
#   ARCHIFY_UPDATE_CHECK_DISABLED=1  关掉 archify 每次出图时向上游查新版本（bin/delivery-update.mjs；隐私默认：不向上游白送数据）
# 场景是桌面浏览器里点着看，macOS 为主；Linux 上也探测 ~/.cache/ms-playwright 里的 headless shell。sh / bash / zsh 都能 source。

_sm_cfg="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
ARCHIFY_DIR=$(node -e '
const fs = require("fs")
try {
  const d = JSON.parse(fs.readFileSync(process.argv[1] + "/plugins/installed_plugins.json", "utf8"))
  const e = [].concat((d.plugins || d)["archify@sunkit"] || [])[0]
  if (e && fs.existsSync(e.installPath + "/SKILL.md")) console.log(e.installPath)
} catch {}' "$_sm_cfg")
if [ -z "$ARCHIFY_DIR" ]; then
  echo "archify-env: 本机没装 archify@sunkit（$_sm_cfg/plugins/installed_plugins.json 里没有）。安装：/plugin marketplace add SunflowersLwtech/sunkit 再 /plugin install archify@sunkit（装上默认禁用，属正常，见 SKILL.md §5）；装不上就改走 diagram-design" >&2
  unset _sm_cfg; return 1 2>/dev/null || exit 1
fi

# 版本号最大的那个 headless shell；macOS 没有就退到 Chrome for Testing（同样要那两个参数），再退到 Linux 的缓存
_sm_bin=$(find "$HOME/Library/Caches/ms-playwright" -maxdepth 3 -type f -path '*/chromium_headless_shell-*/chrome-headless-shell-mac-*/chrome-headless-shell' 2>/dev/null | sort | tail -1)
[ -n "$_sm_bin" ] || _sm_bin=$(find "$HOME/Library/Caches/ms-playwright" -maxdepth 6 -type f -path '*/chromium-*/chrome-mac-*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing' 2>/dev/null | sort | tail -1)
[ -n "$_sm_bin" ] || _sm_bin=$(find "$HOME/.cache/ms-playwright" -maxdepth 4 -type f -path '*/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell' 2>/dev/null | sort | tail -1)
if [ -z "$_sm_bin" ]; then
  echo "archify-env: Playwright 缓存（~/Library/Caches/ms-playwright、~/.cache/ms-playwright）里没有 chrome-headless-shell 或 Chrome for Testing；装一份要下载数百 MB，先征得用户同意" >&2
  unset _sm_cfg _sm_bin; return 1 2>/dev/null || exit 1
fi

_sm_dir="$HOME/.cache/show-me"
mkdir -p "$_sm_dir"
# 先写临时文件再改名：几个会话同时 source 时不会读到写了一半的脚本
printf '#!/bin/sh\nexec "%s" --use-mock-keychain --password-store=basic "$@"\n' "$_sm_bin" > "$_sm_dir/archify-chrome.$$"
chmod +x "$_sm_dir/archify-chrome.$$"
mv -f "$_sm_dir/archify-chrome.$$" "$_sm_dir/archify-chrome"

export ARCHIFY_DIR
export ARCHIFY_CHROME="$_sm_dir/archify-chrome"
export ARCHIFY_UPDATE_CHECK_DISABLED=1
unset _sm_cfg _sm_bin _sm_dir
