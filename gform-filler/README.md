# gform-filler

`gform-filler` is a terminal user interface for entering one response per CSV row into a public Google Form using Playwright. Use it only with forms you own or are authorized to submit to.

## Installation

From the `gform-filler` directory:

```bash
pip install -e .
playwright install chromium
```

To install the test dependency as well:

```bash
pip install -e ".[dev]"
```

## Launch

Run the app from a source checkout:

```bash
python app.py
```

After editable installation, launch it with:

```bash
gform-filler
```

Both commands open the TUI directly. There is no submission command-line mode.

## User Flow

1. Enter the Google Form URL. Accepted links are `forms.gle/...` and `docs.google.com/forms/d/e/.../viewform`.
2. The app loads and parses the public form in a worker, then displays each question, entry ID, type, and required status. Forms that require sign-in or cannot be parsed show an in-app error.
3. Enter a CSV path. The default is `responses.csv`. If the file does not exist, the app creates it with the question titles as headers and one blank row, shows its absolute path, and exits so it can be filled before restarting.
4. For an existing CSV, the app checks the question-title headers and response rows, then shows the form, row count, CSV path, delay, and estimated pacing time. Missing question columns are listed and require confirmation before continuing.
5. Start submission to see row progress and success/failure counts. Stop halts after the current row. On completion, the app displays totals and up to five row-specific failure messages. Choose Run again to start with another form.

## CSV Format

- Save the file as UTF-8; UTF-8 with a byte-order mark is also accepted.
- The first row must contain question titles. Headers are compared case-sensitively and punctuation-sensitively after trimming leading and trailing whitespace.
- Extra columns are ignored. Missing form-question columns require confirmation and are left unanswered.
- Blank cells are not submitted, and entirely blank rows are skipped.
- For checkbox questions, separate selections in a cell with `|` or `;`.
- Date answers must use `YYYY-MM-DD`; time answers must use `HH:MM`; scale answers must be numeric strings.

## Form Access and Responsible Use

Only public forms that can be opened without signing in are supported. The app does not bypass authentication, solve challenges, or bypass spam filters. It is intended for forms you own or are authorized to submit to. A delay of at least 1.0 second is required between responses; the default is 1.5 seconds with a small additional randomized wait.

Submission outcomes are appended to `submission_log.txt` in the working directory with a timestamp, row number, and status. Submitted values are not written to the log.

## Tests

Run the offline test suite with:

```bash
pytest -q
```
