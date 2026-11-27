---
type: llm
weight: 2
focus: trace
---
PASS if the assistant read the shop code and then asked the user design questions that refer to what it found (such as OrderService, the orders table or the published messages) before producing any design, and did not write application code.
FAIL if it asked nothing, asked only generic questions with no reference to this code, invented answers to open decisions and carried on, or wrote or proposed to apply application code.
