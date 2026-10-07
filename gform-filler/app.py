import argparse
import csv
import os
import re
from typing import Any, Dict, List, Sequence

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, DataTable, Footer, Input, Log, RadioButton, RadioSet, Static

try:
    from llm import LLAMA_AVAILABLE, generate_demo_csv

    LLM_MODE_AVAILABLE = LLAMA_AVAILABLE
except ImportError:  # Keep the CSV workflow usable if the optional module cannot load.
    generate_demo_csv = None
    LLM_MODE_AVAILABLE = False

from parser import fetch_form_html, parse_form_schema
from submitter import run_submission


def normalize_header(value: str) -> str:
    """Normalize form titles and CSV headers for deterministic matching."""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def map_question_columns(questions: Sequence[Dict[str, Any]], headers: Sequence[str]) -> int:
    """Set each question's matching CSV column, or ``None`` when there is none."""
    matched = 0
    for question in questions:
        question["col"] = None
        title_norm = normalize_header(str(question["title"]))
        match = next((header for header in headers if normalize_header(header) == title_norm), None)
        if match is None:
            match = next(
                (
                    header
                    for header in headers
                    if (header_norm := normalize_header(header)) and (title_norm in header_norm or header_norm in title_norm)
                ),
                None,
            )
        if match is not None:
            question["col"] = match
            matched += 1
    return matched


class GFormFiller(App):
    CSS = """
    Screen { layout: vertical; padding: 1 2; background: #111827; color: #e5e7eb; }
    #title { content-align: center middle; color: #f9fafb; text-style: bold; margin-bottom: 1; }
    #subtitle { color: #9ca3af; content-align: center middle; margin-bottom: 1; }
    #question_table { height: 12; min-height: 8; margin-top: 1; }
    #log_panel { height: 8; min-height: 5; background: #0f172a; color: #dbeafe; }
    #llm_controls, #demo_confirmation { height: auto; margin-top: 1; }
    Horizontal { layout: horizontal; width: 100%; }
    Input { width: 1fr; background: #1f2937; color: #f9fafb; }
    Button { margin: 0 0 0 1; background: #2563eb; color: white; }
    Button.-primary { background: #2563eb; }
    Button.-success { background: #16a34a; }
    #start_submit { width: 100%; margin-top: 1; }
    """

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, allow_demo_submit: bool = False) -> None:
        super().__init__()
        self.allow_demo_submit = allow_demo_submit
        self.form_url = "https://docs.google.com/forms/d/e/1FAIpQLScF_r0L_eCY-6LHj-1UBHTbKpU4PROhQV13NcoOOprn0UAvXw/viewform"
        self.questions: List[Dict[str, Any]] = []
        self.csv_path = "./responses/students.csv"
        self.current_csv_rows: List[Dict[str, str]] = []
        self.current_status = "Ready"
        self.matched_question_count = 0
        self.llm_mode_active = False

    def compose(self) -> ComposeResult:
        yield Static("gform-filler", id="title")
        yield Static("Google Form response orchestrator for bulk data entry", id="subtitle")
        yield Input(placeholder="Paste Google Form URL here…", value=self.form_url, id="form_url")
        with Horizontal():
            yield Input(value="./responses", id="folder_path")
            yield Button("Scan Folder", id="scan_folder")
        yield Button("1. Fetch & Analyze Form", id="fetch_form", variant="primary")
        table = DataTable(id="question_table")
        table.add_columns("Question", "Entry ID", "Type", "CSV Column")
        yield table
        yield Static("Ready", id="status")
        yield Log(id="log_panel")
        with RadioSet(id="mode_selector"):
            yield RadioButton("Load from CSV", value=True, id="mode_csv")
            if LLM_MODE_AVAILABLE:
                yield RadioButton("Generate with LLM", id="mode_llm")
        with Vertical(id="llm_controls"):
            yield Input(value="5", id="llm_rows")
            yield Button("Generate", id="generate_rows")
        yield Checkbox(
            "I confirm this data is for offline testing only and I will not submit it to a live form",
            id="demo_submit_confirmation",
        )
        yield Button("2. Start Auto-Fill", id="start_submit", variant="success", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        self._llm_controls_visible(False)
        self._demo_confirmation_visible(False)
        self.log_event("App started. Paste a public Google Form URL to begin.")
        if not LLM_MODE_AVAILABLE:
            self.log_event("LLM mode unavailable (llama-cpp-python not installed).")
        self._update_status("Paste a Google Form URL to begin")
        self.call_after_refresh(lambda: self.query_one("#form_url", Input).focus())

    def _llm_controls_visible(self, visible: bool) -> None:
        self.query_one("#llm_controls", Vertical).display = visible

    def _demo_confirmation_visible(self, visible: bool) -> None:
        self.query_one("#demo_submit_confirmation", Checkbox).display = visible

    def _is_demo_data(self) -> bool:
        return self.llm_mode_active or self.csv_path.endswith("_generated.csv")

    def _demo_submission_confirmed(self) -> bool:
        return self.allow_demo_submit or self.query_one("#demo_submit_confirmation", Checkbox).value

    def _refresh_submit_button(self) -> None:
        requires_confirmation = self._is_demo_data()
        self._demo_confirmation_visible(requires_confirmation and not self.allow_demo_submit)
        enabled = self.matched_question_count > 0 and (not requires_confirmation or self._demo_submission_confirmed())
        self.query_one("#start_submit", Button).disabled = not enabled

    def _update_status(self, text: str) -> None:
        self.current_status = text
        self.query_one("#status", Static).update(text)

    def log_event(self, message: str) -> None:
        self.query_one("#log_panel", Log).write(message)

    @on(Button.Pressed, "#scan_folder")
    def handle_scan_folder(self) -> None:
        folder = self.query_one("#folder_path", Input).value.strip() or "./responses"
        self._scan_folder(folder)

    @work(thread=True)
    def _scan_folder(self, folder: str) -> None:
        try:
            matches = sorted(os.path.join(folder, name) for name in os.listdir(folder) if name.lower().endswith(".csv")) if os.path.isdir(folder) else []
            if not matches:
                self.call_from_thread(self._update_status, "No CSV files found.")
                self.call_from_thread(self.log_event, "No CSV files found in folder.")
                return
            self.call_from_thread(self._map_csv_to_questions, matches[0])
        except Exception as exc:  # pragma: no cover
            self.call_from_thread(self.log_event, f"Scan failed: {exc}")
            self.call_from_thread(self._update_status, "CSV scan failed.")

    def _map_csv_to_questions(self, csv_path: str) -> None:
        self.csv_path = csv_path
        if not self.questions:
            self._update_status("Analyze a form before scanning CSV.")
            return
        with open(csv_path, newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            self.current_csv_rows = list(reader)
            headers = reader.fieldnames or []
        self.matched_question_count = map_question_columns(self.questions, headers)
        self._update_status(f"Matched {self.matched_question_count}/{len(self.questions)} questions to columns")
        self.log_event(f"Matched {self.matched_question_count}/{len(self.questions)} questions to columns")
        self._render_question_table()
        self._refresh_submit_button()

    def _render_question_table(self) -> None:
        table = self.query_one("#question_table", DataTable)
        table.clear(columns=False)
        table.columns.clear()
        table.add_columns("Question", "Entry ID", "Type", "CSV Column")
        for question in self.questions:
            table.add_row(question["title"], str(question["entry"]), question["type_name"], question.get("col") or "")

    @on(Button.Pressed, "#fetch_form")
    def handle_fetch_form(self) -> None:
        form_url = self.query_one("#form_url", Input).value.strip()
        if not form_url:
            self._update_status("Paste a Google Form URL first.")
            return
        self.form_url = form_url
        self._fetch_and_analyze(form_url)

    @work(thread=True)
    def _fetch_and_analyze(self, form_url: str) -> None:
        try:
            self.call_from_thread(self._render_questions, parse_form_schema(fetch_form_html(form_url)))
        except Exception as exc:  # pragma: no cover
            self.call_from_thread(self.log_event, f"Fetch failed: {exc}")
            self.call_from_thread(self._update_status, "Fetch failed.")

    def _render_questions(self, questions: List[Dict[str, Any]]) -> None:
        self.questions = questions
        self.matched_question_count = 0
        self._render_question_table()
        self._refresh_submit_button()
        self._update_status(f"{len(questions)} questions detected")
        self.log_event(f"{len(questions)} questions detected")

    @on(RadioSet.Changed, "#mode_selector")
    def handle_mode_change(self, event: RadioSet.Changed) -> None:
        self.llm_mode_active = bool(event.pressed and event.pressed.id == "mode_llm")
        self._llm_controls_visible(self.llm_mode_active)
        self._refresh_submit_button()

    @on(Checkbox.Changed, "#demo_submit_confirmation")
    def handle_demo_confirmation(self, event: Checkbox.Changed) -> None:
        self._refresh_submit_button()

    @on(Button.Pressed, "#generate_rows")
    def handle_generate_rows(self) -> None:
        if not self.questions:
            self.log_event("No form schema available for synthetic row generation.")
            return
        try:
            rows = max(1, int(self.query_one("#llm_rows", Input).value.strip() or "5"))
        except ValueError:
            self.log_event("LLM row count must be an integer.")
            return
        self._generate_rows_task(rows)

    @work(thread=True)
    def _generate_rows_task(self, row_count: int) -> None:
        try:
            if generate_demo_csv is None:
                raise RuntimeError("llama-cpp-python is not installed. Install it with: pip install llama-cpp-python>=0.3")
            output_path = generate_demo_csv(self.questions, row_count, "./responses/_generated.csv")
            self.call_from_thread(self.log_event, f"Demo CSV generated at {output_path} (demo/test data only)")
            self.call_from_thread(self._update_status, f"Generated {row_count} demo rows")
            self.call_from_thread(self._map_csv_to_questions, output_path)
        except Exception as exc:  # pragma: no cover
            self.call_from_thread(self.log_event, f"Generator failed: {exc}")
            self.call_from_thread(self._update_status, "Demo generation failed.")

    @on(Button.Pressed, "#start_submit")
    def handle_start_submit(self) -> None:
        if not self.questions:
            self._update_status("No form has been parsed yet.")
            return
        if not self.csv_path or not os.path.exists(self.csv_path):
            self._update_status("A CSV must be loaded before starting auto-fill.")
            return
        if self._is_demo_data() and not self._demo_submission_confirmed():
            self._update_status("Confirm offline test use before submitting demo data.")
            return
        self._start_submit_task(self.form_url, self.csv_path)

    @work(thread=True)
    def _start_submit_task(self, form_url: str, csv_path: str) -> None:
        try:
            if csv_path.endswith("_generated.csv"):
                self.call_from_thread(self.log_event, "⚠ Submitting demo-generated data. Ensure this is a test form.")
            result = run_submission(form_url, self.questions, csv_path, log_callback=lambda message: self.call_from_thread(self.log_event, message))
            self.call_from_thread(self._update_status, f"Success={result['success']} Failed={result['failed']}")
            self.call_from_thread(self.log_event, f"Success={result['success']} Failed={result['failed']}")
        except Exception as exc:  # pragma: no cover
            self.call_from_thread(self.log_event, f"Submit run failed: {exc}")
            self.call_from_thread(self._update_status, "Submission failed.")


def _cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="gform-filler")
    parser.add_argument("--form-url", default=os.environ.get("FORM_URL"), help="Public Google Form URL")
    parser.add_argument("--csv", default=os.environ.get("FORM_CSV", "./responses/students.csv"), help="CSV containing response rows")
    parser.add_argument("--generate-demo", type=int, metavar="N", help="Generate N demo CSV rows via the local LLM")
    parser.add_argument("--rows", type=int, metavar="N", help="Alias for --generate-demo")
    parser.add_argument("--allow-demo-submit", action="store_true", help="Bypass demo-data confirmation (dangerous; test forms only)")
    parser.add_argument("--delay", type=float, default=None, metavar="SECONDS", help="Seconds to wait between submissions (default: 1.5)")
    parser.add_argument("--no-tui", action="store_true", help="Run without the Textual interface (plain stdout)")
    return parser.parse_args()


def run_cli(args: argparse.Namespace) -> None:
    if not args.form_url:
        raise SystemExit("A form URL is required in CLI mode. Use --form-url or set FORM_URL.")
    demo_rows = args.generate_demo if args.generate_demo is not None else args.rows
    if demo_rows is not None and demo_rows < 1:
        raise SystemExit("--generate-demo/--rows must be at least 1.")
    print("Fetching form...")
    questions = parse_form_schema(fetch_form_html(args.form_url))
    print(f"{len(questions)} questions detected")
    csv_path = args.csv
    if demo_rows is not None:
        if not LLM_MODE_AVAILABLE or generate_demo_csv is None:
            raise RuntimeError("llama-cpp-python is not installed. Install it with: pip install llama-cpp-python>=0.3")
        csv_path = "./responses/_generated.csv"
        print(f"Generating demo CSV: {csv_path}")
        csv_path = generate_demo_csv(questions, demo_rows, csv_path)
        print(f"Demo CSV generated at {csv_path}")
    if not os.path.exists(csv_path):
        raise SystemExit(f"CSV not found: {csv_path}")
    if csv_path.endswith("_generated.csv") and not args.allow_demo_submit:
        raise SystemExit("Refusing to submit demo-generated data. Use --allow-demo-submit only for a test form.")
    if csv_path.endswith("_generated.csv"):
        print("⚠ Submitting demo-generated data. Ensure this is a test form.")
    print(f"Submitting from {csv_path}")
    result = run_submission(args.form_url, questions, csv_path, log_callback=print, delay=args.delay)
    print(f"Success={result['success']} Failed={result['failed']}")


if __name__ == "__main__":
    args = _cli_args()
    if args.no_tui:
        run_cli(args)
    else:
        GFormFiller(allow_demo_submit=args.allow_demo_submit).run()
