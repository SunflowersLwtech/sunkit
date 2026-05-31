# Skill Resolver

This is the dispatcher. Skills are the implementation. Read the matched
`SKILL.md` before acting.

## Always Route

| Trigger | Skill |
| --- | --- |
| "repo to X", "Twitter/X thread", "posting pack", "launch thread", "share this repo", "推荐这个项目", "写成推文" | `skills/github-repo-to-x-threads/SKILL.md` |
| GitHub URL, `owner/repo`, or local repo path plus a request to post/share/explain publicly | `skills/github-repo-to-x-threads/SKILL.md` |
| arXiv/alphaXiv/paper/blog/docs/PDF/note/raw idea plus a request to decide X strategy or create social copy | `skills/github-repo-to-x-threads/SKILL.md` |
| "账号定位", "bio", "profile", "置顶帖", "pinned post", "Agent 工程实战派" | `skills/github-repo-to-x-threads/SKILL.md` |
| "KYC", "客服", "工单", "申诉", "吐槽", "bug report", "冷静反馈" plus X/social copy | `skills/github-repo-to-x-threads/SKILL.md` |
| "配图", "image2", "GPT Image 2", "actual images" for a posting pack | `skills/github-repo-to-x-threads/SKILL.md` |
| "publish", "上传", "发 X", "CLI 发 thread" | `skills/github-repo-to-x-threads/SKILL.md` |
| "record metrics", "postmortem", "strategy memory", "skill 自进化", "eval results", "Trending experiment" | `skills/github-repo-to-x-threads/SKILL.md` |

## Cross-Cutting References

- `skills/github-repo-to-x-threads/references/content-quality-gates.md` - use
  when a safe draft still feels generic, smooth, abstract, or weak.
- `skills/github-repo-to-x-threads/references/creator-style-patterns.md` - use
  when improving content quality, taste, demo value, cadence, creator-pattern
  fit, or when the user references AI/X creators as style examples.
- `skills/github-repo-to-x-threads/references/agent-engineering-brand-profile.md` -
  use for account positioning and main-account content fit.
- `skills/github-repo-to-x-threads/references/bug-report-rewrite-template.md` -
  use for KYC/support/platform complaint rewrites.
- `skills/github-repo-to-x-threads/references/paper-to-system-template.md` - use
  for paper inputs that need engineering translation instead of summary.
- `skills/github-repo-to-x-threads/references/profile-bio-pinned-post.md` - use
  for bio, profile, and pinned-post work.
- `skills/github-repo-to-x-threads/references/model-intelligence-quality-chain.md` -
  use when strengthening generation quality, self-review, or model-side
  editorial reasoning.
- `skills/github-repo-to-x-threads/references/self-evolving-strategy.md` - use
  for adaptive routing, postmortems, local strategy memory, or arbitrary inputs.
- `skills/github-repo-to-x-threads/references/skill-evolution-system.md` - use
  when changing the skill based on evals, metrics, or Trending experiments.
- `skills/github-repo-to-x-threads/references/thread-quality-checklist.md` - use
  before final pack review.

## Disambiguation

Prefer the governed run scripts when the work needs repeatability, multiple
sources, image governance, final posting packs, review, publishing, or future
learning. Use direct chat drafting only for lightweight exploration.

When in doubt, preserve claim safety and ownership boundaries first, then
optimize voice, hook, and visuals.
