# Forms Poison

Forms Poison is a lightweight, container-friendly Python app that reads a public Google Form, matches CSV rows to the form schema, and submits one response per row through a real Chromium browser.

It is designed for authorized form workflows: you paste a public form URL, match it against a CSV file, and let the app fill the form row by row with real browser automation.

> This project is meant for legitimate testing and internal data-entry workflows. Only use it on forms you are authorized to submit to.

## What it does

- Parses a public Google Form and extracts its question payload
- Maps CSV headers to form fields using normalized names
- Fills the form fields in the browser one row at a time
- Reports success and failure per row in the UI or CLI
- Can run in headless mode for Docker and CI-style environments
- Includes an optional demo-data CSV generator for test runs

## How the app works

1. You paste a public Google Form URL into the app.
2. The app fetches the page HTML and extracts the `FB_PUBLIC_LOAD_DATA_` payload.
3. It detects each question, question type, and entry IDs.
4. You point it at a CSV file containing rows of form responses.
5. It matches CSV columns to form titles, normalizes field names, and prepares a mapping.
6. A Playwright browser opens the form and fills answer fields row by row.
7. The app clicks submit and waits for the confirmation state.
8. It logs each row result, so failed rows are easy to isolate.

## TUI overview

The TUI is intentionally focused and compact:

- Form URL input at the top
- CSV scanning and folder input
- “Fetch & Analyze Form” step
- Question table showing detected fields and mapped CSV columns
- Mode selector for CSV or demo generator
- Start submission button with live status and logs
- Headless-compatible flow for Docker execution

The app name in the interface is branded as “Forms Poison” to make it read like a real tool instead of a raw prototype.

## Project structure

- `app.py` — TUI and CLI entrypoint
- `parser.py` — Google Form HTML extraction and schema parsing
- `submitter.py` — Playwright form submission logic
- `llm.py` — optional demo-data generation for testing only
- `responses/` — CSV input and generated output files
- `models/` — optional GGUF model folder for local demo generation
- `Dockerfile` — Linux container definition
- `docker-entrypoint.sh` — Xvfb headless browser bootstrap
- `docker-compose.yml` — compose-based startup helper

## Setup

### Local Python setup

```bash
cd gform-filler
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### Optional local LLM demo generation

This feature is optional and not required for the main workflow.

```bash
mkdir -p models
# place a local GGUF model in ./models/
# example: ailo-152m-v2-q4_k_m.gguf
```

## Running the app

### TUI mode

```bash
python app.py
```

### Headless CLI mode

```bash
FORM_FILLER_HEADLESS=1 python app.py --no-tui \
  --form-url "https://docs.google.com/forms/..." \
  --csv ./responses/students.csv
```

### Demo generation mode

```bash
python app.py --no-tui --generate-demo --rows 5 \
  --form-url "https://docs.google.com/forms/..."
```

## Docker / WSL usage

This app is built to run inside Docker Desktop with WSL2 enabled.

```bash
# from the project root
$env:PATH += ';' + "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin"
docker build -t gform-filler .

docker run --rm -it \
  -e FORM_FILLER_HEADLESS=1 \
  -v "${PWD}/responses:/app/responses" \
  gform-filler python app.py --no-tui \
  --form-url "https://docs.google.com/forms/d/e/.../viewform" \
  --csv /app/responses/students.csv
```

## Safety and ethics

- Only use on forms you are authorized to submit to.
- Do not fabricate real respondent data.
- The app does not bypass authentication or hidden protections.
- Logs are intentionally limited and do not overexpose sensitive values.
- The built-in demo CSV generation is for testing only.

## Typical workflow

1. Prepare a CSV with one response row per student or record.
2. Put the CSV in `responses/`.
3. Paste the public form URL.
4. Click “Fetch & Analyze Form”.
5. Confirm the detected questions and column mappings.
6. Press “Start Auto-Fill” to submit the mapped rows.
7. Review the log for any row-level failures.

This gives you a clean, repeatable pipeline for form filling without needing a separate Linux host for testing.
