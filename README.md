# Helix

Autonomous AI research framework. A master agent and researcher agent spiral upward through iterative experiments — each turn learning from the last — until success criteria are met.

## The Helix Loop

Each turn has 3 steps:

```
 Step 1: BRAINSTORM (Master)
 Read goal.md + tree_search.md → choose next branch → stage selection
                    │
                    ▼
 Step 2: EXECUTE (Researcher)
 Write plan first → rebuild from plan → implement → write results.md
                    │
                    ▼
 Step 3: REFLECT (Master)
 Read results → write reflect.md → update tree_search.md
```

The loop continues until success criteria are met or the maximum number of runs is reached.

During Brainstorm, the master reasons over the entire `tree_search.md` and writes a staged selection file to `.helix/brainstorm_selection.md`. Helix validates that choice, assigns the final run number, copies the staged brainstorm into `runs/{id}/idea.md`, and only then moves on to Execute.

Helix keeps `.helix/context_*.md` as the canonical prompt artifacts, but supported CLIs receive those prompts over stdin rather than argv so large contexts do not hit command-line size limits.

## Quick Start

```bash
# Install
uv sync

# Create a workspace
mkdir my-project
cd my-project

# Initialize it
helix init
# Choose either:
# - Conversational setup
# - Use existing local files

# Configure API keys
helix config set openai_api_key "sk-..."
helix config set anthropic_api_key "sk-ant-..."

# Review goal.md, master_agent.md, and researcher_agent.md
# Edit helix.toml if you want custom agents

# Run
helix run
```

`helix init --mode conversational` uses a setup LLM to draft the workspace from either a typed paragraph or a local Markdown file. `helix init --mode local` validates files you already placed in the project folder, reports what is missing or invalid, and offers to scaffold only the gaps. When `helix.toml` is created or regenerated, setup asks separately for master and researcher model IDs plus their provider-aware `thinking_level` values.

## CLI Commands

```bash
helix init [--path .] [--mode conversational|local] [--setup-model gpt-5.4]
helix setup [--path .] [--mode conversational|local] [--setup-model gpt-5.4]

helix run [--path .] [--max-runs 100]   # Run the helix loop
helix status [--path .]                  # Show best run + frontier
helix history [--path .] [--last N]      # Show run history
helix stop [--path .]                    # Stop after current step

helix config init [--path .]             # Create default config.yaml
helix config show [--path .]             # Display config (keys masked)
helix config set KEY VALUE [--path .]    # Set a config value

helix agents list [--path .]             # List configured agents
helix agents add --name NAME --role ROLE --cli CLI --model MODEL
helix agents remove --name NAME
```

## Workspace Structure

```
my-project/
├── helix.toml              # Agent configuration
├── config.yaml             # Optional API keys and defaults (gitignore this)
├── goal.md                 # Required: goal, criteria, boundary, evaluation, limitation
├── master_agent.md         # Required: human-authored instructions for the master agent
├── researcher_agent.md     # Required: human-authored instructions for the researcher agent
├── tree_search.md          # Required: research tree (master-written, evolving)
├── setup_transcript.md     # Conversational setup transcript (only if setup LLM was used)
├── evaluate.sh             # Optional evaluation starter
├── runs/                   # One folder per experiment
│   ├── 1/
│   │   ├── idea.md         # Written by master (step 1)
│   │   ├── plan.md         # Written by researcher (step 2, mandatory)
│   │   ├── results.md      # Written by researcher (step 2)
│   │   ├── reflect.md      # Written by master (step 3)
│   │   ├── codes/          # Code artifacts
│   │   ├── data/           # Data artifacts
│   │   └── logs/           # Stdout/stderr captures
│   ├── 2_1/                # Child run (tree number 2.1)
│   └── ...
├── .helix/                 # Framework working directory
│   ├── context_brainstorm.md
│   ├── brainstorm_selection.md  # Staged master output before run numbering
│   ├── context_execute_plan.md
│   ├── context_execute_run.md
│   └── context_reflect.md
└── reference/              # Optional reference documents
```

## Configuration

Helix considers a workspace initialized when these 5 core files exist and validate: `goal.md`, `master_agent.md`, `researcher_agent.md`, `helix.toml`, and `tree_search.md`.

### config.yaml

Per-workspace API keys and defaults. Should be gitignored.

```yaml
openai_api_key: "sk-..."
anthropic_api_key: "sk-ant-..."

defaults:
  master_cli: "claude"
  master_model: "claude-opus-4-6"
  master_thinking_level: "none"
  researcher_cli: "codex"
  researcher_model: "gpt-5.4"
  researcher_thinking_level: "none"
  agent_timeout_seconds: 3600
```

### helix.toml

Agent definitions. Must have exactly one master and at least one researcher.

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

Helix stores CLI-facing model IDs in `helix.toml`, not marketing labels. For Claude, use raw IDs like `claude-opus-4-6` or `claude-sonnet-4-6`.
`thinking_level` is a Helix field, but the underlying runtime words are provider-specific. Claude maps it to `--effort` and uses `low`, `medium`, `high`, or `max` (`max` is for Opus 4.6 only). Codex maps it to `-c model_reasoning_effort=...` and uses `low`, `medium`, `high`, or `xhigh`. `none` is a Helix abstraction that means “omit any explicit override.”

## Success Criteria

Helix auto-stops only when `goal.md` contains a fenced YAML block under `## Success Criteria`, and the researcher reports matching JSON metrics in `results.md`.

````markdown
## Success Criteria

```yaml
all:
  - metric: val_bpb
    op: "<"
    value: 1.05
  - metric: train_time_seconds
    op: "<="
    value: 300
```
````

After Execute, Helix evaluates the JSON metrics from `results.md`, still runs Reflect for that run, and then stops before the next run if the criteria passed.

## tree_search.md

The core knowledge structure. A tree of all experiments written by the master agent.

The master uses the full tree to decide the next run. `[frontier]` and `[active]` markers are informative cues for the master, not a framework-owned queue.

In the current MVP, Helix parses `tree_search.md` into a flat ordered list of nodes. `tree_search.md` remains the source of truth, and lineage is inferred from numbering like `2.1.3` rather than from a populated in-memory `children` structure.

```markdown
# Research Tree

1. [dead-end] Linear attention replacement
   idea: replace O(n²) attention with linear variant
   result: val_bpb 1.20 (+0.08 regression)
   reflect: attention quality matters more at this scale

2. [active] Muon optimizer
   idea: replace AdamW with Muon for faster convergence
   result: val_bpb 1.08 (−0.04 improvement)
   reflect: Muon clearly better, explore scheduling next

  2.1. [★ best] Muon + cosine annealing
       idea: add cosine LR schedule to Muon baseline
       result: val_bpb 1.05 (−0.03) ← BEST
       reflect: schedule helps significantly

3. [frontier] Flash Attention v3
   idea: (pending)
```

**Status markers:** `[★ best]` current best | `[active]` productive branch | `[dead-end]` don't revisit | `[frontier]` promising leaf to consider next

**Numbering:** `2.1.1` is a child of `2.1`, which is a child of `2`. Top-level numbers are independent research directions.

**Future implementation:** Not implemented yet, but a stronger version of Helix could parse `tree_search.md` into a real in-memory forest, populate `children` structurally, and optionally keep parent links or lookup maps for traversal. Even in that design, it would still be useful to keep a flattened ordered view for display, serialization, and simple scans.

## Development

```bash
uv sync
uv run pytest tests/ -v
```

## Tech Stack

Python 3.12+ | Pydantic | PyYAML | tomli/tomli-w | Typer | Rich | httpx
