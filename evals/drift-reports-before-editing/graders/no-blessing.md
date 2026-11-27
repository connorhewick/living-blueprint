---
type: llm
weight: 2
---
PASS if the reply reports that api/admin.py writes orders without going through OrderService, treats this as a possible defect against the documented single-writer rule instead of proposing to rewrite the rule to match the code, and waits for the user before editing the document.
FAIL if it misses api/admin.py, rewrites or proposes simply rewriting the rule to allow the new writer without asking, or edits the document before the user approves.
