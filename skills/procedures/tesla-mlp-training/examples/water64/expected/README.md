# expected (placeholders)

This directory will hold the **expected outputs** for the fixture run: the
verdict JSONs the check scripts should produce when run against
`fixtures/`.

Expected content once populated:

- `check_tesla_project.json` — pass verdict for a fixture project skeleton
- `check_iteration.json` — pass verdict with `completed` and `validated`
  reported separately, plus the echoed iteration manifest
- `check_dataset_fingerprint.json` — pass verdict with matching fingerprint
- `summarize_iteration.json` — lcurve/model_devi/label summary

Anything deviating from the expected verdicts is a logic regression in the
chain, not a fixture problem. No real data is committed here.
