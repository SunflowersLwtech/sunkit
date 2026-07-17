---
source: GitHub - upstash/context7: Context7 Platform -- Up-to-date code documentation for LLMs and AI code editors
url: https://github.com/upstash/context7
final_url: https://github.com/upstash/context7
language: en
fetched_at: 2026-05-04
bytes: 5971
---

# GitHub - upstash/context7: Context7 Platform -- Up-to-date code documentation for LLMs and AI code editors

> Context7 Platform -- Up-to-date code documentation for LLMs and AI code editors - upstash/context7

LLMs rely on outdated or generic information about the libraries you use. You get:

* ❌ Code examples are outdated and based on year-old training data
* ❌ Hallucinated APIs that don't even exist
* ❌ Generic answers for old package versions

Context7 pulls up-to-date, version-specific documentation and code examples straight from the source — and places them directly into your prompt.

```
Create a Next.js middleware that checks for a valid JWT in cookies
and redirects unauthenticated users to `/login`. use context7
```

```
Configure a Cloudflare Worker script to cache
JSON API responses for five minutes. use context7
```

```
Show me the Supabase auth API for email/password sign-up.
```

Context7 fetches up-to-date code examples and documentation right into your LLM's context. No tab-switching, no hallucinated APIs that don't exist, no outdated code generation.

Works in two modes:

* CLI + Skills — installs a skill that guides your agent to fetch docs using

  ```
  ctx7
  ```

  CLI commands (no MCP required)
* MCP — registers a Context7 MCP server so your agent can call documentation tools natively

Note

API Key Recommended: Get a free API key at context7.com/dashboard for higher rate limits.

Set up Context7 for your coding agents with a single command:

```
npx ctx7 setup
```

Authenticates via OAuth, generates an API key, and installs the appropriate skill. You can choose between CLI + Skills or MCP mode. Use

```
--cursor
```

,

```
--claude
```

, or

```
--opencode
```

to target a specific agent.

To remove the generated setup later, run

```
npx ctx7 remove
```

. If you globally installed the CLI with

```
npm install -g ctx7
```

, remove that package separately with

```
npm uninstall -g ctx7
```

.

To configure manually, use the Context7 server URL

```
https://mcp.context7.com/mcp
```

with your MCP client and pass your API key via the

```
CONTEXT7_API_KEY
```

header. See the link below for client-specific setup instructions.

Manual Installation / Other Clients →

If you already know exactly which library you want to use, add its Context7 ID to your prompt. That way, Context7 can skip the library-matching step and directly retrieve docs.

```
Implement basic authentication with Supabase. use library /supabase/supabase for API and docs.
```

The slash syntax tells Context7 exactly which library to load docs for.

To get documentation for a specific library version, just mention the version in your prompt:

```
How do I set up Next.js 14 middleware? use context7
```

Context7 will automatically match the appropriate version.

If you installed via

```
ctx7 setup
```

, a skill is configured automatically that triggers Context7 for library-related questions. To set up a rule manually instead, add one to your coding agent:

* Cursor:

  ```
  Cursor Settings > Rules
  ```
* Claude Code:

  ```
  CLAUDE.md
  ```
* Or the equivalent in your coding agent

Example rule:

```
Always use Context7 when I need library/API documentation, code generation, setup or configuration steps without me having to explicitly ask.
```

* ```
  ctx7 library <name> <query>
  ```

  : Searches the Context7 index by library name and returns matching libraries with their IDs.
* ```
  ctx7 docs <libraryId> <query>
  ```

  : Retrieves documentation for a library using a Context7-compatible library ID (e.g.,

  ```
  /mongodb/docs
  ```

  ,

  ```
  /vercel/next.js
  ```

  ).

* ```
  resolve-library-id
  ```

  : Resolves a general library name into a Context7-compatible library ID.
  + ```
    query
    ```

    (required): The user's question or task (used to rank results by relevance)
  + ```
    libraryName
    ```

    (required): The name of the library to search for
* ```
  query-docs
  ```

  : Retrieves documentation for a library using a Context7-compatible library ID.
  + ```
    libraryId
    ```

    (required): Exact Context7-compatible library ID (e.g.,

    ```
    /mongodb/docs
    ```

    ,

    ```
    /vercel/next.js
    ```

    )
  + ```
    query
    ```

    (required): The question or task to get relevant documentation for

* CLI Reference - Full CLI documentation
* MCP Clients - Manual MCP installation for 30+ clients
* Adding Libraries - Submit your library to Context7
* Troubleshooting - Common issues and solutions
* API Reference - REST API documentation
* Developer Guide - Run Context7 MCP locally

1- Context7 projects are community-contributed and while we strive to maintain high quality, we cannot guarantee the accuracy, completeness, or security of all library documentation. Projects listed in Context7 are developed and maintained by their respective owners, not by Context7. If you encounter any suspicious, inappropriate, or potentially harmful content, please use the "Report" button on the project page to notify us immediately. We take all reports seriously and will review flagged content promptly to maintain the integrity and safety of our platform. By using Context7, you acknowledge that you do so at your own discretion and risk.

2- This repository hosts the MCP server’s source code. The supporting components — API backend, parsing engine, and crawling engine — are private and not part of this repository.

Stay updated and join our community:

* 📢 Follow us on X for the latest news and updates
* 🌐 Visit our Website
* 💬 Join our Discord Community

* Better Stack: "Free Tool Makes Cursor 10x Smarter"
* Cole Medin: "This is Hands Down the BEST MCP Server for AI Coding Assistants"
* Income Stream Surfers: "Context7 + SequentialThinking MCPs: Is This AGI?"
* Julian Goldie SEO: "Context7: New MCP AI Agent Update"
* JeredBlu: "Context 7 MCP: Get Documentation Instantly + VS Code Setup"
* Income Stream Surfers: "Context7: The New MCP Server That Will CHANGE AI Coding"
* AICodeKing: "Context7 + Cline & RooCode: This MCP Server Makes CLINE 100X MORE EFFECTIVE!"
* Sean Kochel: "5 MCP Servers For Vibe Coding Glory (Just Plug-In & Go)"

MIT
