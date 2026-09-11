# Ticket classifier prompt changelog

## V1

- Added basic role-based instructions, task definition, categories, output
  format, and constraints.
- Establishes a clear baseline with minimal prompt complexity.

## V2

- Added realistic few-shot customer/classification examples.
- Intended to improve consistency by demonstrating category boundaries.
- Trade-off: uses more input tokens and examples may introduce bias toward
  the demonstrated wording.

## V3

- Added explicit XML-style sections for role, task, categories, input, and
  output format.
- Intended to improve instruction separation and make the prompt easier for
  later application integration.
- Trade-off: adds formatting overhead and does not guarantee better accuracy.

These versions are alternatives for later evaluation; this changelog does not
claim that one version is superior.
