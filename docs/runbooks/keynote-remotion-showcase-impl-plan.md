# Searchpo Keynote Remotion Showcase — 实施计划

> 分支：`feat/keynote-remotion-showcase`
> Worktree：`/Users/sunfl/Documents/media/searchpo-keynote`
> 目标：把 provider 视频从模板化 Searchpo Radar 升级到"重金打造的 Apple 发布会 Keynote"级别；用 React/Remotion programmatic 真实生成 MP4；E2E 验证多 topic 真实渲染。

## 0. 现状基线

| 维度 | 现状 | 改造后 |
|---|---|---|
| 视觉主结构 | 模板化 HexGrid/雷达圆/节点圆环（main 分支的 `src/Composition.tsx` 默认渲染） | 强制 full-canvas `AgentVisualGenerated`，全屏由 `src/premium/PremiumRepoVisual.tsx` 拥有 |
| GitHub repo 覆盖 | `render/prepare_remotion_input.py` + `agent_harness/stages.py` 静默把 DeepSeek 输出替换成 `premium_repo_agent_visual()`（773 行的固定 PremiumRepoVisual） | 取消静默覆盖；允许 `module_code` 走透；PremiumRepoVisual 退化为**可选 fallback** |
| Director Spec | 无 | 新增 `premium_director_spec`（typed dataclass + JSON schema），存进 `video_spec.json` 和 `render_payload.json` |
| Premium Compiler | 单一组件 `PremiumRepoVisual`，永远渲染 5 段（Problem/Repo/Mechanism/Evidence/Decision） | 新增 5+ 场景库：`HeroScene / MechanismScene / CodeScene / MetricScene / DecisionScene / TakeawayScene`；由 compiler 按 director_spec 拼装 |
| 内容话术 | "按证据验证，不急着下结论" / "待验证案例继续观察" / "自己验证" 出现在 `scripts/deepseek_polish.py` 多处 | 替换为"机制 / 架构位置 / 适用 / 失败边界 / 判断框架" |
| 多媒体内容 | 单一 motion（fade-rise + sweep light） | Ken Burns 推近、mask reveal、SVG path draw、counter 滚字、object focus |
| 视觉对比 | 6 个外部 remotion 视频都共享"暗蓝+节点圆环+无声" | 引入"横向 16:9 默认"（repo/code/architecture/dense），但**保留垂直手机向选项** |
| 审计 | Deterministic + Gemini；无 showcase 对比 | 新增 `premium_showcase_audit.py` 对比 `/Volumes/Sunflowers/T7/mac32/document/study` |
| 渲染证据 | 单元测试 | 5 个 topic 真实 provider render 跑通 |

## 1. 改动清单（按 ROI 排序，全部要在 worktree 内完成）

### P0 — 解除静默覆盖

1. **`render/prepare_remotion_input.py:165-167`** — 删除 `if is_github_repo_subject(payload=payload)` 分支，**让 provider 输出的 `module_code` 直接写盘**。同时保留 `premium_repo_agent_visual()` 作为**只在没有 provider module_code 时**的兜底。

2. **`agent_harness/stages.py:418-422`** — 同上：把 `premium_repo_visual_applied = True` 这条短路移除；改为只在 polish 无 `agent_visual.module_code` 时调用 `premium_repo_agent_visual` 兜底。

3. **`scripts/deepseek_polish.py:2078` (`source_grounded_agent_visual`)** — 同样：只在没有 module_code 时才降级到 `premium_repo_agent_visual`。

4. **`scripts/deepseek_polish.py:510 / :3279 / :501`** — 删掉 "按证据验证，不急着下结论" / "待验证案例继续观察" / "不能跳过最小验证" 三处模板文案；改成"机制解释 + 架构位置 + 适用边界 + 判断框架" 5 句式。

### P1 — Director Spec + 场景库

5. **新增 `agent_harness/premium_director_spec.py`**
   - dataclass `VisualScene { id, kind, duration_in_frames, props }`
   - dataclass `DirectorSpec { profile, knowledge_arc, visual_scenes, topic_objects, motion_beats, content_constraints }`
   - 校验器：每个 scene.kind 必须在已知 scene_type 集合中；topic_objects 至少 3 个；banned_phrases 不在 scene.props 文本中
   - JSON Schema: `contracts/schemas/premium_director_spec.schema.json`

6. **`scripts/deepseek_polish.py`** — 在 prompt 里加 `agent_visual_layout_contract()` 的同时，**额外要求 LLM 输出 `visual_recipe` 字段**（结构化 JSON），与 `module_code` 并列；若 LLM 没给，compiler 端 fallback 到 provider 现有 mechanism/details 拼装。

7. **新增 `src/premium/scenes/` 目录**，包含：
   - `HeroScene.tsx` — 巨号 280px + 慢推 + 单色 bloom
   - `MechanismScene.tsx` — 抽象 SVG 节点流（每段一条主线，5 节点交错）
   - `CodeScene.tsx` — 真实代码（typewriter 40ms/字）+ terminal 三色 LED
   - `RepoScene.tsx` — 文件树逐行展开 + module 列表
   - `MetricScene.tsx` — 数字 counter 滚到目标值（easeOutExpo）
   - `DecisionScene.tsx` — 双栏 good-fit / failure-mode
   - `TakeawayScene.tsx` — 5 句"机制 / 架构位置 / 适用 / 失败边界 / 判断框架"
   - `ChapterCard.tsx` — "01 / The Problem" 全屏衬线卡

8. **新增 `src/premium/compiler.tsx`** — 接收 `DirectorSpec` → 输出 `<AgentVisualGenerated>` 组件树；scene kind 路由到对应 scene 组件。

9. **`src/premium/PremiumRepoVisual.tsx` 改为 `compiler` 默认回退路径**（保留兼容性，但默认走 `compiler`）。

### P2 — 内容契约

10. **`config/searchpo_policy.json`** — 加 `content.banned_phrases` 列表（"自己验证", "待验证案例继续观察", "按证据验证，不急着下结论", "不急着下结论", "你自己动手验证", "需要自己去试"）。

11. **`scripts/content_scorer.py`** — 新增维度 `knowledge_density`（每段必须包含"机制/架构/适用/失败/判断"5 个词中的至少 3 个）；加 `dismissive_phrase_penalty`（命中 banned phrase 一次扣 8 分）。

12. **`scripts/deepseek_polish.py`** — `validate_polish` 后增加 `scrub_dismissive_phrases(polished)` 步骤；命中即尝试用 knowledge-takeaway 模板替换；替换失败抛错让 repair 路径接管。

13. **`agent_harness/storyboard.py`** — `safe_storyboard` 的 cta 段 `text` 默认值从"按证据验证，不急着下结论"改为"今天带走：<机制一句话> + <架构位置一句话>"。

### P3 — 审计与对比

14. **`scripts/deterministic_visual_audit.py`** — 加规则：`scene_grammar_changes` 必须 ≥ 3 个不同视觉族（hero / mechanism / code / metric / decision / takeaway）；reject 整片单组件。

15. **`scripts/gemini_visual_audit.py`** — prompt 中加新维度："premium keynote aesthetic" / "topic-specific grammar" / "knowledge density" / "no dismissive phrases"。

16. **新增 `scripts/premium_showcase_audit.py`** — 对比 `study` 目录的 6 个参考视频，让 Gemini 1-5 评分（premium 感、topic 特异性、motion 顺滑度、knowledge density、no-card-template、no-dismissive），写 `premium_showcase_audit.json`。

17. **`tests/`** — 加：
    - `test_premium_director_spec.py` — schema 校验、banned phrase 校验
    - `test_premium_compiler.py` — scene kind 路由
    - `test_github_repo_override.py` — 验证 provider module_code 不会被静默替换
    - `test_dismissive_phrases.py` — 验证全流水线不输出 banned phrases
    - `test_showcase_audit_contract.py` — 验证 audit artifact 字段

### P4 — 5 Topic 真实 E2E 渲染

18. 跑 5 个 topic 真实 provider render：
    - `https://github.com/mem0ai/mem0` (GitHub repo)
    - `https://github.com/assafelovic/gpt-researcher` (GitHub repo, 复杂多文件)
    - 一个 AI 论文 (arXiv)
    - 一个 dev tool (e.g. cursor / claude-code)
    - 一个产品发布 (e.g. Anthropic / OpenAI 公告)

    每条记录：
    - run dir
    - final MP4 路径
    - render_metadata_check.json 状态
    - visual_audit_deterministic.json 状态
    - gemini_visual_audit.json 状态
    - premium_showcase_audit.json 状态
    - banned phrases absent 验证
    - 一句话说明用了什么 visual grammar

19. 在主答案中给出"系统是否真正升级"的明确判断 + 剩余 blockers 列表。

## 2. 验收标准

每一条都必须有真实 artifact 证据：

- [ ] `agent_visual.module_code` 在 `render/prepare_remotion_input.py` 中**不被静默替换**
- [ ] `video_spec.json` 中能找到 `premium_director_spec` 字段
- [ ] `render_payload.json` 中能 round-trip `premium_director_spec`
- [ ] `PremiumRepoVisual` 仍有，但通过 `compiler` 接受 `DirectorSpec`
- [ ] 5 个 banned phrases 全部从 `scripts/deepseek_polish.py` / `agent_harness/storyboard.py` 移除
- [ ] `content_scorer.py` 加 `knowledge_density` 和 `dismissive_phrase_penalty`
- [ ] `premium_showcase_audit.py` 存在并能跑
- [ ] 5 个 topic 真实 provider render 全部通过
- [ ] 所有单元测试 pass
- [ ] 不打印 .env 密钥
- [ ] 不做 mock audio / silent media / 假 audit / 假 publish

## 3. 不做什么

- 不删 safety validator（agent_visual 的 BLOCKED_CODE_PATTERNS / RISKY_LAYOUT_PATTERNS / MOTION_COMFORT_PATTERNS），而是保留为**合规审计**
- 不触碰 main 分支其他无关改动
- 不活发布（除非用户额外要求 `post --live`）
- 不改 Douyin publish 流程
- 不改 voiceover 文本长度逻辑（除了内容话术）

## 4. E2E 验证策略

```bash
# 单元测试
python3 -m unittest tests.test_premium_director_spec tests.test_premium_compiler \
  tests.test_github_repo_override tests.test_dismissive_phrases \
  tests.test_showcase_audit_contract tests.test_static_contracts \
  tests.test_storyboard_contract tests.test_remotion_inputs \
  tests.test_deepseek_polish

# 5 topic 真实 provider render
SEARCHPO_LINK="https://github.com/mem0ai/mem0" npm run e2e:provider
SEARCHPO_LINK="https://github.com/assafelovic/gpt-researcher" npm run e2e:provider
SEARCHPO_TOPIC="Anthropic Computer Use 2025 release" npm run e2e:provider
SEARCHPO_TOPIC="Cursor 2.0 background agents launch" npm run e2e:provider
SEARCHPO_LINK="https://arxiv.org/abs/2605.26731" npm run e2e:provider

# 每个 run 后验证
RUN_DIR=$(cat runtime/latest_run.txt)
jq '.status' "$RUN_DIR/render_metadata_check.json"
jq '.status' "$RUN_DIR/visual_audit_deterministic.json"
jq '.status' "$RUN_DIR/gemini_visual_audit.json"
jq '.status' "$RUN_DIR/premium_showcase_audit.json"
grep -E "自己验证|待验证|不急着|需要自己去试" "$RUN_DIR"/{script,deepseek_polish,content_plan,voiceover_manifest,visual_audit_deterministic,gemini_visual_audit,premium_showcase_audit,storyboard}.json && echo "BANNED PHRASE FOUND" || echo "OK"
```

## 5. 风险与回退

- 风险 1：DeepSeek 不返回结构化 `visual_recipe` → fallback 到 provider module_code → fallback 到 PremiumRepoVisual → fallback 到 safe_agent_visual。每一步都保留。
- 风险 2：5 个 topic 全跑需要真实 API key（DeepSeek/Gemini/AnySearch/TTS）→ 通过 `python3 scripts/agent_capabilities.py --profile implementation` 提前确认；缺哪个就显式标注。
- 风险 3：scene 库引入新依赖 → 全部用 React/Remotion/SVG 内置 API，不引入新 npm 包。
- 风险 4：scrub_dismissive_phrases 误伤 → 只针对 banned phrase 字面匹配，不做语义替换。
