# Helix

Autonomous AI research framework. A master agent and researcher agent spiral upward through iterative experiments — each turn learning from the last — until success criteria are met.

Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch) and [lidangzzz/goal-driven](https://github.com/lidangzzz/goal-driven).

---

## 1. The Helix Loop

Each turn has 3 steps:

```
 Step 1: BRAINSTORM (Master)
 Read goal.md + tree_search.md → web search or read reference documents if necessary → decide branch → write idea.md
                    │
                    ▼
 Step 2: EXECUTE (Researcher)
 Write plan first → implement idea → run evaluation → write results.md
                    │
                    ▼
 Step 3: REFLECT (Master)
 Read results → write reflect.md → update tree_search.md
```

### Step 1 — Brainstorm (Master)

Master reads `goal.md`+`tree_search.md`, and if necessary searches the web or reads reference documents. Decides whether to deepen an existing branch or start a new top-level direction. Writes `runs/{run_id}/idea.md` with reasoning and logic.

### Step 2 — Execute (Researcher)

**Plan first (mandatory)**: Researcher writes `runs/{run_id}/plan.md` before doing anything — exact files to create or modify, commands to run, order of operations, expected outputs.

Then executes: writes code, downloads resources, fine-tunes hyperparameters, runs evaluation. All generated artifacts go into `runs/{run_id}/` (codes/, data/, logs/, etc.).

Writes `runs/{run_id}/results.md` with: what was done, metrics (JSON), observations.

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
| `[frontier]` | Leaf node worth exploring next |

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

### 3.1 Paragraph-First

User describes their task in free-form text. The setup LLM (GPT-5.4 by default) auto-extracts all fields. Only asks follow-up questions for genuinely missing info (max 2–3 questions).

```
$ helix init

Describe your research task:
> I want to optimize train.py to get val_bpb below 1.05 on a single
  H100 within 5 minutes. Don't touch prepare.py or the tokenizer.

→ GPT-5.4 extracts goal (the objective), criteria (machine-checkable success conditions), boundary (what agents can/cannot modify), evaluation (how to measure results), limitation (hardware/time/resource constraints).
→ Asks 1-2 follow-ups if anything is ambiguous
→ Generates research_memory/ files + helix.toml
→ User reviews and approves
```

### 3.2 Research Memory Files

| File | Source | Purpose |
|------|--------|---------|
| `goal.md` | Setup (static) | including goal, criteria, boundary, evaluation, limitation |
| `tree_search.md` | Master (evolving) | Tree of all runs with summaries |
| `setup_transcript.md` | Setup (static) | Full setup conversation |

### 3.3 Config

```yaml
openai_api_key: "sk-..."
anthropic_api_key: "sk-ant-..."

defaults:
  setup_model: "gpt-5.4"
  master_cli: "claude"
  master_model: "claude-opus-4.6"
  researcher_cli: "codex"
  researcher_model: "gpt-5.4"
  claude_full_access_flag: "--dangerously-skip-permissions"
  codex_full_access_flag: "--dangerously-bypass-approvals-and-sandbox"
  codex_reasoning_level: "high"  # none | low | medium | high
  agent_timeout_seconds: 3600
```

Resolution order: CLI flags → `helix.toml` → `config.yaml` → built-in defaults.

---

## 4. Multi-Agent Architecture

### 4.1 Defaults

| Role | CLI | Model | Steps |
|------|-----|-------|-------|
| **Master** | Claude Code | claude-opus-4.6 | 1 (Brainstorm) + 3 (Reflect) |
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
model = "claude-opus-4.6"
full_access_flag = "--dangerously-skip-permissions"
description = "Brainstorms ideas and reflects on results"

[[agents]]
name = "researcher"
role = "researcher"
cli = "codex"
model = "gpt-5.4"
full_access_flag = "--dangerously-bypass-approvals-and-sandbox"
description = "Executes experiments, writes code, runs evaluation"
```

### 4.4 Agent Invocation

```bash
# Claude Code
claude --dangerously-skip-permissions -p "$(cat .helix/context_{step}.md)"

# Codex CLI
codex --dangerously-bypass-approvals-and-sandbox -q "$(cat .helix/context_{step}.md)"
```

### 4.5 Plan-First

**Mandatory for Step 2 (Execute) only.** The researcher must write `runs/{run_id}/plan.md` before making any changes. This makes execution transparent and debuggable.

---

## 5. Runs Folder

Every run gets its own folder. The run_id matches the tree numbering (dots replaced with underscores for filesystem compatibility).

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
| `context_brainstorm.md` | Master | `goal.md` + `tree_search.md` + web search or read reference documents if necessary. Instruction: pick a branch (deepen or new), write `runs/{id}/idea.md`. | No |
| `context_execute.md` | Researcher | `idea.md` + research memory (goal, criteria, boundary, evaluation, limitation). Instruction: **write plan.md first**, then implement, run eval, write `results.md`. 1-hour per-program timeout. | **Yes** |
| `context_reflect.md` | Master | `results.md` + `idea.md` + `tree_search.md`. Instruction: write `reflect.md`, update `tree_search.md`. | No |

`CLAUDE.md` and `AGENTS.md` are auto-generated at workspace root by concatenating all research memory files.

---

## 7. Workspace Structure

```
my-project/
├── helix.toml
├── evaluate.sh
├── goal.md                     # Static
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
│   ├── context_execute.md
│   └── context_reflect.md
├── CLAUDE.md                       # Auto-generated
├── AGENTS.md                       # Auto-generated
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

helix init [--path .] [--setup-model gpt-5.4]
helix setup [--path .]              # Re-run setup

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
│   ├── setup.py           # Paragraph-first setup engine
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
