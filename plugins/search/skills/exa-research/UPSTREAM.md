# Upstream

Vendored from [exa-labs/exa-mcp-server](https://github.com/exa-labs/exa-mcp-server)
at `15ffb50519e719dc791cdc750ce5ed1934c0a1ed` (`skills/search`), the Exa Claude
Code plugin's bundled skills, under that project's MIT license (see `LICENSE`).

Local edits relative to upstream: frontmatter only (name, description, and the
`disable-model-invocation` / `user-invocable` fields — the `search` router reads
this doc by path). To update: re-fetch that path at a newer sha and re-apply the
frontmatter.
