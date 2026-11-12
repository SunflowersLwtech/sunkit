# skill-forge

Two jobs in one steward skill:

1. **Session closeout** — before an agent session ends: reconcile every user
   ask against what was delivered, sweep scratchpads for credential residue,
   verify anything shipped is really live, kill background loops, write a
   handoff a fresh session can pick up. `scripts/closeout-scan.sh` does the
   mechanical half (git drift + plaintext-secret residue).
2. **Skill forging** — the seven mechanical obligations any new SKILL.md must
   pass before it counts as written, plus the judgment that cannot be
   checked (`references/forging.md`). `eval-lab/` and `eval-lab-viewer/`
   (derived from Anthropic's skill-creator, Apache-2.0 — see Upstream.md)
   benchmark and package skills.

Sky is the limit for fewer, sharper skills: one skill exists to change one
decision an agent gets wrong.
