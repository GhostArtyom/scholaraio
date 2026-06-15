# ScholarAIO - Claude Code Entry

This file is the Claude Code project-memory entrypoint. It intentionally stays light:

- durable project facts and navigation live here
- reusable procedures belong in `.claude/skills/`
- deep reference lives in the indexed `docs/` knowledge base, starting at `docs/DESIGN.md` and `docs/guide/agent-reference.md`

Claude-specific notes:

- **Web tools**: Use `WebSearch`. Use `mcp__cc-web__fetch_url` for URL fetching. Use `web-research` agent for complex multi-step research. Do NOT use `WebFetch`, `mcp__cc-web__web_search`, `mcp__cc-web__research_brief`.
- **Python runner**: Use `uv run scholaraio ...` (or `uv run python -m scholaraio.cli ...`) to run CLI commands in this repo — not bare `python` or `pip install`.
- Use `/memory` to edit this file or imported project memory.
- Keep shared workflows in skills, not in this file.
- Shared project guidance, including core writing skills such as `academic-writing`, `nature-workflow`, `paper-guided-reading`, `poster`, and `technical-report`, is imported from `@AGENTS.md`.
- Important canonical pointers remain: `scholaraio/stores/explore.py`, `scholaraio/projects/workspace.py`, `scholaraio/services/insights.py`, `scholaraio/services/translate.py`, `scholaraio/interfaces/cli/`, `scholaraio/interfaces/cli/compat.py` for internal CLI wiring, and `scholaraio/cli.py` as the published entrypoint.

@AGENTS.md
