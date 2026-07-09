# ScholarAIO - Claude Code Entry

This file is the Claude Code project-memory entrypoint. It intentionally stays light:

- durable project facts and navigation live here
- reusable procedures belong in `.claude/skills/`
- deep reference lives in the indexed `docs/` knowledge base, starting at `docs/DESIGN.md` and `docs/guide/agent-reference.md`

Claude-specific notes:

- **Web tools**: Prefer `mcp__exa__web_search_exa` for web search. Use `mcp__exa__web_fetch_exa` for URL fetching. Use `mcp__exa__web_search_advanced_exa` (with `includeDomains`) for scoped or topic overviews. Use `web-research` agent for complex multi-step research. Do NOT use `WebSearch` or `WebFetch`.
- **Python runner / CLI**: Run the project CLI as `uv run scholaraio ...`. Use `uv run python -m <pkg>` only for modules without a console entry point.
- **No inline Python scripts**: Do not write `python -c` / `uv run python -c` one-liners for data queries or bulk edits. Use `scholaraio` CLI commands, `jq`, `grep`, `awk`, `comm`, and shell pipelines instead. Only fall back to Python when the CLI has no equivalent and shell tools genuinely cannot express the logic.
- Use `/memory` to edit this file or imported project memory.
- Keep shared workflows in skills, not in this file.
- Shared project guidance, including core writing skills such as `academic-writing`, `nature-workflow`, `paper-guided-reading`, `poster`, and `technical-report`, is imported from `@AGENTS.md`.
- Important canonical pointers remain: `scholaraio/stores/explore.py`, `scholaraio/projects/workspace.py`, `scholaraio/services/insights.py`, `scholaraio/services/translate.py`, `scholaraio/interfaces/cli/`, `scholaraio/interfaces/cli/compat.py` for internal CLI wiring, and `scholaraio/cli.py` as the published entrypoint.

@AGENTS.md
