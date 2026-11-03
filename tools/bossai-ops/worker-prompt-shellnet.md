研究任务：Claude Code 的 bash 工具网络沙箱机制，用于设计 BossAI 的「作用域内放网」。

背景：BossAI 的 shell_command 走 srt OS sandbox（apps/server/src/services/chatBashIsolationPolicy.ts + bashSandbox.ts），networkAccess 默认 deny，导致需要联网的远程运维类 agentic run 反复失败空转（实测 100+ 轮 LLM 调用、每轮 ~180k tokens 无效燃烧）。目标是给它加一个受控的联网路径。

请完成：
1. 查 Claude Code（本机 ~/.claude、官方文档、Anthropic sandbox-runtime/srt 源码如可得）的 bash 网络沙箱实现：Linux bubblewrap 与 macOS Seatbelt 各自怎么限网？是否走 HTTP/SOCKS 代理做域名 allowlist？allowedDomains 类配置在哪层生效、exec 时如何注入？
2. 读 BossAI 现状代码（chatBashIsolationPolicy.ts、bashSandbox.ts、BOSSAI_BASH_NETWORK/BOSSAI_BASH_OS_SANDBOX/BOSSAI_FS_CONFINEMENT 相关路径），找出机制差距。
3. 产出最小设计：给 BossAI 加「按会话/按任务 allowlist 放网」——改哪些文件、配置面长什么样、如何保持 fail-closed 默认不破。
4. 把结论写成 markdown 报告存到仓库 tasks/shell-network-sandbox-claude-code-20261103.md（不 commit、不改源码——纯调研交付物）。
5. 报告开头写 DONE，并附 3 行要点总结。
