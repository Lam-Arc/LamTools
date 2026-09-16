# LamTools Core Skills

Put shared skills here only when they are useful across multiple LamTools members.

Core skills must not contain Writer- or Artist-specific persona, routing, or product behavior.

## Built-in office skills

LamTools bundles ten task-focused office skills under `office-*`. Their frontmatter
descriptions define automatic matching and `/office-*` composer commands; each skill
checks the host's real capabilities before claiming that an Office artifact was created.

Shared design, tooling, source, and acceptance-test guidance lives in `references/` and
is not exposed as an additional skill.

The deterministic renderer follows the standard Skill layout at `office-renderer/`:
instructions in `SKILL.md`, UI metadata in `agents/openai.yaml`, and its executable plus
Python package in `scripts/`. It is explicit-only supporting infrastructure rather than
an automatic content-authoring route. Core provides the thin `office validate` /
`office render` CLI adapter and loads the Skill-owned runtime lazily.
