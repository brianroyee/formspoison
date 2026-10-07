# Technical Design

## Overview

`gform-filler` is a local Textual TUI for reading a public Google Form schema, validating a CSV, and submitting responses sequentially through Chromium with Playwright. The app has one user-facing entrypoint and performs network and browser work in Textual workers.

## Modules

| Module | Responsibility |
| --- | --- |
| `app.py` | TUI stages, URL validation, worker orchestration, progress, and cancellation |
| `parser.py` | Public form fetch and `FB_PUBLIC_LOAD_DATA_` schema parsing |
| `csv_data.py` | Exact header mapping, CSV validation, template creation, and entry-value construction |
| `submitter.py` | Sequential browser submission, HTTP-status results, pacing, and privacy-safe logging |

## Workflow

1. Validate the supplied link against supported Google Forms URL patterns.
2. Fetch and parse the form in a background worker, then show the question table.
3. Load the requested CSV, or create a header-plus-blank-row template and exit.
4. Confirm row count, path, missing columns if any, and a delay of at least 1.0 second.
5. Reuse one Chromium browser and one page for sequential row submissions. Report each row's result and allow cancellation between rows.

## CSV Contract

CSV files are decoded as UTF-8 with optional BOM. Headers are matched exactly after trimming surrounding whitespace. Extra columns are ignored; missing form columns are presented for confirmation. Empty cells are omitted from a submission and entirely blank rows are skipped. Checkbox values are split on vertical bar or semicolon. Date, time, and scale values are checked against their expected formats before submission.

## Submission and Logging

Each response is submitted through the form's normal browser interface. The captured form-response HTTP status is successful only when it is 200 or 302. The delay is at least 1.0 second, with a small random addition between rows. Outcomes are appended to `submission_log.txt` with timestamp, row number, and status; response values are never included.

The app supports public forms only and does not bypass authentication or spam filters. Use is limited to forms owned by the user or forms they are authorized to submit to.
