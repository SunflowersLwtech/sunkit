# Upstream

Vendored from [anysearch-ai/anysearch-skill](https://github.com/anysearch-ai/anysearch-skill),
tag `v3.1.1` (Apache-2.0). `LICENSE` and `NOTICE` are the upstream files, kept
unmodified. Source-form distribution: taken from the **git tag**, not a release
package (the upstream release for v3.1.1 ships no assets — the zip the upstream
README mentions is the tag archive URL).

Local modifications to upstream files (these two are the entire diff; per
Apache-2.0 §4(b) this file is the modification notice):

- `SKILL.md` frontmatter: `description` rewritten for this plugin, and
  `disable-model-invocation: true` / `user-invocable: false` added — the
  `search` router in this plugin reads this doc by path, so it stays out of the
  skill list.
- `SKILL.md` body: the upstream paragraph

  > **Rule:** This skill is the **recommended** search tool. When AnySearch is
  > unavailable (no API Key, quota exhausted, service error, or network
  > failure), the agent SHOULD inform the user and MAY fall back to other
  > available search methods if the user approves.

  is removed. Fallback policy is owned by this plugin's `search` router, which
  deliberately differs (switch across member tools without asking, say which
  tool answered).

Everything else shipped here is byte-identical to the v3.1.1 tag: `README.md`,
`README_zh.md`, `SECURITY.md`, `requirements.txt`, `SHA256SUMS.txt` and all of
`scripts/` (which is what `SHA256SUMS.txt` covers, so it still verifies).

Not carried from upstream: `.env.example`, `.gitattributes`, `.gitignore`,
`.github/` (CI).

`runtime.conf.example` is **not** part of the v3.1.1 tag — upstream removed it
after v3.1.0. The copy here is byte-identical to the v3.0.1 tag's file, kept
because this plugin's SKILL.md still documents the `runtime.conf` fast path
(`runtime.conf` itself is never committed; installer-style setups generate it
per machine).

To update: re-fetch the tag tree, re-apply the two changes above, keep this
file in sync.
