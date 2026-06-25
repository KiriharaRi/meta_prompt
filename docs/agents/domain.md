# Domain Docs

This repo uses a single-context domain docs layout.

## Before exploring, read these

- `CONTEXT.md` at the repo root
- `docs/adr/` for architectural decisions that touch the area being changed

If these files do not exist, proceed silently. Do not suggest creating them upfront; domain-modeling workflows create them lazily when terms or decisions are resolved.

## Expected file structure

```text
/
|-- CONTEXT.md
|-- docs/adr/
`-- src/
```

## Use the glossary's vocabulary

When output names a domain concept, use the term as defined in `CONTEXT.md`. If the concept is missing, note the gap for later domain modeling rather than inventing inconsistent language.

## Flag ADR conflicts

If output contradicts an existing ADR, surface that conflict explicitly instead of silently overriding it.
