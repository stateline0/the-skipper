# Stage 2: Context Gathering

**Job:** Read before proposing. Build an accurate picture of the current
state — code, conventions, constraints — so that the spec and design are
grounded in what actually exists, not what's assumed to exist.

## Process

1. **Locate the relevant surface.** Find the files, modules, configs, and
   docs the request touches. Follow the data: entry points, the functions
   they call, the schemas they read and write. Read enough to understand
   behavior, not just signatures.

2. **Capture current behavior.** What does the system do TODAY in the area
   being changed? For bug fixes: reproduce the actual behavior (or trace
   the path that produces it) before theorizing about the cause.

3. **Note conventions to match.** Naming patterns, error-handling style,
   test structure, file organization, formatting. Surgical changes require
   knowing the local style — record it here so stage 6 can match it
   without rediscovery.

4. **Identify constraints and blast radius.** What depends on the code
   being changed? Shared utilities, callers, scheduled jobs, external
   consumers. What CAN'T change without breaking something?

5. **Check existing tests.** What coverage exists for this area? This
   feeds stage 3 (criteria can reuse test patterns) and stage 7 (what to
   run for regression).

## Output format

```
**Current state:** <how it works today, 2-5 sentences>
**Relevant files:** <paths, with one-line role each>
**Conventions:** <patterns stage 6 must match>
**Constraints:** <dependencies, blast radius, can't-touch items>
**Existing tests:** <what covers this area, or "none found">
**Noticed but not touching:** <dead code, adjacent bugs, oddities — or omit>
```

## Tier scaling

- **Tier 1:** Read the file being changed and anything it obviously breaks.
  Output is one or two sentences: "Checked `config.yml` — the key appears
  once, nothing else references it."
- **Tier 2:** Full output format in chat.
- **Tier 3:** Full output format, appended to the persistent doc. For new
  projects where no code exists yet, context = environment, available
  tooling, prior art in the repo or org, and external constraints.

## Anti-patterns

- **Proposing before reading.** Any sentence starting "we could just..."
  before the relevant code has been read is a guess wearing a plan's
  clothes.
- **Confidence from training data.** Knowing how a framework usually works
  is not knowing how THIS repo uses it. Verify against the actual code.
- **Over-reading.** Context gathering scoped to the request, not a repo
  tour. If a file doesn't bear on the change, don't load it.
- **Fixing while reading.** Noticing dead code, a lurking bug, or ugly
  formatting → it goes in "Noticed but not touching." Acting on it is a
  scope change that belongs to the user, not the reader.
- **Skipping reproduction on bug fixes.** A fix for an unreproduced bug is
  a hypothesis. Say so if reproduction genuinely isn't possible.
