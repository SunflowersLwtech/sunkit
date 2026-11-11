# obsidian-wiki

Use the user's Obsidian vault as the agent's long-term memory: recall in tiers
before answering, write session conclusions back as indexed notes, keep the
wiki self-correcting, and survive multi-device sync. Part of
[sunkit](../../README.md).

```
/plugin marketplace add SunflowersLwtech/sunkit
/plugin install obsidian-wiki@sunkit
```

The skill works on a plain folder of markdown with ordinary file tools
(Read/Write/Edit + grep). The official `obsidian` CLI that ships with recent
Obsidian desktop builds is treated as an optional accelerator — link-safe
rename, structural queries, app-state eval — and every one of its jobs has a
plain-file fallback. `references/sync.md` carries the generic multi-device
sync lessons (eventual consistency, whole-file conflicts, subset syncing,
delete propagation); `references/obsidian-cli.md` is the CLI reference.

What the skill does *not* do: it is not a sync tool and is not pinned to any
particular sync backend. If your fleet syncs the vault through some plugin or
cron loop, that setup stays yours — the skill only carries the judgement rules
that keep the wiki intact under it.
