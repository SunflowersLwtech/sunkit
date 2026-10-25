# frontier

Claude Code subagents that hand one task to another agent harness, each in its own official client and signed in on its own machine, plus the magpie gateway's model list. Part of [sunkit](../../README.md).

| subagent | runs | on |
|---|---|---|
| `agy-pro` | Antigravity CLI (`agy -p`), weiliu0607, Google AI Pro | m2, in `~/.harness-jobs/<job>` |
| `agy-trial` | Antigravity CLI, devweiliu0607, Samsung trial | M4, in `~/.harness-jobs/<job>` |
| `zen` | OpenCode CLI (`opencode run`), Zen free models | this machine, in the current folder |
| `zcode` | ZCode CLI bundled in ZCode.app (`zcode.cjs -p`) | M4, in `~/.harness-jobs/<job>` |
| `frontier` | Claude Code headless on the magpie gateway (`claude --settings ~/.claude/magpie-settings.json -p`) | this machine, in the current folder |

Each subagent runs on Haiku and only relays: it passes the task word for word to `bin/harness-run`, which Claude Code puts on the Bash tool's PATH, and returns the answer. A failed run is reported, never retried on another account.

```
harness-run list
harness-run agy-pro -f clip.mp4 "What happens in this video, with timestamps?"
harness-run zen -m opencode/glm-5.3-flash-free "Review this diff for bugs" -f change.diff
harness-run gw -m auto/gpt-6.1-sol --edit "Fix the failing test in tests/test_x.py"
harness-run status agy-trial
harness-run models gpt
```

- agy and zcode are reached over ssh (`m2`, `m4`; override with `HARNESS_HOST_AGY_PRO` etc.). `-f` files are copied into the job folder, and files the run creates or changes are copied back to `./harness-out/<job>/`. Job folders older than a week are removed.
- zen and gw run in `-C DIR` (default: the current folder), read-only unless `--edit`: OpenCode's `plan` agent, Claude Code's plan mode.
- `/frontier:models [text]` lists the gateway's models; the `frontier-models` skill says which group or subagent to use.

Setup per machine: `claude plugin install frontier@sunkit`. zen needs OpenCode (`curl -fsSL https://opencode.ai/install | bash`); frontier needs `magpie-client setup` (tools/magpie-gateway). agy and zcode need ssh to m2/m4.

Tests: `python3 -m unittest discover -s plugins/frontier/tests` (fake clients, fake ssh/scp against a temp home).
