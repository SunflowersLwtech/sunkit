---
name: obsidian-wiki
description: >-
  Use the user's Obsidian vault as the agent's long-term memory: recall what is
  already known BEFORE answering, write session conclusions back as indexed
  notes, and keep the wiki consistent across sessions. Fires on
  「我之前记过吗」「vault 里有什么」「我们当初怎么决定的」, on any question the
  user's own notes would answer (past decisions, measured results, contacts,
  project/infra state), including requests whose shape is pure external
  research — 选型、对比供应商或模型、「X 和 Y 哪个好」、'compare A, B, C' — where
  the deciding evidence may be a measurement already in the vault, on 'save
  this', 'write this down', 'record what we learned', and on to-do work —
  「加个待办」「记一条 todo」「把这条勾掉」「这个做完了」「清理已完成的任务」
  「我还有什么没做」, 'add a task', 'mark it done', 'mark … done', 'what is
  still open', and on anything about the vault living on several devices.
  Works on a plain folder of markdown with ordinary file tools; the official
  obsidian CLI is an optional accelerator.
metadata:
  role: knowledge-base
---

# obsidian-wiki

A vault is a plain folder of markdown. Obsidian is one client on it; you are
the other. The point of this skill: the folder outlives every session, so
**before answering, recall; after concluding, write back** — under conventions
that keep a machine-maintained wiki from rotting into a pile of files.

## 选型/对比类问题尤其先召回

外部评测只能回答「市面上有什么」，判据常是用户已实测过的那一条：客户端的可用性、供应商的
可靠性、模型的成本——vault 里大概率有一条**针对同一对象**的实测（某客户端不按配置走、某家
API 的额度实测耗尽、某机型跑不起来）。**只做外部检索就开始答，会把已测过的东西当未知**：
结论可能整体正确，却把实测里已判死的候选重新标成「待观察」。凡 vault 里测过的项，外发
对比结论要带上那条实测。

## Setup（每会话一次）

**找到 vault。** macOS 读 `~/Library/Application Support/obsidian/obsidian.json`、
Windows 读 `%APPDATA%\obsidian\obsidian.json`（JSON 里 vault id → path），或直接问用户。
拿到后设一个变量，全篇用绝路径：

```bash
VAULT=/path/to/vault   # resolve once; never work from a guessed path
```

**工具就是普通文件操作**：Read/Write/Edit + glob/grep，面对带 YAML frontmatter 的
markdown。官方 `obsidian` CLI（桌面 App 的 IPC 客户端，部分版本自带；`references/obsidian-cli.md`）
是可选加速器——链接改写的 rename、`search`/`outline`/`backlinks`/`orphans`/`unresolved`
这类结构查询、`eval` 逃生舱。没装或 App 没开时，每个用途都有普通文件的退路，见那份参考。

## Recall — always before answering, in tiers

先说禁区。**绝不 `cat`/`rg` 输出整棵树**。便宜的原因是 token——几千条笔记按 10M token 量级算；
贵的原因是**vault 这种个人笔记里很可能有存凭据的文件**，带行输出的 `rg`/`grep` 会在关键词恰好
也出现在凭据文件里时，把值原样打进会话。要 grep 就 **`-l` 只出文件名**，或
`--glob` 排掉存敏感内容的目录。ignore 文件不是护栏：命令行传的 `--glob` 会盖过它。

| 目标 | 普通文件做法 | 预算 |
|---|---|---|
| **真实工作从这里开始**：给定任务，召回相关笔记 | 项目索引先行：`grep -i -l <对象名> <索引目录>/*/索引文件`——索引行是收尾时写的，带结论和出处，比全文检索先命中；没有索引再 `grep -r -l -i <terms> "$VAULT" --include='*.md'`，挑中后只读那几篇 | 命中后逐篇 ≤6k |
| 摸结构 | 每目录一张小抄（条数 + 一句话），自己 `find` + 标题扫描生成；`obsidian` CLI 的 `files`/`vault` 也能给 | ≤2k |
| 单篇笔记的骨架 | `rg -n '^#{1,6} '` 该文件（CLI：`outline`） | ≤1.4k |
| 只读那一节 | 按 Read 工具的 offset/limit 读到下一标题为止 | ≤6k |
| 图谱 | 入链：`grep -rl "\[\[<name>\]\]" "$VAULT"`；孤儿与断链见收尾一节 | — |

直接 `cat` 一整篇去找一个 200 token 的答案，是本 skill 最大的浪费。多级召回的每一层都该
窄化范围，而不是放大读取。

**别的设备刚写的笔记可能还不在本机。**vault 一旦多机同步，本机永远落后最后一轮（几分钟到
更久，「搜不到」不等于「没写过」——判断方法见 `references/sync.md`），怀疑时把这条讲出来，
不要拿「本机没有」当「用户的 vault 里没有」。

## Writing

```bash
mkdir -p "$VAULT/<主题文件夹>"
cat > "$VAULT/<主题文件夹>/<Note>.md" <<'EOF'
---
type: note
created: 2026-08-24
tags: [example]
status: draft
---

...body with [[wikilinks]]...
EOF
```

- **写完从磁盘读回**，别信命令的退出码或回显。整篇用 Write/heredoc 建好，改动用 Edit，
  追加后读回末尾。
- **shell 会吃 markdown 的字符**：双引号参数里反引号被当命令替换、`$` 被展开，那些词会从
  笔记里消失而命令照样成功。正文一律走 heredoc（引号包住定界符 `<<'EOF'`）、单独的正文
  文件或 Write/Edit 工具，不走内联双引号串。
- **追加语义**：CLI 的 `append` 会先补一个空行，会把表格和列表从中间截断。往已有表格/列表
  加一行，用 Edit 精准落位（或 CLI 的 raw 模式，如果有）。
- **文件名要求**：全局唯一（`[[wikilink]]` 按文件名而不是路径解析）、避开最严格端不接受的
  字符（`\ : * ? " < > |` 中带 `\` 与 `:` 最常见踩雷，Android 上这些文件**无声消失**）；改名
  用 CLI 的 `rename`（会重写入站链接）或自己把入站 `[[链接]]` 全部改掉——裸 `mv` 会留下一张断链
  图。检测命令见 `references/obsidian-cli.md`。

### 收尾写什么：指针 + 索引行

会话结束时把结论写回 vault，有两种形状，按载荷选，不按口味选：

1. **主题笔记 + 指针**（发现会长出正文、证据、给人看的材料）：完整笔记放主题文件夹；
   同时在**该项目的索引/记忆文件**里追加一行指针。索引是平铺枚举，按项目一个文件：
   `- [[note-slug]] — <一句话结论>`。**只放主题文件夹里不留指针的结论，未来任何会话都看不见**
   ——未来的召回从索引走。
2. **独立记忆**（一条短命的操作性规则/事实，两三句放得下）：直接写成一篇 2–6 句话的笔记
   （结论 + 该拿它做什么 + 链接），再登记索引行。

两条铁律：

- **索引行的 hook 必须自带结论**，不是主题词。「图标方案定稿」是主题词；
  「图标用 SVG sprite，嵌位图方案因审核风险放弃」才是 hook。
- **端到端验证**：拿「未来会话会怎么问」问一遍自己的召回路径，看到的是**结论文本**而不只是
  文件名——这是唯一能测到未来会话真实体验的检查。

### 什么不写回

- 转瞬即逝的过程状态（今天几点做到哪），除非它是交接材料；
- **凭据**：密钥、token、口令进真正的密钥管理，不进明文 wiki——多机同步会把它们复制到
  每台设备，replication 是不可撤回的；
- 复述一句索引行已经说完的东西；索引行够了。
- 临时草稿、排练文本。

## Conventions（工具决定不了、你得决定的）

1. **哪个主题文件夹**。文件夹在第二条笔记出现时才配存在；在那之前用最接近的现有文件夹。
   组织按主题，不按类型（没有「notes 文件夹」和「scratch 文件夹」这种分类）。
2. **`research` vs `reference` vs `note`**。移动领域的快照（综述、对比、价格表）带日期后缀，
   是 `research`；某天做了某事的记录是 `note`，日期不自动把它变成 research。
3. **`status: verified` 表示本会话查过**——跑过命令、读过一手来源。搜索结果只是 `draft`。
   一篇不区分「实测」与「转述」的 wiki，不如没有 wiki。要点：
   - 一篇笔记一个等级，混装取最低——但笔记自己明确标注「未验证/待核实」的条目不拉低等级，
     只有**没标注**的声明才拉低；
   - 用户报告而你没有复跑的实测保持 `draft`，并把升级条件写进笔记（「CI 里跑通一次后升
     verified」），下个会话才知道缺什么；
   - 排序建立在厂商文档上的综述，即使核对了其中六条也是 `draft`——把核实过的部分拆成独立
     笔记再链接，否则文件级的 verified 会替没验证的大多数洗白。
4. **从 MOC 链进新笔记**。索引行+指针给了新笔记一个入链，但主题的总览页（MOC）还缺；
   孤儿检查在收尾做。`[[wikilink]]` 按 slug 存放时会解析失败，看起来又像一个故意的前向链接
   ——要分辨。
5. **外发结论的每个数字都能指回一篇笔记**；没披露的写「未披露」，不许为了行文顺去推算。

## To-dos

待办是 ` - [ ]` 行，写在**做这件事时要打开的那篇笔记里**——绝不集中进一个巨型 todo 文件
（整文件写入的并发会互相覆盖），也不写进仅供查看的视图页。

- 加之前先查已有待办：新的一条常常改变已有的那条——同一件事（改它）、取代它（关掉它）、
  和它矛盾（「周五前停掉容器」挨着「每周检查容器」——把这对摆出来，而不是都登记）。
- **done 意味着本会话验证过**，与 `status: verified` 同一条纪律。
- **有真日期才写日期**：编造的 due date 在过期视图里是假警报。
- 循环任务保持简单格式（如 `🔁 every week`），并确认你的阅读方确实解析它——不同工具对
  勾选行为的处理不同（有的只翻标记，不写完成日期、不推进下一次），勾完读回那一行。

## Multi-device sync（一票否决的几条）

vault 同步到多台设备后，大部分「工具坏了」其实是同步的时序。**写≠同步**——写入成功只说明
落了本机盘。几条通用教训（完整展开见 `references/sync.md`）：

1. 整文件、「保留较新版本」的冲突解法会**无声吃掉并发写**：两个会话/两台设备写同一份共享
   文件（索引页、任务页），后到者整份覆盖先到者。共享文件的写入要串行化（单一入口或锁），
   覆盖嫌疑发生后隔一轮再核对。
2. 状态栏说同步完成不算数，**用内容核对**（远程 etag/md5 对本地），时间戳对得上而内容不同
   的情形真实存在。
3. 每台设备同步的是**子集**（`.`/`_` 开头常被排除，过滤规则各端不同），而 `ls`、编辑器和本地
   检查看到的都是完整树——存在但没被同步的文件，一切本地检查都不会报错。工具的持久状态
   放非点路径或密钥管理，不放点文件。
4. 删除是最危险的方向：一台积压很久的旧设备上线，「清空重来」会把全库删穿（同步插件会把
   删除也当变更传播）。旧设备先设为只下载；批量删除前逐 key 核对。
5. 首次上设备**不要靠拷文件预填**——mtime 全变成「现在」会让同步工具把每个文件判成冲突，
   触发其「改动比例过高保护」**无声中止**；让同步工具自己做第一次下载。

## Session close-out

加过或重排过页面的会话，收尾跑一遍（CLI 有就用，没有就用 grep 退路）：

```bash
# 该写没写的：被 [[链接]] 指着但还不存在的页（CLI: unresolved）
grep -rhoE '\[\[[^]|#]+' "$VAULT" --include='*.md' | sort -u   # 对照磁盘文件名筛
# 该被链没被链的：没有任何入链的 .md（CLI: orphans）
# 索引/磁盘脱同步检查
find "$VAULT" -name '*.md' -not -path '*/.obsidian/*' | wc -l  # 对比 CLI `vault` 的计数
```

并把结果链进或写进对应索引。跳过这一步，wiki 就在往「一堆文件」退化的路上。

## 常见坑（看起来像坏了、其实不是）

| 看起来像 | 其实是 |
|---|---|
| 脚本「成功」但笔记没变化 | 追加/写入被 shell 吃了字符，或写进了另一个同名 frontmatter 缺失的孪生文件——总是从磁盘读回 |
| `[[链接]]` 显示为断链 | 故意的前向链接，是「待写清单」，别当错误修 |
| 重新组织后链接全断 | 不会——`[[Name]]` 与路径无关；断的是**重命名**没改入站链接 |
| `sort \| uniq -c` 统计 CJK 文件名给错数 | 某些系统的排序规则把不同的 CJK 串合成一条；用 `LC_ALL=C` 或在 Python 里数。由此得出的任何统计作废 |
| 新写的笔记别的设备看不到 | 还在同步路上（或它以点/下划线开头被排除）——见 references/sync.md |
| 删除的笔记「自己回来了」 | 本地删了、同步状态没报上去，另一端当新文件又推回来——删除要走到同步完成的确认 |
