# Token-Efficient Workflow Rules

Defines how to minimize token usage while maintaining engineering quality.

---

## Core Principles

1. Work in small, scoped batches.
2. Read only the code required for the current task.
3. Prefer targeted validation over full-suite runs during iteration.
4. Commit early when risk or token usage increases.
5. Avoid broad refactors unless explicitly requested.

---

## Default Operating Rules

1. Search first (`rg` or equivalent), then open only matching files or line ranges.
2. Do NOT open large files (>600 LOC) end-to-end unless absolutely required.
3. Once a section is identified, operate only on that section.
4. Do NOT re-read the same large file multiple times in a single task.
5. Limit each iteration to a small number of concrete changes (≤3 logical changes).
6. Use concise progress updates and summaries.
7. Reuse existing modules before introducing new abstractions.
8. Validate only affected areas first, expand scope only when stable.
9. Commit after each stable, verified step.

---

## Large File Handling (`> 600` LOC)

1. Build a structure map using search/symbol tools.
2. Identify exact regions before making changes.
3. Modify only targeted sections; avoid full-file rewrites.
4. If multiple regions must be edited repeatedly, apply slicing (see slicing rules).
5. Do not mix structural changes with feature changes.

---

## Read Strategy

* Prefer:

  * symbol lookup
  * search hits
  * partial file reads

* Avoid:

  * full file scans
  * repeated reads of the same content
  * loading unrelated files

---

## Change Strategy

* Make minimal, localized edits.
* Avoid cascading changes across multiple files unless necessary.
* Do not introduce new patterns unless required by the task.
* Preserve existing structure and naming unless explicitly improving it.

---

## Commit Strategy

Use small, descriptive checkpoint commits:

* `checkpoint: stable fix`
* `checkpoint: scoped change`
* `checkpoint: tests + validation`

---

## Failure Handling

If token usage becomes high or scope expands:

1. Stop adding new changes.
2. Commit current stable state.
3. Continue in a new iteration with reduced scope.

---

## Reuse Across Projects

This file is portable. Adapt only:

* command/tooling specifics
* test commands
* file size thresholds
* commit conventions
