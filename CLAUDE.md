# CLAUDE.md — Helix

Read `REQUIREMENTS.md` for the full spec. This file is the build guide.

## Architecture

3-step helix: **Brainstorm** (master → `idea.md`) → **Execute** (researcher: plan.md first → implement → `results.md`) → **Reflect** (master → `reflect.md` + update `tree_search.md`).

No database. No git. No dashboard. All state lives in files: `tree_search.md` (master-written research tree), `runs/` (per-run archive), `config.yaml` (API keys), `helix.toml` (agent config).

All agents are CLI subprocesses with full computer permissions. The setup agent is the only direct LLM API call (GPT-5.4).

## Build Order
 
### Phase 1 — Core Loop (MVP)
 
Build and test in this order:
 
1. **`helix/config.py`** — Parse `config.yaml` (PyYAML + Pydantic) and `helix.toml` (tomli + Pydantic). Models: `GlobalConfig`, `WorkspaceConfig`, `AgentConfig`. Validation: exactly one master, ≥1 researcher. Config resolution: CLI → toml → yaml → defaults.
 
2. **`helix/models.py`** — Pydantic models: `RunState` (id, status, parent_id, tree_number), `AgentRun` (stdout, stderr, exit_code, duration), `ParsedResults` (metrics dict, observations).
 
3. **`helix/agents.py`** — Spawn agent CLI as subprocess with full permissions. Build command string from agent config (cli + full_access_flag + prompt flag + context). Capture stdout/stderr to `runs/{id}/logs/`. Enforce timeout (SIGTERM → SIGKILL after 10s). Return `AgentRun`. Handle both Claude (`-p`) and Codex (`-q`) prompt flags.
 
4. **`helix/context.py`** — Build 3 context markdown files by reading and concatenating research memory files + run-specific files. Write to `.helix/context_{step}.md`. Also: `generate_agent_md()` to concatenate research memory into `CLAUDE.md` / `AGENTS.md`.
 
5. **`helix/runs.py`** — Run folder management: `create_run_folder(run_id)` (creates `runs/{id}/` with subdirs), `parse_results(run_id)` (read `results.md`, extract JSON metrics block), `parse_tree_search()` (read `tree_search.md`, return list of nodes with status/numbering), `get_best_run()`, `get_frontier_runs()`, `next_run_id(parent)` (compute next child number).
 
6. **`helix/loop.py`** — The helix:
   ```
   while not criteria_met and run_count < max_runs:
       run_id = determine from tree (frontier pick or new)
       create_run_folder(run_id)
 
       # Step 1: Brainstorm
       build context_brainstorm.md
       spawn master → web search or read reference documents if necessary → writes runs/{id}/idea.md
 
       # Step 2: Execute
       build context_execute.md
       spawn researcher → writes plan.md, implements, writes results.md
       parse metrics from results.md
       check criteria
 
       # Step 3: Reflect
       build context_reflect.md
       spawn master → writes reflect.md, updates tree_search.md
 
       regenerate CLAUDE.md / AGENTS.md
   ```
   Handle: SIGINT/SIGTERM graceful shutdown (finish current step, then stop), agent crash recovery (log error, mark run as failed in tree, continue to next), 1-hour child process timeout.
 
7. **`helix/cli.py`** — Typer CLI: `helix run`, `helix status` (parse tree_search.md for best/current), `helix history` (scan tree_search.md + runs/), `helix stop` (write `.helix/stop` signal file), `helix config init|show|set`, `helix agents list|add|remove`.
 
8. **`templates/blank/`** — Minimal starter files: `goal.md` template, empty `tree_search.md`, sample `evaluate.sh`, default `helix.toml` + `config.yaml`.
 
9. **Tests** — pytest. Mock `subprocess.Popen` for agent tests. Use `tmp_path` for workspace tests. Test tree_search.md parsing. Test full loop with mock agents that write predictable idea.md/results.md.
 
### Phase 2 — Setup
 
1. **`helix/setup.py`** — Paragraph-first setup engine. User types free-form text. Call GPT-5.4 API to extract goal/criteria/boundary/evaluation/limitation. If info missing, LLM asks max 2-3 follow-ups. Write `goal.md`, empty `tree_search.md`, default `helix.toml`, `config.yaml` (prompt for API keys if not present). Save transcript to `setup_transcript.md`.
 
2. **`helix/setup_ui.py`** — Rich terminal: prompt for paragraph input, render LLM follow-up questions with markdown formatting, display generated `goal.md` for user review/approval, prompt for API keys.
 
3. **CLI**: `helix init [--path] [--setup-model]`, `helix setup [--path]`
 
### Phase 3 — Intelligence
 
- Smart context window management: if `tree_search.md` grows very large, summarize old dead-end branches and keep only active/frontier nodes in full detail
- Workspace templates for common domains (ML training, code generation, theorem proving)
- `helix replay` command: re-read `tree_search.md` if it gets corrupted

## Constraints

- Python 3.12+, `pathlib.Path`, modern typing
- `logging` for framework internals, `Rich` for user-facing output
- No database — parse `tree_search.md` and scan `runs/` for all state
- No git — `runs/` folder is the only history
- No dashboard — CLI only
- API keys in `./config.yaml` (per-workspace, gitignored)
- 1-hour hard timeout on child processes spawned by agents

## Key Decisions

1. **No database, no git, no dashboard.** Files are the only state: `tree_search.md` + `runs/` + `config.yaml` + `helix.toml`.
2. **tree_search.md is the single source of truth** for research progress. `[frontier]` markers double as the idea queue.
3. **Plan-first mandatory for Execute only.** Brainstorm and Reflect write directly.
4. **Code evolves linearly** — no revert mechanism. If a run breaks things, the next researcher fixes it. `runs/{id}/codes/` preserves what was written for reference.
5. **Full permissions** for all agents. `full_access_flag` configurable per CLI.
6. **config.yaml is per-workspace** (in project root, gitignored). No global config.
7. **Setup agent** = direct OpenAI API call (GPT-5.4). All other agents = CLI subprocesses.
8. **goal.md holds everything** — goal, criteria, boundary, evaluation, limitation in one file.
