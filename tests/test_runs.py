"""Tests for helix/runs.py."""

from helix.runs import (
    create_run_folder,
    get_best_run,
    get_frontier_runs,
    next_run_id,
    parse_results,
    parse_tree_search,
)

SAMPLE_TREE = """# Research Tree

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
"""


class TestCreateRunFolder:
    def test_creates_subdirs(self, tmp_path):
        run_dir = create_run_folder(tmp_path, "2_1")
        assert (run_dir / "codes").is_dir()
        assert (run_dir / "data").is_dir()
        assert (run_dir / "logs").is_dir()

    def test_idempotent(self, tmp_path):
        create_run_folder(tmp_path, "1")
        create_run_folder(tmp_path, "1")  # No error


class TestParseResults:
    def test_parse_json_metrics(self, tmp_path):
        run_dir = tmp_path / "runs" / "1"
        run_dir.mkdir(parents=True)
        (run_dir / "results.md").write_text("""# Results

Done training.

```json
{"val_bpb": 1.05, "train_loss": 0.42}
```

Model converged well.
""")
        parsed = parse_results(tmp_path, "1")
        assert parsed.metrics["val_bpb"] == 1.05
        assert parsed.metrics["train_loss"] == 0.42
        assert "converged" in parsed.observations

    def test_missing_results(self, tmp_path):
        parsed = parse_results(tmp_path, "999")
        assert parsed.metrics == {}

    def test_no_json_block(self, tmp_path):
        run_dir = tmp_path / "runs" / "1"
        run_dir.mkdir(parents=True)
        (run_dir / "results.md").write_text("# Results\nNo metrics.")
        parsed = parse_results(tmp_path, "1")
        assert parsed.metrics == {}
        assert "No metrics" in parsed.observations


class TestParseTreeSearch:
    def test_parse_sample_tree(self, tmp_path):
        (tmp_path / "tree_search.md").write_text(SAMPLE_TREE)
        nodes = parse_tree_search(tmp_path)
        assert len(nodes) == 7

        # Check first node
        assert nodes[0].number == "1"
        assert nodes[0].status == "dead-end"
        assert "Linear attention" in nodes[0].title

        # Check nested node
        node_211 = next(n for n in nodes if n.number == "2.1.1")
        assert "best" in node_211.status
        assert "warmup" in node_211.idea

        # Check frontier
        node_3 = next(n for n in nodes if n.number == "3")
        assert node_3.status == "frontier"

    def test_empty_tree(self, tmp_path):
        (tmp_path / "tree_search.md").write_text("# Research Tree\n\n")
        nodes = parse_tree_search(tmp_path)
        assert nodes == []

    def test_missing_file(self, tmp_path):
        nodes = parse_tree_search(tmp_path)
        assert nodes == []


class TestGetBestRun:
    def test_finds_best(self, tmp_path):
        (tmp_path / "tree_search.md").write_text(SAMPLE_TREE)
        nodes = parse_tree_search(tmp_path)
        best = get_best_run(nodes)
        assert best is not None
        assert best.number == "2.1.1"

    def test_no_best(self, tmp_path):
        (tmp_path / "tree_search.md").write_text("""# Research Tree

1. [active] Test
   idea: test
   result: test
   reflect: test
""")
        nodes = parse_tree_search(tmp_path)
        assert get_best_run(nodes) is None


class TestGetFrontierRuns:
    def test_finds_frontiers(self, tmp_path):
        (tmp_path / "tree_search.md").write_text(SAMPLE_TREE)
        nodes = parse_tree_search(tmp_path)
        frontiers = get_frontier_runs(nodes)
        assert len(frontiers) == 1
        assert frontiers[0].number == "3"


class TestNextRunId:
    def test_first_run(self, tmp_path):
        (tmp_path / "tree_search.md").write_text("# Research Tree\n\n")
        assert next_run_id(tmp_path) == "1"

    def test_next_top_level(self, tmp_path):
        (tmp_path / "tree_search.md").write_text(SAMPLE_TREE)
        assert next_run_id(tmp_path) == "4"

    def test_next_child(self, tmp_path):
        (tmp_path / "tree_search.md").write_text(SAMPLE_TREE)
        # 2.1 has children 2.1.1 and 2.1.2, so next is 2.1.3
        assert next_run_id(tmp_path, parent_id="2_1") == "2_1_3"

    def test_first_child(self, tmp_path):
        (tmp_path / "tree_search.md").write_text(SAMPLE_TREE)
        # Node 1 has no children, so first child is 1.1
        assert next_run_id(tmp_path, parent_id="1") == "1_1"
