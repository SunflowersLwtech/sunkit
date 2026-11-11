---
name: skill-forge
description: Run a full closeout audit before an agent session ends, and forge new skills so they actually change agent behavior. Closeout reconciles every user ask against what shipped, sweeps scratchpads for credential residue, verifies anything shipped is really live, and kills background loops before they bite. Forging pins the seven mechanical obligations a new skill must pass before it counts as written. Fires on wrap-up, handoff, "写完收尾", "关掉这个 session", or any request to write, shorten, or review a SKILL.md.
metadata:
  last-reviewed: 2026-11-20
---

# skill-forge

审计,不是仪式。收尾 = 一屏可读的报告 + 一个新 session 能无缝接手的世界状态。

## A. Session 收尾(按序执行)

### ① 需求对账

重读本 session 的每一条 user message,含 mid-turn 插话。逐条判:

- `done`(带证据)
- `deferred`(记录处 + **验过的阻塞点**:「A 挂了」不算,写「B 需要 a/b/c,断的是哪条」)
- `handed-back`(需用户决策——用户在场用 AskUserQuestion 做成一次显式选择;
  不在场(worker 收尾)写进报告、按汇报渠道转交)
- 只满足最后一条 prompt 的 session 从内部看是完整的——所以此步必须回 transcript,不许凭记忆

### ② 密钥:靠读回,不靠回忆

- 自己写的遮罩正则按格式分派会漏:调试 trace(`sh -x`/`curl -v`)打的是展开后的值;
  走 argv 的密钥被包装器连命令回显;邮件标题、通知预览、URL 参数一次性验证码常写在标题里
- 平台遮罩按形状替换:PEM 头形态的私钥在工具返回里变占位符,同一把钥匙的 base64 形态原样通过
- 取值一律 shell 层重定向落盘,报告里只留 KEY 名与哈希/指纹
- 部署会产生完成感,入库是独立动作:读回比对才算数

### ③ 结论落盘

值得召回的结论在写报告**之前**写进笔记库(按主题分目录、可被后续 session 检索)。
写入会部分成功,失败行还印在成功行之前;读回要 grep 索引里那一行,不信末行。

### ④ 机械扫描

- `find <目录…> -type f -newermt '<绝对日期>'` 窗口用绝对日期;
- 残留检查最容易假绿;扫描根本身是软链则 `find` 默认不进去,④ 的根路径一律先 `realpath`;
- worktree 开在没人写的树上;不做别人 checkout 的修改

### ⑤ 线上与对外一致性

- 每次发布判「谁在写、写了什么、有什么可观测量会因此不同」;
- 报告为真是测量,不是过程;写明验证命令,复现才通过;
- 「已发布」三个字也算对外产物,发完从接受侧读回产物本身(邮件正文、确认页字段、PR body)。

### ⑥ 测试与 QA 对账

- 问它「看得见这一类错吗」:缺陷此刻就在,它会报什么?
- 反过来也要测:它会不会报出不存在的错——阈值判据先对「什么都没变」跑一次
- 最后按将来被使用的条件验一次,而不是按写入成功验

### ⑦ 清理与 handoff

- 后台循环引用的路径,先停循环再删;点名杀自己起的进程,别用 `pkill -f`(会打到别人)
- 未完成事项进 handoff,带确切的续跑命令;「见上文对话」不是 handoff
- 收尾时对每条向用户做出的可验证承诺(隧道、端口转发、代理)重取独立读数,掉过就写明

## B. 锻造法则

- skill 为行为而写:每段要么改变 agent 的一个决策,删掉
- 规则写成带机制的条件句,不写口号;例子写真实踩过的坑(机制留下、故事删掉)
- 七条硬义务全部可被第三方复跑核查:值三态可溯 / 引用路径存在 / 交付物执行过 /
  frontmatter 解析 / 触发词分类器测试 / 有无对比 / 退役源前机械证明内容落地
- 大规模多 agent 评测只在用户明确要求时启动;进程文件设上限,逼近先删后加

## C. 自进化

每次收尾问一句:哪条检查这次抓到了真问题?从未触发的删掉,抓到真问题的升格成硬义务;
改动记进本文件,不另开过程文档。
