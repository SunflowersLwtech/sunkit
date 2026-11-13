# show-me 工具参考

SKILL.md 只管「图上放什么、正文写多少」。这里是导出、发布、验证时的工具坑——**导出 PNG、发布页面、
跑几何验证、调 archify 之前读对应一节**。

下文 `<SKILL_DIR>` 指本 skill 自己的目录（Claude Code 加载 skill 时会给出 base directory；插件安装后
形如 `~/.claude/plugins/cache/sunkit/show-me/<版本>/skills/show-me`）。脚本一律相对它引用，
别把带版本号的安装路径写死进任何地方。

## A. 委托 diagram-design：调用、皮肤、验证

**调不到 ≠ 没装。** diagram-design 以插件形式装在 Claude Code 里（缓存与 marketplace checkout 都在
`~/.claude/plugins/` 下）。别的运行时（非 Claude Code 的 agent）的 skill 工具会报 not found——那是
「这个运行时没注册它」，不是「机器上没有」。此时手动执行同一个 skill：找 checkout——
`~/.claude/plugins/marketplaces/diagram-design`（无版本号 git checkout，它文档里说的 "repository
checkout" 就是这个）或用户自己的开发仓——读 `skills/diagram-design/SKILL.md` 照做，验证脚本从同一
checkout 的 `scripts/` 跑，效果与调用等价。两个 checkout 先用 `git log -1` 对一下是不是同一个 commit。

**落点要 PNG 进文档、或要可直接编辑的图源时，本机装了 draw.io 的话，draw.io CLI 是更短的链**：
命令行直出 PNG/SVG（导出时带 XML 可再编辑），不走 playwright，CJK 字形栅格化进像素、不依赖读者环境。

它管类型选择、配色、SVG 几何、可访问性契约。你要替它决定的、和它不管的：

- **皮肤门禁**：首次会问要不要定制品牌皮肤。**默认答「用默认」，别拿它去问用户**，
  除非用户自己提过品牌色。
- **四个 dial**（format / size / detail / audience）它只在「导入既有图」那一节讲，
  **新画一张时它不会问你**。新画也要先定，尤其 format——见 C 节。
- **图例没有「预测带/置信区间」原语**。一张图里出现两条颜色不同的区间带时，
  单色块图例会读成「只有一个带」；要给**双色拼接色块 + 括号写明归属**
  （如「预测区间（DRAM / NAND）」，左右半色与序列同序）。端点数值标签压在浅色带上时加遮罩板。
- **验证**：产出后跑两个脚本，路径按加载时公布的 base directory 找，
  **别硬编码带版本号的路径**（`plugins/cache/…/2.6.x/` 会随升级腐烂；
  `plugins/marketplaces/diagram-design/` 是个不带版本号的 git checkout，
  也就是它文档里说的 "repository checkout"）。
  - `skills/diagram-design/scripts/self_check.py` — a11y 契约、单文件安全
  - `scripts/verify-geometry.py` — 标签遮罩会不会被后画的节点盖住

**⚠️ `verify-geometry.py` 的绿有两种是空的，中文图上两种同时成立。**

① **量具看不见你的遮罩**（阈值）。它把「像遮罩板」的判据写死成高度 8–14px
（`MASK_MAX_H = 14.0`；它自己的 ADR 0005 说抬到 18 会误判约 80 个既有 rect，所以留在 14）。
而 CJK 标签按规范要 12px 字，遮罩板做出来是 **16px**——整份中文图里一个遮罩都不在窗口内，
于是它「检查了 0 个对象」并报 0 findings。覆盖掉那个常量再跑：

```python
import importlib.util, sys
spec = importlib.util.spec_from_file_location("vg", "<repo-root>/scripts/verify-geometry.py")
vg = importlib.util.module_from_spec(spec); spec.loader.exec_module(vg)
vg.MASK_MAX_H = 24.0                      # CJK 遮罩板 16px，默认上限 14 看不见
sys.argv = ["verify-geometry", "<你的图.html>"]
sys.exit(vg.main())                       # main() 不收参数，走 argparse 读 sys.argv
```

② **规则对这张图根本不适用**（z-order）。它只拿遮罩比**声明在它之后**的节点；把标签统统
画在最后是正确构造，于是比较次数为零——0 findings 说的是「这条规则不适用」，不是「几何没问题」。

③ **还有三类它从不看，而渲染图上一眼可见。** **贴边文字**：`text-anchor="end"` 锚在画布边距上的行会因字形侧距溢出 1–2px，只有 `getBBox()` 看得见。**遮罩 vs 连接线**：它只比遮罩和节点，不比遮罩和
箭头——多行标签的行距等于遮罩高度时，**每个遮罩顶边正好压住上一条箭头**，行距要 > 遮罩高 + 6px。
**SVG 默认折叠连续空白**：排代码不加 `xml:space="preserve"`，缩进和 diff 的 `+`/`-` 前缀全塌而两个
脚本照样全绿——**那些前缀往往就是整张图的全部语义**。

**所以别把它的绿当成『几何已验证』报出去**；能抓到标签压线、文字溢出、引线穿过自己文字的，
只有渲染出来看的那一眼。

**④ 多图页面整页跑，红也可能是空的。** 两个脚本都把一个文件当一张画布：A 图的坐标轴会被判成「沿 B 图节点的边走」
（实测：五图页整页 2 findings，全是跨图坐标相撞；按 `<svg>…</svg>` 拆成单图文件各跑，均 0 findings）。
所以先拆再跑，别照着跨图的报错去挪几何。`self_check.py` 会把非阻塞字体加载判 FAIL（`<link>` 的 `onload`、`preconnect`），
这是给国内读者保留的有意写法，不是缺陷。

**做阳性对照时，变异必须跨在节点边缘上，且遮罩要声明在节点之前。** 整块落在节点内部的遮罩是合法的徽章芯片、
按设计被跳过，于是变异体照样全绿——长得和量具坏掉一模一样，会把人引去修一个没坏的东西。
**实测：把遮罩追加在文件末尾，变异体照样 0 findings / exit=0**——该脚本只比较「声明在它之后」的节点
（`if node.offset <= mask.offset: continue`），所以对照要把 16px 遮罩插进那个节点的**前一行**并跨它的边，才会红。
双向都验过才算数（变异体 1 finding / exit=1，原图 0 findings / exit=0），且
**判红绿读那行报错正文**——`vg.main(path)` 传错参数抛 TypeError 同样退 1。

**⑤ 图表型产物（折线/柱/带/散点）里它一个对象都检不到，0 findings 是「无适用对象」。**
它只把 `w >= 60 and h >= 40` 的 `<rect>` 当节点（`NODE_MIN_W/H`），数据图表里没有这种 rect，
于是遮罩一个都比不上、比较次数恒为 0。阳性对照要自己插入一个 100×60 的 rect 并声明在遮罩**之后**
才会红（实测：原图 0 findings / exit=0，插入后 1 finding / exit=1）。
图表产物的几何只能靠渲染后量：`getBoundingClientRect()` 映射回 viewBox 坐标查越界
——**别用 `getBBox()`，它不含元素自身的 `transform`**，旋转的 Y 轴标题会被误报越界几十像素。
**模型说「文字压着色带」时先用像素采样裁决**：纸面、带内、注解框内各取一点，
框内像素若等于纸面色（而非带的色）就是误报，别照着改版式。

## B. 导出 PNG 会丢掉图外内容

- ⚠️ **导出 PNG / SVG 只带 `<svg>` 那一块**，页头、summary cards、页脚全部按设计丢掉。
  于是「注解写进 summary cards → 导 PNG 发出去」= 注解凭空消失，而图看起来完好无损。
  **交 PNG 时 summary cards 不是落点**：要么压进那 2 条 callout，要么跟在图外的正文里一起发。

## C. 交付格式、PNG 依赖链、简中字体

| 落点 | 格式 | 代价 / 先验什么 |
|---|---|---|
| 聊天工具 / 笔记工具 / 文档（飞书、Notion、微信等） | **PNG** | 需 playwright + chromium，**先验再承诺**（见下） |
| 分享链接 / 手机看（默认） | **自包含 HTML → FoldRender** | **每次交付**都 `foldrender publish <file> --name <英文短名>`，把 stdout 的 `…/artifacts/<login>/<name>` 链接和本地文件路径一起交给用户。中文标题会被落成 `untitled`，所以 `--name` 一定给。文件保留、路径稳定，重发同一路径更新同一链接。默认私有；要发给别人用 `--share alice,bob` 或 `--link`。CLI 没装 / 没登录按 `foldrender-artifacts` skill 处理；发布失败要报出来，别只交本地文件 |
| 宿主自带的 artifact（Claude Artifact 等） | 平台的 artifact 功能 | **不是交付**：页面拿不回、`foldrender read` 也读不到；show-me 的页面一律走 FoldRender，别用它代替 |
| 要进 Figma / 要可编辑 | SVG | 纯文本抽取，无浏览器依赖 |

**更新同一个页面：** 页面由源文件生成，改一小处就改源文件、重新发布同一个文件路径——
`foldrender publish` 同一路径会更新同一个链接，`foldrender edit <page> --old … --new …` 可以就地改一行；
别另起新文件名（读者手里的链接就旧了）。发布前定一个稳定、好拼写的英文短名文件名，比标题生成的默认名干净。

**手机读者：画布宽 ≤540，`<svg>` 设 `min-width:460px`，图下加一行「← 左右滑动查看 →」。**
只写 `width:100%` 时图跟着缩到屏宽：390 宽的手机上 540 宽的画布只剩 358px（0.66 倍，12px 标签剩约 8px）；
`min-width:460px` 把它钉在 0.85 倍（约 10px），多出的部分靠外层 `<div style="overflow-x:auto">` 横滑——
**提示行不能省**，否则读者以为右边被裁了；**外层不加 `overflow-x:auto` 就变成整页横向滚动**。电脑上同一条
`width:100%` 会把 540 宽的图放大 2.3 倍（1280 宽时 12px 字变 31px），所以 svg 同时要设 `max-width`；
放得下时外层不滚，提示行就是错的，用 `@media` 在宽屏藏掉。
（实测：chrome-headless-shell `--window-size=390,800 --dump-dom`：页面 scrollWidth 390、外层 358/460；去掉 `min-width` 时 svg 358px；去掉外层 `overflow-x` 时页面 scrollWidth 476。）

**PNG 导出是一条独立的依赖链，画得出来不代表导得出去**——断的通常只是其中一环，不是整个能力。
四环各自验：

1. **哪个解释器有 playwright**（常常不是 `python3`，而是某个 conda / venv 里的那个）。
2. **这个 playwright 要的那个 chromium build 在不在**（「没装」和「版本对不上」报的是同一句
   `playwright install`，照字面跑只会再下一份、不解决后者）。
3. **浏览器从哪来**：别假设系统里有 Chrome。能用的兜底是把 `executable_path` 指向 Playwright 缓存里
   现成的 chrome-headless-shell（取版本最大的一个）：

   ```python
   import glob, os
   p.chromium.launch(executable_path=sorted(glob.glob(os.path.expanduser(
       '~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-mac-*/chrome-headless-shell')))[-1])
   ```

   Linux 上同一思路，路径换成 `~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell`。
   想让默认 `launch()` 恢复，就给那个解释器的 playwright 装匹配的 build
   （`python -m playwright install chromium-headless-shell`，要下载数百 MB，先征得用户同意）。
4. **playwright 全断或挂住时，chrome-headless-shell 二进制本身就能出图**，不经过 playwright：
   `chrome-headless-shell --use-mock-keychain --password-store=basic --screenshot=out.png --window-size=<W>,<H> --force-device-scale-factor=2 --hide-scrollbars file://<abs>`
   （**直接跑任何 Chromium 系二进制都要带前两个参数**：不带的话 macOS 上它去读登录钥匙串里的
   「Chromium Safe Storage」，每启动一次就在用户屏幕上弹一次钥匙串授权框；Playwright 的 `launch()`
   自己会加，所以走 Playwright 不弹。Linux 容器里可能还要 `--no-sandbox`。）

它也会不报错地永远挂在 launch/goto 上——截图步骤一律套超时（如 `perl -e 'alarm 90; exec @ARGV' …`），
超时即改走第 4 环，别重试同一条。没有 playwright 也能量几何：往页面副本注入一段脚本，把
`getBoundingClientRect` 的结果写进一个 `<pre>`，再用 `--dump-dom --virtual-time-budget=8000` 取回。
裁剪 / 后处理别假设有 PIL 或 ImageMagick：最稳的是注入 CSS，每次只显示一张图，然后各截一次。
只截 `<svg>`：`page.locator('svg').screenshot(path=...)`（整页截图会把页头页脚一起带进 PNG，而它们按设计
不该在交付里）；导完查一次 `document.fonts` 里 `status==='loaded'` 的条目，要有目标 CJK 字体的各个字重。
判据不是「本机导不了 PNG」，是**逐环验到底哪一环断**；别把 HTML 当 PNG 交。

**简体中文标签的字体默认不随文件走。** diagram-design 的字体链接带了 Noto TC / KR，
**唯独没带 SC**——照默认产出的 HTML / SVG 到了读者那端，用他本地装了什么就是什么。
两条出路，按落点选：

- 把 `Noto Sans SC` / `Noto Serif SC` **补进那个 Google Fonts 链接**（不是只往 `font-family`
  里加本地字体名）。HTML/SVG 于是自己去取字体——代价是**读者那端要能连外网**。
- 交 **PNG**：字形已经栅格化进像素，不依赖读者的字体，也不依赖网络。

补完链接要验它**真的加载了**：读 `document.fonts` 里 `status==='loaded'` 的条目，看 SC 的各个
字重在不在。**别用 `document.fonts.check()`**——它对一个根本不存在的字族同样返回 `true`
（能回退渲染就算通过），而对已加载的字重可能返回 `false`：两个方向都骗你。

**读者在国内（或本机走 TUN 代理）时，Google Fonts 链接要整个删掉，不是补字重。**
`fonts.googleapis.com` 会挂住：渲染时 `page.goto(..., wait_until="load")` 30 秒超时、一个字节都不出
（实测），读者那端是首屏被阻塞；而系统 CJK 字体栈（`PingFang SC` / `微软雅黑` / `Source Han`）
在中文设备上本就齐全。判据是**读者在哪张网上**（要发到微信、发给国内同事 → 系统字体栈），
不是「有没有 SC 字重」。截图与验证脚本一律 `wait_until="domcontentloaded"` + 显式 `wait_for_timeout`，
否则一个挂住的外链就把整条导出链读成「页面打不开」。

CJK 标签 12px 起（8px 的 mono 副标签只放拉丁串）。译完标签重跑一次几何验证——
中文字宽和拉丁完全不同，而那个验证在中文上还有个坑，见 A 节。

## D. archify：电脑上点着看的交互版

**它在哪、为什么看不见。** 本市场（sunkit）里的 `archify@sunkit`：上游 tt-a1i/archify 的 `archify/` 子目录
（git-subdir 稀疏拉取，17 MB），钉在一个读过代码的 commit 上（sha 写在本仓库 `.claude-plugin/marketplace.json`），
装进 `~/.claude/plugins/cache/sunkit/archify/<版本>/`。**装上就是禁用的**（条目里 `defaultEnabled: false`），
所以不进 / 菜单和 skill 列表。收敛入口靠「装上即禁用 + show-me 按路径驱动」，不靠 `skillOverrides`
（官方 skills 文档原话：「Plugin skills are not affected by `skillOverrides`」——它管不到插件的 skill）。

**怎么调。** Bash 工具不保留 shell 状态，每条命令都先 source 环境脚本：

```
. <SKILL_DIR>/scripts/archify-env.sh && node "$ARCHIFY_DIR/bin/archify.mjs" <子命令> …
```

它设三样，缺一样就非 0 退出并说缺什么：
- `ARCHIFY_DIR`：从 Claude 的插件登记表（`installed_plugins.json`）读安装目录（目录名带版本号，别硬编码）。
- `ARCHIFY_CHROME`：`~/.cache/show-me/archify-chrome` 包装脚本，exec Playwright 缓存里版本最大的 chrome-headless-shell 并加
  `--use-mock-keychain --password-store=basic`。archify 自己起浏览器不带这两个参数（`bin/visual-check.mjs` 的 `chromeVisualBrowserArgs`），
  而没有系统 Chrome 的机器上直接指过去，每次启动都会在用户屏幕上弹一次登录钥匙串框。没有 headless shell 时退到 Chrome for Testing。
- `ARCHIFY_UPDATE_CHECK_DISABLED=1`：关掉每次出图向 `tt-a1i.github.io` 查新版本（`bin/delivery-update.mjs`；
  隐私默认：不向上游白送数据）。

然后 `Read "$ARCHIFY_DIR/SKILL.md"` 照它的流程做。它写的 `node bin/archify.mjs …` 一律换成 `node "$ARCHIFY_DIR/bin/archify.mjs" …`；
candidate.json 和产物放当前工作目录（它默认写 `.archify/<图>/`），**别往 `$ARCHIFY_DIR` 里写**——那是插件缓存，升级时整个换掉。

**交付。** 每张图 finalize 四道门全过之后拼页：

```
. <SKILL_DIR>/scripts/archify-env.sh && node <SKILL_DIR>/scripts/archify-page.mjs --out <页.html> --title "<页标题>" <图1.html> [<图2.html> …]
```

出一页（每张图 = 查看器自己导出的整图 SVG + archify 的卡片 + 「全屏打开交互版」）和每张图的 `<页名>-<n>.svg`。然后往
`<!-- show-me: … -->` 处补页首结论和图注（§3 的预算），按 C 节交付。手机读者看整图和卡片，电脑上点按钮进交互版。
要 PNG 进聊天工具就对那张 `.svg` 用 C 节第 4 环截图；但 archify 图里的字只有 7–9 px，缩到手机宽读不了——只给手机看的，回 SKILL §5 换 diagram-design。

**坑**（实测：三张图 16 次 finalize 才全过——按轮次记成本，别低估）：
- **手机上 architecture 不缩放到全图**，右半边被裁。官方原话「This is not a mobile product feature; narrow layouts get containment only.」
  （`references/viewer-runtime.md`）——这就是拼页要带整图 SVG 的理由。
- **画布高度跟着视口高度涨**（同一张 dataflow，视口 700 高时页面 1384、900 高时 1494）：iframe 按内容自适应会越撑越高。交互版只放全屏覆盖层，拼页脚本就是这么做的。
- **节点 `tag` 在默认 100% 缩放下不显示**（175% 才出现，导出的 SVG 里有）——要紧的信息放 `sublabel`。
- **高节点的端口在边的竖直中点**；`via`、`route: straight` 都挪不动端口，validate 报 `clean-flow/endpoint-side-direction`。改几何，
  或按它 SKILL 的「不开第二轮布局」退回上一版过了的 candidate。标签长度一变，走线也会跟着变。
- **sequence 自定 `viewBox` 时几道门互相顶住**（`composition/desktop-readability` 要宽 ≤1085，`composition/viewport-height` 要不纵向滚动）——内容一高就无解，
  用自动尺寸，长注释挪进卡片。
- **CLI 没有导出命令**，只能走查看器。拼页脚本调查看器自己的 `Archify.exportMenu.run('svg')`，经 DevTools 协议驱动、不需要 playwright；
  对照实测：三张图的 SVG 与手点菜单「SVG · 自动」导出的逐字节一致。
- **体积**：单张交互 HTML 约 820 KB（大头是内置的查看器运行时），拼页每张约 1.3 MB；超过 4.5 MB 脚本会提示拆页。

**升级 archify** 不会自动发生（本仓库把 sha 钉在 `.claude-plugin/marketplace.json` 里）。上游动得快，升级步骤：
先读新提交里联网和起进程的代码（`scripts/check-update.mjs`、`bin/delivery-update.mjs`、`bin/visual-check.mjs`、新增的 bin/scripts）
→ 改 `sha` 走 PR → `claude plugin update archify@sunkit` → 用 `archify-env.sh` 跑一次 `doctor` 和一张图的 finalize。

## E. answer-me-with-html（am）：Markdown 草稿 → 单文件讲解页

**它在哪、为什么看不见。** 本市场里的 `answer-me-with-html@sunkit`：上游 QingYunA/answer-me-with-html 的 `skills/` 子目录
（git-subdir 稀疏拉取，1.2 MB），钉在读过代码的 commit（marketplace.json 里的 sha；v0.5.11，MIT），装进
`~/.claude/plugins/cache/sunkit/answer-me-with-html/<版本>/`。只依赖 Node ≥ 20，各平台都能装；
**装上就是禁用的**（`defaultEnabled: false`），所以不进 / 菜单和 skill 列表——它的 skill description 叫模型
「主动、大量使用」，放出来会绕开 show-me 这一个入口。

**怎么调。** 和 archify 一样每条命令先 source 环境脚本：

```
. <SKILL_DIR>/scripts/amwh-env.sh && node "$AMWH_DIR/scripts/am.mjs" render - <<'AM_EOF'
---
title: 标题
---
## A 第一块面板
…（扩展 Markdown，组件语法在它的 SKILL.md §3–4 和 `am help <组件>`）
AM_EOF
```

`amwh-env.sh` 设三样：`AMWH_DIR`（从插件登记表读 skill 目录——`am.mjs` 在 `$AMWH_DIR/scripts/` 下，比 archify 多一层 `answer-me-with-html/`）、`AM_NO_UPDATE_CHECK=1`、`AM_NO_OPEN=1`（理由见下）。然后 `Read "$AMWH_DIR/SKILL.md"` 照它的流程做，它写的 `node "${CLAUDE_SKILL_DIR}/scripts/am.mjs"` 一律换成 `node "$AMWH_DIR/scripts/am.mjs"`。

**写好的页面落点**。默认 am 把页写进 `~/.answer-me-with-html/pages/`（数据目录，`AM_HOME` 可挪）；我们要拿
文件去托管 / 发送，所以 render 时一律带 `-o <当前工作目录>/<名>.html` 把页写在工作目录，**别往 `$AMWH_DIR` 里写**
（插件缓存，升级整个换掉）。要稳定的分享地址，发布时用一个固定、好拼写的英文短名文件名。

**发出去之前过一遍外联**（钉住的 commit 上逐条查过，`scripts/am.mjs`）：

- **更新检查**：`update_check` 配置默认 true，每次 render 后 `spawnUpdateCheck` 后台 fork `am.mjs __update-check`，fetch
  `raw.githubusercontent.com/…/package.json` + `highlights.json`（每天最多一次，结果写 state、页面上冒「有新版本」按钮）。`AM_NO_UPDATE_CHECK=1`（env 脚本已带）或 `CI` 或 `am config set update_check off` 都能关——不关的话每渲染一次向上游发一次请求。
- **自动开浏览器**：`shouldOpen` 默认开，`am render` 写完页就在本机浏览器打开。`AM_NO_OPEN=1`（env 脚本已带）或 `am config set open off` 或每次带 `--no-open` 关掉；有 STE/code 警告的页它本来就不开。交付的是文件或链接，不需要在本机开。
- **主题目录**：`am theme add <名>` 才 fetch 上游站点的主题目录（可用 `AM_CATALOG_URL` 改地址）。本技能不调 `theme add`；页面字体全是内嵌（`@font-face` data URI + `languageFontCss` 系统字体栈），无 Google Fonts 外链。
- **ElevenLabs TTS**：只走 `am video`（配音），`ELEVENLABS_API_KEY`/`AM_TTS_*` 不设就不发；show-me 不做视频。
- **`am serve`**（本地 HTTP 给页面加 live-reload 和 Reply 通道）和 **`am export`**（截图，要浏览器）只有显式调用才用；serve 别替用户起（它 SKILL 也这么说）。export/截图要找 Chrome：顺序 `AM_CHROME` → `CHROME_PATH` → 平台常见路径；没有系统 Chrome 的机器上找不到就把 `AM_CHROME` 指成一个包装脚本——exec Playwright 缓存的 `chrome-headless-shell` 并带 `--use-mock-keychain --password-store=basic`（照抄 `archify-env.sh` 里 `ARCHIFY_CHROME` 的做法，不然每次启动弹一次钥匙串框）。Linux 上 `CHROME_PATHS.linux` 里有 `google-chrome`/`chromium` 就直接用。
- 没有遥测（grep `telemetry|posthog|sentry|beacon|analytics` 零命中）。

**坑与边界**：

- 它产出的是「读一页就懂」的讲解页（sheet/doc 两种模板，flow/state/er/sequence/chart/timeline/annot 等组件自动布局），**不是精修图**：要控每个节点位置、自定义几何的仍回 diagram-design / archify。
- STE 写作检查（`style:` 默认 `80` 只警告，`strict` 出错不出页）：`✗` 行按它的 `Correct example:` 改草稿重渲，最多 2 轮；`patch` 子命令可以只改一页里的一块面板。
- `ask` 组件会在页面上放可点选的「请读者决定」项，配合 Reply 按钮把答案拷回来——给读者的待决项可以用它。
- 代码引用 `src=` 只允许当前工作目录内的文件；页面嵌了私有代码时发出去前告诉读者。
- **升级**不自动发生：上游 main 动得频繁。升级步骤照 archify：读新提交里联网/起进程的代码（重点 `spawnUpdateCheck`、`openPage`/`findChrome`、`am serve`、`am theme add`、`am video` 的 TTS）→ 改 marketplace.json 的 `sha` 走 PR → `claude plugin update answer-me-with-html@sunkit` → 跑一次 `--version` 和一页 render。
