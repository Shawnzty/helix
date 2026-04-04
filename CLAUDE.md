# CLAUDE.md — Helix

Read `REQUIREMENTS.md` for the full spec. This file is the build guide.

## Architecture

3-step helix: **Brainstorm** (master reasons over the full tree and stages a branch selection) → **Execute** (researcher plan step, then researcher run step with a rebuilt context) → **Reflect** (master → `reflect.md` + update `tree_search.md`).

No database. No git. No dashboard. All state lives in files: `tree_search.md` (master-written research tree), `runs/` (per-run archive), `config.yaml` (API keys), `helix.toml` (agent config).

All agents are CLI subprocesses with full computer permissions. The setup agent is the only direct LLM API call (GPT-5.4).

## Build Order
 
### Phase 1 — Core Loop (MVP)
 
Build and test in this order:
 
1. **`helix/config.py`** — Parse `config.yaml` (PyYAML + Pydantic) and `helix.toml` (tomli + Pydantic). Models: `GlobalConfig`, `WorkspaceConfig`, `AgentConfig`. Validation: exactly one master, ≥1 researcher. Config resolution: CLI → toml → yaml → defaults.
 
2. **`helix/models.py`** — Pydantic models: `RunState` (id, status, parent_id, tree_number), `AgentRun` (stdout, stderr, exit_code, duration), `ParsedResults` (metrics dict, observations), and success-checking models for parsed criteria and evaluations.
 
3. **`helix/agents.py`** — Spawn agent CLI as subprocess with full permissions. Keep `.helix/context_*.md` as canonical prompt artifacts, but deliver prompt text via stdin for supported CLIs and use argv fallback for unknown ones. Capture stdout/stderr to `runs/{id}/logs/`. Enforce timeout (SIGTERM → SIGKILL after 10s). Return `AgentRun`.
 
4. **`helix/context.py`** — Build Brainstorm, Execute Plan, Execute Run, and Reflect context markdown files by reading and concatenating role-specific human instruction files, research memory files, and run-specific files. Write them to `.helix/context_*.md`.
 
5. **`helix/runs.py`** — Run folder management: `create_run_folder(run_id)` (creates `runs/{id}/` with subdirs), `parse_results(run_id)` (read `results.md`, extract JSON metrics block), `parse_tree_search()` (read `tree_search.md`, return list of nodes with status/numbering), `get_best_run()`, `get_frontier_runs()`, and helpers to validate parents and assign the next child or top-level number.
 
6. **`helix/loop.py`** — The helix:
   ```
   while not criteria_met and run_count < max_runs:
       parse success criteria from goal.md

       # Step 1: Brainstorm
       build context_brainstorm.md
       spawn master → web search or read reference documents if necessary → writes .helix/brainstorm_selection.md
       validate YAML branch choice against tree_search.md
       assign run_id from the selected parent or top-level slot
       create_run_folder(run_id)
       materialize runs/{id}/idea.md from the staged brainstorm output

       # Step 2: Execute
       build context_execute_plan.md
       spawn researcher → writes plan.md only
       if plan.md exists and plan step exited cleanly:
           build context_execute_run.md
           spawn researcher → implements, writes results.md
           parse metrics from results.md
           check criteria
           if criteria passed:
               still run reflect, then stop before next run
       else:
           skip Execute Run and still continue to Reflect
 
       # Step 3: Reflect
       build context_reflect.md
       spawn master → writes reflect.md, updates tree_search.md
   ```
   Handle: SIGINT/SIGTERM graceful shutdown (finish current step, then stop), agent crash recovery (log error, mark run as failed in tree, continue to next), 1-hour child process timeout.
 
7. **`helix/cli.py`** — Typer CLI: `helix run`, `helix status` (parse tree_search.md for best/current), `helix history` (scan tree_search.md + runs/), `helix stop` (write `.helix/stop` signal file), `helix config init|show|set`, `helix agents list|add|remove`.
 
8. **`templates/blank/`** — Minimal starter files: `goal.md` template, `master_agent.md`, `researcher_agent.md`, empty `tree_search.md`, sample `evaluate.sh`, default `helix.toml` + `config.yaml`.
 
9. **Tests** — pytest. Mock `subprocess.Popen` for agent tests. Use `tmp_path` for workspace tests. Test tree_search.md parsing. Test staged brainstorm selection parsing/validation. Test stdin prompt transport for supported CLIs plus argv fallback. Test full loop with mock agents that write predictable staged selections, plan.md/results.md, and reflect.md.
 
### Phase 2 — Setup
 
1. **`helix/setup.py`** — Dual-mode setup engine. Conversational mode calls GPT-5.4 to draft `goal.md`, `master_agent.md`, and `researcher_agent.md`, scaffolds `tree_search.md` and `helix.toml`, and saves `setup_transcript.md`. Local mode audits the 5-file init contract (`goal.md`, `master_agent.md`, `researcher_agent.md`, `helix.toml`, `tree_search.md`) and offers targeted scaffolding or repair with `.bak` backups.
 
2. **`helix/setup_ui.py`** — Rich terminal: mode picker, workspace audit table, requirement-source picker (typed paragraph or Markdown file), follow-up questions, review/approval screens, and config/API-key prompts.
 
3. **CLI**: `helix init [--path] [--mode conversational|local] [--setup-model]`, `helix setup [--path] [--mode conversational|local] [--setup-model]`
 
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
2. **tree_search.md is the single source of truth** for research progress. The master reasons over the full tree; `[frontier]` markers are informative hints, not a framework-owned queue.
3. **Plan-first mandatory for Execute only.** Brainstorm stages a selection file, Execute writes plan/results, Reflect writes directly.
4. **Code evolves linearly** — no revert mechanism. If a run breaks things, the next researcher fixes it. `runs/{id}/codes/` preserves what was written for reference.
5. **Full permissions** for all agents. `full_access_flag` configurable per CLI.
6. **config.yaml is per-workspace** (in project root, gitignored). No global config.
7. **Setup agent** = direct OpenAI API call (GPT-5.4). All other agents = CLI subprocesses.
8. **goal.md holds everything** — goal, YAML success criteria, boundary, evaluation, limitation in one file.
