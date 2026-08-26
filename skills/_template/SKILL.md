---
name: palimind-skill-template
description: >
  Template for creating new developer skills in /skills. Use when adding a
  SKILL.md that teaches AI coding agents how to work on part of Palimind.
---

# <Skill Name>

> Copy this folder to `skills/<new-skill-name>/SKILL.md` and fill it in.
> Delete this template file from your new skill.

---
name: palimind-<name>
description: >
  One paragraph: what this skill covers and WHEN a coding agent must load it.
  State the trigger conditions explicitly (files, tasks, keywords).
---

# Title

## When this skill MUST be used
- Bullet list of concrete file paths / task types

## Context
2-4 sentences max — what area of the codebase this governs.

## Conventions & rules
- Imperative, checkable rules ("Always X", "Never Y")

## Commands
```
exact commands to build/test/lint this area
```

## Gotchas
- Non-obvious things that break easily or have bitten us before
