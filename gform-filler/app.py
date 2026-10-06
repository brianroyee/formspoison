import argparse
import csv
import os
import re
import sys
from typing import Any, Dict, List, Optional

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Footer, Input, Log, RadioButton, RadioSet, Static

from llm import generate_demo_csv
from parser import fetch_form_html, parse_form_schema
from submitter import run_submission


class GFormFiller(App):
    CSS = """
    Screen {
        layout: vertical;
        padding: 1 2;
        background: #111827;
        color: #e5e7eb;
    }
    #title {
        content-align: center middle;
        color: #f9fafb;
        text-style: bold;
        margin-bottom: 1;
    }
    #subtitle {
        color: #9ca3af;
        content-align: center middle;
        margin-bottom: 1;
    }
    #question_table {
        height: 12;
        min-height: 8;
        margin-top: 1;
    }
    #log_panel {
        height: 8;
        min-height: 5;
        background: #0f172a;
        color: #dbeafe;
    }
    #llm_controls {
        height: auto;
        margin-top: 1;
    }
    Horizontal {
        layout: horizontal;
        width: 100%;
    }
    Input {
        width: 1fr;
        background: #1f2937;
        color: #f9fafb;
    }
    Button {
        margin: 0 0 0 1;
        background: #2563eb;
        color: white;
    }
    Button.-primary {
        background: #2563eb;
    }
    Button.-success {
        background: #16a34a;
    }
    #start_submit {
        width: 100%;
        margin-top: 1;
    }
    """

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self.form_url = "https://docs.google.com/forms/d/e/1FAIpQLScF_r0L_eCY-6LHj-1UBHTbKpU4PROhQV13NcoOOprn0UAvXw/viewform"
        self.questions: List[Dict[str, Any]] = []
        self.csv_path = "./responses/students.csv"
        self.current_csv_rows: List[Dict[str, str]] = []
        self.current_status = "Ready"

    def compose(self) -> ComposeResult:
        yield Static("Forms Poison", id="title")
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
        yield RadioSet(
            RadioButton("Load from CSV", value=True, id="mode_csv"),
            RadioButton("Generate with LLM", id="mode_llm"),
            id="mode_selector",
        )
        with Vertical(id="llm_controls"):
            yield Input(value="5", id="llm_rows")
            yield Button("Generate", id="generate_rows")
        self._llm_controls_visible(False)
        yield Button("2. Start Auto-Fill", id="start_submit", variant="success", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        self.log_event("App started. Paste a public Google Form URL to begin.")
        self._update_status("Paste a Google Form URL to begin")
        self.call_after_refresh(lambda: self.query_one("#form_url", Input).focus())

    def _llm_controls_visible(self, visible: bool) -> None:
        controls = self.query_one("#llm_controls", Vertical)
        controls.display = visible

    def _update_status(self, text: str) -> None:
        self.current_status = text
        status = self.query_one("#status", Static)
        status.update(text)

    def log_event(self, message: str) -> None:
        log = self.query_one("#log_panel", Log)
        log.write(message)

    @on(Button.Pressed, "#scan_folder")
    def handle_scan_folder(self) -> None:
        folder = self.query_one("#folder_path", Input).value.strip() or "./responses"
        self._scan_folder(folder)

    @work(thread=True)
    def _scan_folder(self, folder: str) -> None:
        try:
            matches = []
            if os.path.isdir(folder):
                matches = sorted(os.path.join(folder, name) for name in os.listdir(folder) if name.lower().endswith(".csv"))
            if not matches:
                self.call_from_thread(self._update_status, "No CSV files found.")
                self.call_from_thread(self.log_event, "No CSV files found in folder.")
                return
            csv_path = matches[0]
            self.call_from_thread(self._map_csv_to_questions, csv_path)
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
            rows = list(reader)
            headers = reader.fieldnames or []

        self.current_csv_rows = rows
        matched = 0
        for question in self.questions:
            question["col"] = ""
            title = str(question["title"])
            title_norm = self._normalize_header(title)
            match = None
            for header in headers:
                if self._normalize_header(header) == title_norm:
                    match = header
                    break
            if match is None:
                for header in headers:
                    norm = self._normalize_header(header)
                    if (title_norm in norm) or (norm in title_norm):
                        match = header
                        break
            if match:
                question["col"] = match
                matched += 1

        self._update_status(f"Matched {matched}/{len(self.questions)} questions to columns")
        self.log_event(f"Matched {matched}/{len(self.questions)} questions to columns")

        start_button = self.query_one("#start_submit", Button)
        start_button.disabled = matched < 1

        table = self.query_one("#question_table", DataTable)
        table.clear(columns=False)
        table.columns.clear()
        table.add_columns("Question", "Entry ID", "Type", "CSV Column")
        for question in self.questions:
            table.add_row(question["title"], str(question["entry"]), question["type_name"], question["col"])

    def _normalize_header(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value).lower())

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
            html = fetch_form_html(form_url)
            questions = parse_form_schema(html)
            self.call_from_thread(self._render_questions, questions)
        except Exception as exc:  # pragma: no cover
            self.call_from_thread(self.log_event, f"Fetch failed: {exc}")
            self.call_from_thread(self._update_status, "Fetch failed.")

    def _render_questions(self, questions: List[Dict[str, Any]]) -> None:
        self.questions = questions
        table = self.query_one("#question_table", DataTable)
        table.clear(columns=False)
        table.columns.clear()
        table.add_columns("Question", "Entry ID", "Type", "CSV Column")
        for question in questions:
            table.add_row(question["title"], str(question["entry"]), question["type_name"], question["col"])
        self._update_status(f"{len(questions)} questions detected")
        self.log_event(f"{len(questions)} questions detected")

        if not self.current_csv_rows and not os.path.exists(self.csv_path):
            self.log_event("No CSV found. Generating demo rows for the detected form.")
            self._generate_rows_task(5)

    @on(RadioSet.Changed, "#mode_selector")
    def handle_mode_change(self, event: RadioSet.Changed) -> None:
        mode = event.pressed.id if event.pressed else "mode_csv"
        self._llm_controls_visible(mode == "mode_llm")

    @on(Button.Pressed, "#generate_rows")
    def handle_generate_rows(self) -> None:
        if not self.questions:
            self.log_event("No form schema available for synthetic row generation.")
            return
        rows_value = self.query_one("#llm_rows", Input).value.strip() or "5"
        try:
            rows = max(1, int(rows_value))
        except ValueError:
            self.log_event("LLM row count must be an integer.")
            return
        self._generate_rows_task(rows)

    @work(thread=True)
    def _generate_rows_task(self, row_count: int) -> None:
        try:
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
        self._start_submit_task(self.form_url, self.csv_path)

    @work(thread=True)
    def _start_submit_task(self, form_url: str, csv_path: str) -> None:
        try:
            result = run_submission(form_url, self.questions, csv_path, log_callback=lambda message: self.call_from_thread(self.log_event, message))
            self.call_from_thread(self._update_status, f"Success={result['success']} Failed={result['failed']}")
            self.call_from_thread(self.log_event, f"Success={result['success']} Failed={result['failed']}")
        except Exception as exc:  # pragma: no cover
            self.call_from_thread(self.log_event, f"Submit run failed: {exc}")
            self.call_from_thread(self._update_status, "Submission failed.")


def _cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Forms Poison")
    parser.add_argument("--form-url", default=os.environ.get("FORM_URL"), help="Public Google Form URL")
    parser.add_argument("--csv", default=os.environ.get("FORM_CSV", "./responses/students.csv"), help="CSV containing response rows")
    parser.add_argument("--rows", type=int, default=int(os.environ.get("FORM_ROWS", "5")), help="Number of demo rows to generate")
    parser.add_argument("--generate-demo", action="store_true", help="Generate demo CSV rows instead of using a supplied CSV")
    parser.add_argument("--no-tui", action="store_true", help="Run headless CLI mode instead of opening the Textual UI")
    return parser.parse_args()


def run_cli(args: argparse.Namespace) -> None:
    if not args.form_url:
        raise SystemExit("A form URL is required in CLI mode. Use --form-url or set FORM_URL.")

    print("Fetching form...")
    html = fetch_form_html(args.form_url)
    questions = parse_form_schema(html)
    print(f"{len(questions)} questions detected")

    csv_path = args.csv
    if args.generate_demo:
        csv_path = "./responses/_generated.csv"
        print(f"Generating demo CSV: {csv_path}")
        csv_path = generate_demo_csv(questions, args.rows, csv_path)
        print(f"Demo CSV generated at {csv_path}")

    if not os.path.exists(csv_path):
        raise SystemExit(f"CSV not found: {csv_path}")

    print(f"Submitting from {csv_path}")
    result = run_submission(args.form_url, questions, csv_path, log_callback=print)
    print(f"Success={result['success']} Failed={result['failed']}")


if __name__ == "__main__":
    args = _cli_args()
    if args.no_tui:
        run_cli(args)
    else:
        GFormFiller().run()
