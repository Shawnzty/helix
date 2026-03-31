# Helix

Autonomous AI research framework. A master agent and researcher agent spiral upward through iterative experiments — each turn learning from the last — until success criteria are met.

## The Helix Loop

Each turn has 3 steps:

```
 Step 1: BRAINSTORM (Master)
 Read goal.md + tree_search.md → decide branch → write idea.md
                    │
                    ▼
 Step 2: EXECUTE (Researcher)
 Write plan first → implement idea → run evaluation → write results.md
                    │
                    ▼
 Step 3: REFLECT (Master)
 Read results → write reflect.md → update tree_search.md
```

The loop continues until success criteria are met or the maximum number of runs is reached.

## Quick Start

```bash
# Install
uv sync

# Set up a workspace
cp templates/blank/* my-project/
cd my-project

# Configure API keys
helix config init
helix config set openai_api_key "sk-..."
helix config set anthropic_api_key "sk-ant-..."

# Edit goal.md with your research objective
# Edit helix.toml to customize agents (optional)

# Run
helix run
```

## CLI Commands

```bash
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
├── config.yaml             # API keys and defaults (gitignore this)
├── goal.md                 # Goal, criteria, boundary, evaluation, limitation
├── tree_search.md          # Research tree (master-written, evolving)
├── evaluate.sh             # Evaluation script
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
│   ├── context_execute.md
│   └── context_reflect.md
└── reference/              # Optional reference documents
```

## Configuration

### config.yaml

Per-workspace API keys and defaults. Should be gitignored.

```yaml
openai_api_key: "sk-..."
anthropic_api_key: "sk-ant-..."

defaults:
  master_cli: "claude"
  master_model: "claude-opus-4.6"
  researcher_cli: "codex"
  researcher_model: "gpt-5.4"
  agent_timeout_seconds: 3600
```

### helix.toml

Agent definitions. Must have exactly one master and at least one researcher.

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

## tree_search.md

The core knowledge structure. A tree of all experiments written by the master agent.

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

**Status markers:** `[★ best]` current best | `[active]` productive branch | `[dead-end]` don't revisit | `[frontier]` explore next

**Numbering:** `2.1.1` is a child of `2.1`, which is a child of `2`. Top-level numbers are independent research directions.

## Development

```bash
uv sync
uv run pytest tests/ -v
```

## Tech Stack

Python 3.12+ | Pydantic | PyYAML | tomli/tomli-w | Typer | Rich | httpx
