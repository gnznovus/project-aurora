# Token-Efficient Workflow Rules

This file defines default collaboration rules to minimize token usage while keeping engineering quality high.

## Core Principles

1. Work in small scoped batches.
2. Read only the code needed for the current task.
3. Prefer targeted tests over full-suite runs during iteration.
4. Ship checkpoint commits early when risk or token budget is tight.
5. Avoid broad refactors unless explicitly approved.

## Default Operating Rules

1. Search first with `rg`, then open only matching files/line ranges.
2. Never open very large files end-to-end unless required.
3. For large files, patch isolated functions by line range.
4. Keep each turn to up to 3 concrete changes.
5. Use short progress updates and concise final summaries.
6. Reuse existing helpers/modules before adding new abstractions.
7. Run only affected tests first, then wider tests when stable.
8. Commit checkpoint after each stable milestone.

## Large File Rule (`> 600` lines)

1. Build a function map via symbol/search.
2. Touch only local sections for the active task.
3. If repeated edits are needed, split file into modules first.
4. Keep behavior unchanged during structural split (no mixed refactor+feature).

## Recommended Commit Strategy

1. `checkpoint: docs + stable runtime fixes`
2. `checkpoint: scoped feature slice`
3. `checkpoint: tests + docs`

## Reuse Across Projects

Copy this file into any project and adapt:

- commands/scripts location
- preferred test command
- large-file threshold
- commit naming convention
