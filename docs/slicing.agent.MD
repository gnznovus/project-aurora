# Large File Slicing Guide

Use this guide before modifying large files (e.g., `main.py`).

## Goal

Improve structure and maintainability by moving domain-based route logic into dedicated modules.

---

## Core Principle

Slice by **domain (feature)**, not by file size or individual endpoints.

Each domain groups related routes under a shared purpose or path prefix.
Each domain MUST map to exactly one route file.

---

## Guardrails

1. Move one domain at a time.
2. Do not change behavior during slicing (no mixed refactor + feature).
3. Keep endpoint paths and response shapes unchanged.
4. Keep route layer thin; move business logic to `services/` when applicable.
5. Place shared helpers in `utils/`.

---

## File Structure Rules

* Route handlers → `routes/<domain>.py`
* Business logic → `services/<domain>_service.py`
* Shared helpers → `utils/`

### Constraints

* MUST use existing directories (`routes/`, `services/`, `utils/`) if they already exist.
* MUST NOT create equivalent files in root when a matching directory exists.
* MUST NOT split a single domain across multiple route files.
* MUST NOT create one file per endpoint.

### Root Directory Rules

Only allowed files in root:

* `main.py`
* `config.py`
* `db.py` (optional)

All other files MUST be placed in the appropriate subdirectory.

---

## When to Slice

Apply slicing when one or more of the following conditions are met:

* File size exceeds ~500 LOC
* Multiple domains (features) exist in the same file
* Navigation becomes difficult (cannot locate logic quickly)
* Repeated patterns or logic duplication appear
* Changes require scanning large portions of the file

Do NOT slice when:

* The file contains a single, clear domain
* The file is small and easy to understand
* Slicing would create unnecessary fragmentation

Prefer slicing by domain boundaries over file size alone.

---

## Slicing Process

1. Identify a domain (by route prefix or feature group).
2. Extract:

   * route handlers → `routes/<domain>.py`
   * move non-HTTP logic → `services/` (if present)
3. Replace original code with router import and registration.
4. Verify imports and dependencies.
5. Validate application startup and affected routes.
6. If structure or placement is unclear, stop and do not create new patterns.

---

## Per-Slice Checklist

* Handlers moved to correct domain file
* Router registered in `main.py`
* No behavior changes introduced
* Imports resolved correctly
* Application runs without errors

---

## Rollback Plan

If a slice fails:

1. Revert only the current slice.
2. Keep previous successful slices.
3. Resume from last stable state.

---

## Done Definition

* `main.py` contains only:

  * app initialization
  * middleware
  * router registration

* All routes are organized by domain in `routes/`

* Business logic is separated when appropriate

* No misplaced files outside defined structure
