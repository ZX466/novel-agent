---
name: strategic-compact
description: Context management discipline for long sessions. Keep 20% headroom, preserve intent when compacting.
metadata:
  origin: ECC
---

# Strategic Compaction

Goal: prevent context exhaustion on large tasks.

## Rules

- Reserve the last 20% of the context window on large refactors / multi-file features.
- Low-sensitivity tasks (single edits, docs, simple fixes) may use the window more fully.
- Before compacting, summarize: current goal, decisions made, open questions, next steps.
- Prefer targeted reads over broad scans to avoid filling context.

## When to Compress

- Before starting a new large file after memory-heavy review work.
- After completing a phase, note the checkpoint and plan before continuing.

## Keep

- Task framing, activation conditions, workflow steps, critical examples.
- Drop: repetitive prose, unrelated variants, entire directories when 1-2 files suffice.