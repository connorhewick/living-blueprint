# Writing rules

For an engineer who has never seen the code and will believe what the page says.

## Shape

- **Diagram first.** A section opens with a diagram or table, then a caption whose first sentence
  states the takeaway.
- **Describe, don't judge.** Opinions go only in an Assessment section, written only when asked.
- **State the commit once.** The page header shows it.
- **Measure.** Counts come from commands you ran. Never estimate. Save the command in `checks`.
- **Name the enforcer** for every rule. "review only" is itself a finding.
- **Docs are claims.** Read the README, decision records and contributor and agent guides first,
  check them against the code, and record where they disagree. Confirm **both** sides: quote what
  the doc really says.

## Where claims go wrong

Each of these produced a wrong statement in a real review.

- **Absolute words.** Before "only", "never", "every", "none" or "the one", search for a
  counterexample. If you cannot rule one out, say "none found by <method>".
- **Imports are not boundaries.** Inside one module or package, import lines show external
  libraries and little else. Measure references to names, including methods added to a type by
  another folder (extensions, mixins, monkeypatches, globals). A layer that imports nothing can
  still depend on a neighbour.
- **Verify the enforcer, not its name.** Read the test or rule. Say what it actually checks,
  including what it excludes.
- **Reachability.** Code that exists may not ship. Check build flags, feature flags, routes and
  callers before saying a user can do something, or that nothing does.
- **Beyond the repository.** The platform may do things no code shows: backups, retries, TLS,
  autoscaling. Do not claim it does not happen because the code is silent.
- **Call order.** Draw the order the code runs, including what is built eagerly or deferred.
- **Evidence level.** Mark each behaviour claim `run`, `read` or `search`. Never `run` unless you
  ran it.
- **Who owns a step.** A box names the function or component that really does the work.

## An architecture doc's sections

Leave out a section that does not apply, and say so in Provenance.

1. **Overview**: deployable units and layers (folder, responsibility, its one rule, enforcer);
   arrows in allowed directions only; measured wrong-way references and whether boundaries are
   enforced; data model with the path from schema to storage to replication, entities,
   cardinality, delete behaviour, ids and opaque fields; who writes what, flagging state with one
   writer or none.
2. **User stories** (3 to 6): the matrix, then one swimlane each, with side effects beside their
   cause and a list of gaps.
3. **Load-bearing components** (usually 2 to 4), chosen by evidence: fan-in, sole writer, churn,
   blast radius. For each: position with counts, parts grouped by role, contract, the failure that
   would hurt most traced end to end, related types kept apart and why, and a Rule, Why, Held by
   table.
4. **External platforms**: topology, a round trip out and in, start-up order, user-visible state,
   failure and conflict, guard rails including manual steps.
5. **Patterns**: per layer, with real code and its enforcer; size by layer; translation to the
   reader's stack.
6. **Provenance**: what was measured and how, and what could not be confirmed.

## Privacy

No secrets, credentials, personal data or production data in a doc, a check command or its
recorded output. When quoting config, remove the value.
