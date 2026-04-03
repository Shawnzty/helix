# Goal

<!-- Describe the objective of your research -->

## Success Criteria

<!-- Machine-checkable conditions for success -->
<!-- Provide a fenced YAML block. Helix evaluates these rules against the JSON metrics in results.md. -->
```yaml
all:
  - metric: val_bpb
    op: "<"
    value: 1.05
  - metric: train_time_seconds
    op: "<="
    value: 300
```

## Boundary

<!-- What can and cannot be modified -->
<!-- Example: Only modify train.py. Do not touch prepare.py or the tokenizer. -->

## Evaluation

<!-- How to measure results -->
<!-- Example: Run evaluate.sh and report val_bpb -->

## Limitation

<!-- Hardware, time, and resource constraints -->
<!-- Example: Single H100, 5 minutes max training time -->
