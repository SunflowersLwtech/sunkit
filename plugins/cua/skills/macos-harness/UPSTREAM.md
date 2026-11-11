# Upstream provenance

The backbone of `SKILL.md` in this directory is taken from the
[browser-use/macos-harness](https://github.com/browser-use/macos-harness)
project, which is MIT-licensed (`LICENSE`, same directory).

- Source file: `skills/macos-harness/SKILL.md`
- Upstream version: **v0.1.0** (commit
  `38d81937a8a079f4bed208649e98aff2fb109a63`; byte-identical to v0.1.2)
- Why pinned there: upstream v0.2.0 rewrote the CLI interface, and the
  six-verb contract documented here (`see` / `key` / `type` / `click` / `ax` /
  `script`) only exists in the v0.1.x line. Install v0.1.2:

  ```bash
  uv tool install --python 3.12 --from git+https://github.com/browser-use/macos-harness@v0.1.2 macos-harness
  ```

Local changes on top of the upstream file:

- Frontmatter rewritten (name kept; description made self-contained for this
  plugin's marketplace listing).
- Type, CLI-call and permission wording generalized (e.g. "the LLM" → "the
  agent"); no behavioral content changed in the upstream sections
  (Minimize round trips, Use the small surface, Choose the lowest useful
  mode, Keep the invariants).
- Sections **added locally** (not from upstream):
  - an intro note on where the CLI comes from and how to install it;
  - *Electron and other Chromium-backed apps* (native open/save panels via
    AX, policy-disabled debug ports, CDP escape hatch and its traps);
  - *Input-dead but screenshot-live apps (WeChat class)*;
  - *HID-only apps (ToDesk / Flutter class)*;
  - the *Browser and permissions* section was expanded from upstream's
    shorter version (same intent, more detail).
