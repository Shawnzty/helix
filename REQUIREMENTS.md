# Helix

Autonomous AI research framework. A master agent and researcher agent spiral upward through iterative experiments — each turn learning from the last — until success criteria are met.

Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch) and [lidangzzz/goal-driven](https://github.com/lidangzzz/goal-driven).

---

## 1. The Helix Loop

Each turn has 3 steps:

```
 Step 1: BRAINSTORM (Master)
 Read goal.md + tree_search.md → web search or read reference documents if necessary → choose next branch → stage selection
                    │
                    ▼
 Step 2: EXECUTE (Researcher)
 Write plan first → rebuild context from plan → implement → write results.md
                    │
                    ▼
 Step 3: REFLECT (Master)
 Read results → write reflect.md → update tree_search.md
```

### Step 1 — Brainstorm (Master)

Master reads `goal.md` + `tree_search.md`, and if necessary searches the web or reads reference documents. It reasons over the entire tree, decides whether to deepen an existing non-dead-end branch or start a new top-level direction, and writes a staged brainstorm file to `.helix/brainstorm_selection.md`.

That staged file must begin with machine-readable YAML front matter describing the branch choice:

```yaml
---
mode: child
parent: "2.1"
title: "Try the warmup variant"
rationale: "Best next move based on the current tree"
---
```

Helix validates the selection, assigns the final `run_id`, and then materializes the staged brainstorm into `runs/{run_id}/idea.md`.

### Step 2 — Execute (Researcher)

Execute is split into two researcher invocations:

1. **Plan step** — Helix inlines `researcher_agent.md` + `goal.md` + `idea.md`. The researcher writes `runs/{run_id}/plan.md` with exact files to create or modify, commands to run, order of operations, expected outputs, and checkpoints.
2. **Run step** — Helix rebuilds the context and inlines `researcher_agent.md` + `plan.md`. The researcher executes the plan, writes code, runs evaluation, and produces `results.md`.

Writes `runs/{run_id}/results.md` with: what was done, metrics (JSON), observations.

Helix checks success by reading a fenced YAML block under `## Success Criteria` in `goal.md` and comparing it against the top-level JSON metrics in `results.md`. If the criteria pass, Helix still runs Reflect for that run and then stops before the next run.

**1-hour timeout**: If any single program execution exceeds 1 hour, the framework kills it. The researcher's context instructs: "If a program would take longer than 1 hour, break it into smaller steps or find a faster approach. Check intermediate results and report partial progress."

### Step 3 — Reflect (Master)

Master reads `idea.md` + `results.md`. Then:

1. Writes `runs/{run_id}/reflect.md` with reasoning
2. Updates `tree_search.md` — add new node to the tree with status, update flags (best/active/dead-end/frontier), update metrics

---

## 2. tree_search.md

The core knowledge structure. A tree of all runs — each node is one experiment with a 1-sentence summary for idea, result, and reflection. The master writes this directly.

### Format

```markdown
# Research Tree

1. [dead-end] Linear attention replacement
   idea: replace O(n²) attention with linear variant to increase throughput
   result: val_bpb 1.20 (+0.08 regression)
   reflect: attention quality matters more than throughput at this scale

2. [active] Muon optimizer
   idea: replace AdamW with Muon for faster convergence
   result: val_bpb 1.08 (−0.04 improvement)
   reflect: Muon clearly better, explore scheduling next

  2.1. [active] Muon + cosine annealing
       idea: add cosine LR schedule to Muon baseline
       result: val_bpb 1.05 (−0.03)
       reflect: schedule helps, try warmup variants

    2.1.1. [★ best] Muon + cosine + warmup
           idea: add 500-step linear warmup
           result: val_bpb 1.02 (−0.03) ← BEST
           reflect: warmup critical for stability

    2.1.2. [dead-end] Muon + cosine + linear decay
           idea: replace cosine tail with linear decay
           result: val_bpb 1.07 (+0.02)
           reflect: linear decay too aggressive

  2.2. [dead-end] Muon + larger batch (64→128)
       idea: double batch size to use more GPU
       result: val_bpb 1.10 (+0.02)
       reflect: diminishing returns, fewer steps hurt more

3. [frontier] Flash Attention v3 on 2.1.1 baseline
   idea: (pending)
   result: (pending)
   reflect: (pending)
```

### Status Markers

| Marker | Meaning |
|--------|---------|
| `[★ best]` | Current best result across all branches |
| `[active]` | Has children, part of a productive branch |
| `[dead-end]` | Tried, didn't help, don't revisit |
| `[frontier]` | Promising leaf the master may choose to explore next |

### Numbering

The number encodes lineage: `2.1.1` is a child of `2.1`, which is a child of `2`. Top-level numbers (1, 2, 3) are independent research directions. Deeper numbers refine a parent experiment.

### Why This Format

- **Agents read it natively** — plain text, no parsing
- **Master edits it directly** — just write text
- **Human-scannable** — see the full research landscape at a glance
- **Numbering = parentage** — no need for separate ID fields
- **Dead ends visible** — agents won't repeat failed approaches

---

## 3. Setup

`helix init` supports two setup modes:
- **Conversational** — draft the workspace from a typed paragraph or local Markdown file with a setup LLM
- **Local files** — validate files already present in the project folder and scaffold only the missing or invalid ones

Helix treats these 5 files as the initialization contract: `goal.md`, `master_agent.md`, `researcher_agent.md`, `helix.toml`, and `tree_search.md`.
Whenever setup creates or replaces `helix.toml`, it should ask separately for the master and researcher model IDs and provider-aware `thinking_level` values.

### 3.1 Paragraph Or Markdown File

User provides their task either as free-form text or by loading a local `.md` file. The setup LLM (GPT-5.4 by default) auto-extracts all fields. Only asks follow-up questions for genuinely missing info (max 2–3 questions).

```
$ helix init

Choose requirement input source:
1. Type requirement as a paragraph
2. Load requirement from a local Markdown file

Describe your research task:
> I want to optimize train.py to get val_bpb below 1.05 on a single
  H100 within 5 minutes. Don't touch prepare.py or the tokenizer.

→ GPT-5.4 extracts goal (the objective), criteria (machine-checkable success conditions), boundary (what agents can/cannot modify), evaluation (how to measure results), limitation (hardware/time/resource constraints).
→ Asks 1-2 follow-ups if anything is ambiguous
→ Generates `goal.md`, `master_agent.md`, `researcher_agent.md`, `tree_search.md`, and `helix.toml`
→ User reviews and approves
```

### 3.2 Local Files Mode

If the user already has workspace files, `helix init --mode local` or `helix setup --mode local` should:
- detect which core files are valid, missing, or invalid
- report the audit result in the terminal
- offer to scaffold only missing files from starter templates
- offer to repair invalid files after confirmation, preserving a `.bak` copy before replacement

### 3.3 Research Memory Files

| File | Source | Purpose |
|------|--------|---------|
| `goal.md` | Setup (static) | including goal, criteria, boundary, evaluation, limitation |
| `tree_search.md` | Master (evolving) | Tree of all runs with summaries |
| `setup_transcript.md` | Setup (static) | Full setup conversation |

`goal.md` success criteria must be machine-checkable. The `## Success Criteria` section should contain a fenced YAML block like:

```yaml
all:
  - metric: val_bpb
    op: "<"
    value: 1.05
  - metric: train_time_seconds
    op: "<="
    value: 300
```

### 3.4 Config

```yaml
openai_api_key: "sk-..."
anthropic_api_key: "sk-ant-..."

defaults:
  setup_model: "gpt-5.4"
  master_cli: "claude"
  master_model: "claude-opus-4-6"
  master_thinking_level: "none"
  researcher_cli: "codex"
  researcher_model: "gpt-5.4"
  researcher_thinking_level: "none"
  claude_full_access_flag: "--dangerously-skip-permissions"
  codex_full_access_flag: "--dangerously-bypass-approvals-and-sandbox"
  agent_timeout_seconds: 3600
```

Resolution order: CLI flags → `helix.toml` → `config.yaml` → built-in defaults.

---

## 4. Multi-Agent Architecture

### 4.1 Defaults

| Role | CLI | Model | Steps |
|------|-----|-------|-------|
| **Master** | Claude Code | claude-opus-4-6 | 1 (Brainstorm) + 3 (Reflect) |
| **Researcher** | Codex CLI | gpt-5.4 | 2 (Execute) |

**All agents run with full computer permissions.** They can read/write files, run commands, access the network, install packages. No permission prompts.

Permission flags by CLI:
- Claude Code: `--dangerously-skip-permissions`
- Codex CLI: `--dangerously-bypass-approvals-and-sandbox`
- Other CLIs: configurable via `full_access_flag` in agent config

### 4.2 Custom Agents

```bash
helix agents add --name explorer --role researcher \
  --cli claude --model claude-sonnet-4 \
  --description "High-risk/high-reward unconventional ideas"
```

### 4.3 Agent Config in helix.toml

```toml
[[agents]]
name = "master"
role = "master"
cli = "claude"
model = "claude-opus-4-6"
full_access_flag = "--dangerously-skip-permissions"
description = "Brainstorms ideas and reflects on results"
thinking_level = "high"

[[agents]]
name = "researcher"
role = "researcher"
cli = "codex"
model = "gpt-5.4"
full_access_flag = "--dangerously-bypass-approvals-and-sandbox"
description = "Executes experiments, writes code, runs evaluation"
thinking_level = "none"
```

### 4.4 Agent Invocation

```bash
# Claude Code
claude --dangerously-skip-permissions --model claude-opus-4-6 --effort high -p < .helix/context_brainstorm.md

# Codex CLI
codex exec --dangerously-bypass-approvals-and-sandbox --model gpt-5.4 -c model_reasoning_effort="xhigh" - < .helix/context_execute_run.md
```

Helix stores raw CLI model IDs in config. `thinking_level` is a Helix field, but providers use different underlying words: Claude maps it to `--effort` and uses `low`, `medium`, `high`, or `max` (`max` is for Opus 4.6 only), while Codex maps it to `-c model_reasoning_effort=...` and uses `low`, `medium`, `high`, or `xhigh`. `none` is a Helix-level sentinel meaning “omit any explicit override.”

### 4.5 Plan-First

**Mandatory for Step 2 (Execute) only.** The researcher must write `runs/{run_id}/plan.md` in the first Execute invocation before Helix starts the second Execute invocation. This makes execution transparent and lets Helix narrow the run-time context to the concrete plan.

---

## 5. Runs Folder

Every run gets its own folder. The run_id matches the tree numbering (dots replaced with underscores for filesystem compatibility).

Before a run folder exists, Brainstorm writes its staged selection to `.helix/brainstorm_selection.md`. Helix only creates `runs/{run_id}/` after validating that staged selection and assigning the final number from the chosen parent or top-level slot.

```
runs/
├── 1/
│   ├── idea.md              # Written by master (step 1)
│   ├── plan.md              # Written by researcher (step 2, mandatory)
│   ├── results.md           # Written by researcher (step 2)
│   ├── reflect.md           # Written by master (step 3)
│   ├── codes/               # Any code written/modified during execution
│   ├── data/                # Any data downloaded/generated
│   └── logs/                # Stdout/stderr captures
│   └── ...
├── 2/
│   ├── idea.md
│   ├── plan.md
│   ├── results.md
│   ├── reflect.md
│   ├── codes/
│   └── ...
├── 2_1/
│   └── ...
├── 2_1_1/
│   └── ...
└── 3/
    ├── idea.md
    └── ...
```

The `runs/` folder is the detailed archive. `tree_search.md` is the summary view. Together they give both the big picture and the full details.

---

## 6. Context Assembly

| Context File | Agent | Contains | Plan Required? |
|-------------|-------|----------|---------------|
| `context_brainstorm.md` | Master | `master_agent.md` + `goal.md` + `tree_search.md` + web search or read reference documents if necessary. Instruction: reason over the full tree, write `.helix/brainstorm_selection.md` with YAML front matter plus the idea writeup. | No |
| `context_execute_plan.md` | Researcher | `researcher_agent.md` + `goal.md` + `idea.md`. Instruction: write `plan.md` only, do not implement yet. | No |
| `context_execute_run.md` | Researcher | `researcher_agent.md` + `plan.md`. Instruction: execute the plan, write `results.md`, read other files on demand if needed. | **Yes** |
| `context_reflect.md` | Master | `master_agent.md` + `goal.md` + `idea.md` + `plan.md` + `results.md` + success summary + `tree_search.md`. Instruction: write `reflect.md`, update `tree_search.md`. | No |

`master_agent.md` and `researcher_agent.md` are human-authored workspace files. Helix reads them into the corresponding contexts and never overwrites them.

---

## 7. Workspace Structure

```
my-project/
├── helix.toml
├── evaluate.sh
├── goal.md                     # Static
├── master_agent.md             # Static, human-authored instructions for master steps
├── researcher_agent.md         # Static, human-authored instructions for researcher steps
├── setup_transcript.md         # Static
├── tree_search.md              # Evolving (master-written)
│ 
├── runs/                           # One folder per run
│   ├── 1/
│   │   ├── idea.md
│   │   ├── plan.md
│   │   ├── results.md
│   │   ├── reflect.md
│   │   ├── codes/
│   │   ├── data/
│   │   └── logs/
│   ├── 2_1_1/
│   │   └── ...
│   └── ...
├── .helix/
│   ├── context_brainstorm.md       # Debug: last context
│   ├── brainstorm_selection.md     # Staged brainstorm output before run assignment
│   ├── context_execute_plan.md
│   ├── context_execute_run.md
│   └── context_reflect.md
├── reference/                 # Optional reference documents for agents to read
│   ├── reference1.pdf
│   └── ...
└── <user's project files>
```

---

## 8. CLI

```bash
helix config init                   # Create ~/.helix/config.yaml
helix config show                   # Display config (keys masked)
helix config set KEY VALUE

helix init [--path .] [--mode conversational|local] [--setup-model gpt-5.4]
helix setup [--path .] [--mode conversational|local] [--setup-model gpt-5.4]

helix run [--path .]
helix status [--path .]
helix history [--path .] [--last N]
helix stop [--path .]

helix agents list [--path .]
helix agents add --name NAME --role ROLE --cli CLI --model MODEL
helix agents remove --name NAME

```
---

## 9. Tech Stack
- **Python 3.12+** — modern typing, `pathlib.Path` everywhere
- **PyYAML** — parse `config.yaml`
- **tomli / tomli_w** — parse and write `helix.toml`
- **Pydantic** — config validation, data models
- **Typer** — CLI framework
- **Rich** — terminal UI for setup chat, status display, progress
- **httpx** — async HTTP for LLM API calls (setup agent)
- **subprocess** — agent process management (spawn, timeout, kill, capture output)
- **Package management**: uv + `pyproject.toml`.
---

## 10. Implementation Phases
 
### Phase 1 — Core Loop (MVP)
 
Build and test in this order:
 
1. **`helix/config.py`** — Parse `config.yaml` (PyYAML + Pydantic) and `helix.toml` (tomli + Pydantic). Models: `GlobalConfig`, `WorkspaceConfig`, `AgentConfig`. Validation: exactly one master, ≥1 researcher. Config resolution: CLI → toml → yaml → defaults.
 
2. **`helix/models.py`** — Pydantic models: `RunState` (id, status, parent_id, tree_number), `AgentRun` (stdout, stderr, exit_code, duration), `ParsedResults` (metrics dict, observations), success-check models, and master branch-selection models.
 
3. **`helix/agents.py`** — Spawn agent CLI as subprocess with full permissions. Keep `.helix/context_*.md` as the canonical prompt artifacts, but use stdin-first prompt delivery for supported CLIs and argv fallback for unknown ones. Capture stdout/stderr to `runs/{id}/logs/`. Enforce timeout (SIGTERM → SIGKILL after 10s). Return `AgentRun`.
 
4. **`helix/context.py`** — Build Brainstorm, Execute Plan, Execute Run, and Reflect context markdown files by reading and concatenating role-specific human instruction files, research memory files, and run-specific files. Write them to `.helix/context_*.md`.
 
5. **`helix/runs.py`** — Run folder management: `create_run_folder(run_id)` (creates `runs/{id}/` with subdirs), `parse_results(run_id)` (read `results.md`, extract JSON metrics block), `parse_tree_search()` (read `tree_search.md`, return list of nodes with status/numbering), `get_best_run()`, `get_frontier_runs()`, and parent-oriented numbering helpers.
 
6. **`helix/loop.py`** — The helix:
   ```
   while not criteria_met and run_count < max_runs:
       parse success criteria from goal.md

       # Step 1: Brainstorm
       build context_brainstorm.md
       spawn master → web search or read reference documents if necessary → writes .helix/brainstorm_selection.md
       validate YAML branch choice against tree_search.md
       assign run_id from the chosen parent or top-level slot
       create_run_folder(run_id)
       materialize runs/{id}/idea.md from staged brainstorm output

       # Step 2: Execute
       build context_execute_plan.md
       spawn researcher → writes plan.md only
       if plan.md exists and plan step exited cleanly:
           build context_execute_run.md
           spawn researcher → implements, writes results.md
       else:
           skip Execute Run and still continue to Reflect
       parse metrics from results.md
       check criteria
       if criteria passed:
           still run reflect, then stop before next run

       # Step 3: Reflect
       build context_reflect.md
       spawn master → writes reflect.md, updates tree_search.md
   ```
   Handle: SIGINT/SIGTERM graceful shutdown (finish current step, then stop), agent crash recovery (log error, mark run as failed in tree, continue to next), 1-hour child process timeout.
 
7. **`helix/cli.py`** — Typer CLI: `helix run`, `helix status` (parse tree_search.md for best/current), `helix history` (scan tree_search.md + runs/), `helix stop` (write `.helix/stop` signal file), `helix config init|show|set`, `helix agents list|add|remove`.
 
8. **`templates/blank/`** — Minimal starter files: `goal.md` template, `master_agent.md`, `researcher_agent.md`, empty `tree_search.md`, sample `evaluate.sh`, default `helix.toml` + `config.yaml`.
 
9. **Tests** — pytest. Mock `subprocess.Popen` for agent tests. Use `tmp_path` for workspace tests. Test tree_search.md parsing. Test staged brainstorm selection parsing/validation. Test full loop with mock agents that write predictable staged selections, idea.md/results.md, and reflect.md.
 
### Phase 2 — Setup
 
1. **`helix/setup.py`** — Conversational setup engine. User either types free-form text or loads a local Markdown file. Call GPT-5.4 API to extract goal/criteria/boundary/evaluation/limitation. If info missing, LLM asks max 2-3 follow-ups. Write `goal.md`, empty `tree_search.md`, default `helix.toml`, `config.yaml` (prompt for API keys if not present). Save transcript to `setup_transcript.md`.
 
2. **`helix/setup_ui.py`** — Rich terminal: prompt for requirement source (paragraph or Markdown file), render LLM follow-up questions with markdown formatting, display generated `goal.md` for user review/approval, prompt for API keys.
 
3. **CLI**: `helix init [--path] [--setup-model]`, `helix setup [--path]`
 
### Phase 3 — Intelligence
 
- Smart context window management: if `tree_search.md` grows very large, summarize old dead-end branches and keep only active/frontier nodes in full detail
- Workspace templates for common domains (ML training, code generation, theorem proving)
- `helix replay` command: re-read `tree_search.md` if it gets corrupted

---

## 11. Repository Structure

```
helix/
├── REQUIREMENTS.md
├── CLAUDE.md
├── AGENTS.md
├── README.md
├── pyproject.toml
├── helix/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py          # Global yaml + workspace toml
│   ├── models.py
│   ├── llm.py             # Anthropic + OpenAI client
│   ├── setup.py           # Conversational setup engine (paragraph or Markdown file)
│   ├── loop.py            # 3-step helix loop
│   ├── agents.py          # Subprocess management (full permissions)
│   ├── context.py         # Context builder (3 types)
│   ├── setup_ui.py        # Setup UI for terminal
│   └── run.py             # handle all the file operations around the runs/ folder and tree_search.md parsing.
├── templates/
│   ├── blank/
│   ├── ml-training/
│   └── code-generation/
└── tests/
```
