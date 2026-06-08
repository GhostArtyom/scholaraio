# ScholarAIO - Claude Code Entry

This file is the Claude Code project-memory entrypoint. It intentionally stays light:

- durable project facts and navigation live here
- reusable procedures belong in `.claude/skills/`
- deep reference lives in `docs/guide/agent-reference.md`

Claude-specific notes:

- **Web search delegation (HARD RULE)**: When the user asks anything requiring web search, web research, current information, or fact-checking against online sources, you MUST delegate to the `web-research` agent via the Agent tool. Do NOT call WebSearch, WebFetch, or mcp__cc-web__* tools directly from the main agent. The web-research agent owns all web-bound queries.
- Use `/memory` to edit this file or imported project memory.
- Keep shared workflows in skills, not in this file.
- Shared project guidance, including core writing skills such as `academic-writing`, `nature-workflow`, `paper-guided-reading`, `poster`, and `technical-report`, is imported from `@AGENTS.md`.
- Important canonical pointers remain: `scholaraio/stores/explore.py`, `scholaraio/projects/workspace.py`, `scholaraio/services/insights.py`, `scholaraio/services/translate.py`, `scholaraio/interfaces/cli/`, `scholaraio/interfaces/cli/compat.py` for internal CLI wiring, and `scholaraio/cli.py` as the published entrypoint.

@AGENTS.md
