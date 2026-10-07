# gform-filler

`gform-filler` is a terminal tool that reads a public Google Form, maps CSV rows to its fields, and submits one response per row through Chromium and Playwright. Use it only for forms you are authorized to submit.

The tool is intentionally named plainly: gform-filler.

## What it does

- Parses a public Google Form and extracts question titles, types, and entry IDs.
- Maps CSV headers to question titles using punctuation-insensitive matching.
- Offers a Textual TUI and a plain CLI mode.
- Uses a real Playwright browser for submissions, with configurable pacing.
- Optionally generates demo data through a local GGUF model.

## Local setup

```bash
# System dependencies (Linux)
sudo apt-get update
sudo apt-get install -y python3-venv xvfb

# Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Playwright browser + system libraries
playwright install chromium
playwright install-deps chromium   # required on Linux VMs / CI

# Optional: enable the local LLM demo-data generator
# pip install llama-cpp-python>=0.3
# mkdir -p models
# Place a quantized GGUF (e.g. AILO-152M-v2 q4_k_m) in ./models/
```

On Windows, use WSL2 and run these inside the WSL shell. Do not mix PowerShell and bash in the same block.

## Running

Start the TUI:

```bash
python app.py
```

Run without the TUI:

```bash
FORM_FILLER_HEADLESS=1 python app.py --no-tui \
  --form-url "https://docs.google.com/forms/..." \
  --csv ./responses/students.csv
```

The local LLM mode is optional. When `llama-cpp-python` is not installed, CSV filling still works and the TUI hides the LLM option.

## CLI reference

| Flag | Description |
| --- | --- |
| `--no-tui` | Run without the Textual interface (plain stdout). |
| `--form-url URL` | Provide the form URL at launch (skips the input step). |
| `--csv PATH` | Provide the responses CSV path. |
| `--generate-demo N` | Generate N demo rows via the local LLM instead of reading a CSV. |
| `--rows N` | Alias for `--generate-demo N`. |
| `--allow-demo-submit` | Bypass the demo-data confirmation guard (dangerous; test forms only). |
| `--delay SECONDS` | Wait this many seconds between submissions (default: 1.5; also configurable with `GFORM_SUBMIT_DELAY`). |

If Google starts throttling, increase `--delay`.

## Docker

The image installs `xvfb` and runs `playwright install-deps chromium`, so headless browser mode works in the container.

### PowerShell (Windows host)

```powershell
docker build -t gform-filler .
docker run --rm -it `
  -v ${PWD}/responses:/app/responses `
  -v ${PWD}/models:/app/models `
  -e FORM_FILLER_HEADLESS=1 `
  gform-filler
```

### bash (Linux/macOS host)

```bash
docker build -t gform-filler .
docker run --rm -it \
  -v "$PWD/responses:/app/responses" \
  -v "$PWD/models:/app/models" \
  -e FORM_FILLER_HEADLESS=1 \
  gform-filler
```

The `./models` mount is only needed for LLM mode. If you don't use it, omit that volume.

## Safety and ethics

- Only use on forms you are authorized to submit to.
- Do not fabricate real respondent data.
- The app does not bypass authentication or hidden protections.
- Logs are intentionally limited and do not expose response values.
- Generated demo data is for offline and dry-run testing only. Do not submit LLM-generated rows to a live form.

For generated data, the TUI keeps **Start Auto-Fill** disabled until the offline-test confirmation is checked. CLI submissions of `_generated.csv` require `--allow-demo-submit`.

## Tests

Install development requirements and run:

```bash
pip install -r requirements-dev.txt
pytest
```

Run tests with pytest.
