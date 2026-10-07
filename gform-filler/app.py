import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Sequence
from urllib.parse import urlsplit

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Footer, Input, ProgressBar, Static

from csv_data import create_template_csv, read_response_csv
from parser import fetch_form_html, parse_form_schema
from submitter import run_submission


def is_valid_form_url(value: str) -> bool:
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/")
    if host == "forms.gle":
        return bool(path.strip("/"))
    return host == "docs.google.com" and bool(re.match(r"^/forms/d/e/[^/]+/viewform$", path))


class GFormFiller(App):
    CSS = """
    Screen { layout: vertical; padding: 1 2; }
    #banner { content-align: center middle; text-style: bold; height: 3; }
    #subtitle { content-align: center middle; color: $text-muted; height: 2; }
    .stage { height: 1fr; }
    .stage-title { text-style: bold; margin-bottom: 1; }
    .field-label { margin-top: 1; }
    .message { height: auto; min-height: 1; margin-top: 1; }
    .actions { height: 3; margin-top: 1; }
    .actions Button { margin-right: 1; }
    Input { width: 1fr; }
    #question_table { height: 1fr; min-height: 8; margin-top: 1; }
    #progress_bar { margin: 1 0; }
    #failure_summary { height: 1fr; overflow-y: auto; }
    """

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self.form_url = ""
        self.questions: List[Dict[str, Any]] = []
        self.csv_path = ""
        self.csv_rows: List[Dict[str, str]] = []
        self.missing_headers: List[str] = []
        self.cancel_event = threading.Event()
        self.last_result: Dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        yield Static("gform-filler", id="banner")
        yield Static("Authorized Google Forms response entry", id="subtitle")

        with Vertical(id="step_form", classes="stage"):
            yield Static("1 / Form URL", classes="stage-title")
            yield Static("Google Form URL", classes="field-label")
            yield Input(placeholder="https://docs.google.com/forms/d/e/.../viewform", id="form_url")
            yield Static("", id="form_error", classes="message")
            with Horizontal(classes="actions"):
                yield Button("Next", id="form_next", variant="primary")

        with Vertical(id="step_questions", classes="stage"):
            yield Static("2 / Scan questions", classes="stage-title")
            yield Static("Fetching the form...", id="fetch_status", classes="message")
            yield DataTable(id="question_table")
            yield Static("", id="question_error", classes="message")
            with Horizontal(classes="actions"):
                yield Button("Back", id="questions_back")
                yield Button("Next", id="questions_next", variant="primary", disabled=True)

        with Vertical(id="step_csv", classes="stage"):
            yield Static("3 / CSV file", classes="stage-title")
            yield Static("CSV file path", classes="field-label")
            yield Input(value="responses.csv", id="csv_path")
            yield Static("", id="csv_message", classes="message")
            with Horizontal(classes="actions"):
                yield Button("Back", id="csv_back")
                yield Button("Load CSV", id="csv_load", variant="primary")
                yield Button("Proceed with missing columns", id="confirm_missing", variant="warning")
                yield Button("Exit", id="template_exit")

        with Vertical(id="step_confirm", classes="stage"):
            yield Static("4 / Confirm and configure", classes="stage-title")
            yield Static("", id="submission_summary", classes="message")
            yield Static("Delay between submissions (seconds, minimum 1.0)", classes="field-label")
            yield Input(value="1.5", id="delay_input", type="number")
            yield Static("", id="estimate", classes="message")
            yield Static("", id="delay_error", classes="message")
            with Horizontal(classes="actions"):
                yield Button("Back", id="confirm_back")
                yield Button("Start", id="submission_start", variant="success")

        with Vertical(id="step_progress", classes="stage"):
            yield Static("5 / Submission progress", classes="stage-title")
            yield ProgressBar(total=1, id="progress_bar", show_eta=False)
            yield Static("Success: 0  Failed: 0", id="live_counts", classes="message")
            yield Static("Preparing...", id="current_row", classes="message")
            with Horizontal(classes="actions"):
                yield Button("Stop", id="submission_stop", variant="error")

        with Vertical(id="step_result", classes="stage"):
            yield Static("Submission summary", classes="stage-title")
            yield Static("", id="result_counts", classes="message")
            yield Static("", id="failure_summary")
            with Horizontal(classes="actions"):
                yield Button("Run again", id="run_again", variant="primary")
                yield Button("Exit", id="result_exit")

        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#confirm_missing", Button).display = False
        self.query_one("#template_exit", Button).display = False
        self.query_one("#step_questions", Vertical).display = False
        self.query_one("#step_csv", Vertical).display = False
        self.query_one("#step_confirm", Vertical).display = False
        self.query_one("#step_progress", Vertical).display = False
        self.query_one("#step_result", Vertical).display = False
        self._show_stage("step_form")
        self.call_after_refresh(lambda: self.query_one("#form_url", Input).focus())

    def _show_stage(self, stage_id: str) -> None:
        for candidate in ("step_form", "step_questions", "step_csv", "step_confirm", "step_progress", "step_result"):
            self.query_one(f"#{candidate}", Vertical).display = candidate == stage_id

    def _show_error(self, target: str, message: str) -> None:
        self.query_one(f"#{target}", Static).update(message)

    @on(Input.Submitted, "#form_url")
    def form_url_submitted(self) -> None:
        self.advance_from_form()

    @on(Button.Pressed, "#form_next")
    def form_next_pressed(self) -> None:
        self.advance_from_form()

    def advance_from_form(self) -> None:
        form_url = self.query_one("#form_url", Input).value.strip()
        if not form_url:
            self._show_error("form_error", "Enter a Google Form URL.")
            return
        if not is_valid_form_url(form_url):
            self._show_error("form_error", "Use a forms.gle link or a docs.google.com/forms/d/e/.../viewform URL.")
            return

        self.form_url = form_url
        self.questions = []
        self.query_one("#form_error", Static).update("")
        table = self.query_one("#question_table", DataTable)
        table.clear(columns=True)
        self.query_one("#questions_next", Button).disabled = True
        self.query_one("#question_error", Static).update("")
        self.query_one("#fetch_status", Static).update("Fetching the form...")
        self._show_stage("step_questions")
        self._fetch_questions(form_url)

    @work(thread=True, exclusive=True)
    def _fetch_questions(self, form_url: str) -> None:
        try:
            questions = parse_form_schema(fetch_form_html(form_url))
            if not questions:
                raise ValueError("No questions were found. The form may be private, require sign-in, or use an unsupported layout.")
            self.call_from_thread(self._questions_loaded, questions)
        except Exception as exc:
            self.call_from_thread(self._fetch_failed, str(exc))

    def _questions_loaded(self, questions: List[Dict[str, Any]]) -> None:
        self.questions = questions
        table = self.query_one("#question_table", DataTable)
        table.add_columns("#", "Question", "Entry ID", "Type", "Required")
        for number, question in enumerate(questions, start=1):
            table.add_row(
                str(number),
                str(question["title"]),
                f"entry.{question['entry']}",
                str(question["type_name"]),
                "yes" if question.get("required") else "",
            )
        self.query_one("#fetch_status", Static).update(f"Found {len(questions)} questions.")
        self.query_one("#questions_next", Button).disabled = False

    def _fetch_failed(self, message: str) -> None:
        self._show_error("question_error", f"Could not scan this form: {message}")
        self.query_one("#fetch_status", Static).update("Scan failed. Go back and check the URL or form access.")
        self.query_one("#questions_next", Button).disabled = True

    @on(Button.Pressed, "#questions_back")
    def back_to_form(self) -> None:
        self._show_stage("step_form")
        self.query_one("#form_url", Input).focus()

    @on(Button.Pressed, "#questions_next")
    def advance_to_csv(self) -> None:
        self._show_stage("step_csv")
        self.query_one("#csv_path", Input).focus()

    @on(Input.Submitted, "#csv_path")
    def csv_path_submitted(self) -> None:
        self.load_csv()

    @on(Button.Pressed, "#csv_load")
    def csv_load_pressed(self) -> None:
        self.load_csv()

    def load_csv(self) -> None:
        requested_path = self.query_one("#csv_path", Input).value.strip() or "responses.csv"
        path = Path(requested_path).expanduser()
        if not path.exists():
            try:
                self.csv_path = create_template_csv(path, self.questions)
            except Exception as exc:
                self._show_error("csv_message", f"Could not create the template: {exc}")
                return
            self.query_one("#csv_path", Input).display = False
            self.query_one("#csv_load", Button).display = False
            self.query_one("#csv_back", Button).display = False
            self.query_one("#template_exit", Button).display = True
            self.query_one("#confirm_missing", Button).display = False
            self._show_error("csv_message", f"Template created: {self.csv_path}\nFill this in, then restart the app.")
            return

        try:
            rows, missing, extra = read_response_csv(path, self.questions)
        except Exception as exc:
            self._show_error("csv_message", f"Could not load CSV: {exc}")
            return
        if not rows:
            self._show_error("csv_message", "The CSV has no non-blank response rows.")
            return

        self.csv_path = str(path.resolve())
        self.csv_rows = rows
        self.missing_headers = missing
        if missing:
            message = "Missing form question columns:\n" + "\n".join(f"- {title}" for title in missing)
            message += "\nContinue with those answers left blank?"
            if extra:
                message += "\nExtra columns will be ignored: " + ", ".join(extra)
            self._show_error("csv_message", message)
            self.query_one("#confirm_missing", Button).display = True
            self.query_one("#csv_load", Button).display = False
            return

        self._prepare_confirmation(extra)

    @on(Button.Pressed, "#confirm_missing")
    def accept_missing_headers(self) -> None:
        self._prepare_confirmation([])

    def _prepare_confirmation(self, extra: Sequence[str]) -> None:
        self.query_one("#confirm_missing", Button).display = False
        self.query_one("#csv_load", Button).display = True
        summary = (
            f"Form URL: {self.form_url}\n"
            f"Rows: {len(self.csv_rows)}\n"
            f"CSV path: {self.csv_path}"
        )
        if extra:
            summary += "\nExtra columns ignored: " + ", ".join(extra)
        self.query_one("#submission_summary", Static).update(summary)
        self._update_estimate()
        self._show_stage("step_confirm")

    @on(Input.Changed, "#delay_input")
    def update_estimate(self) -> None:
        self._update_estimate()

    def _update_estimate(self) -> None:
        try:
            delay = float(self.query_one("#delay_input", Input).value)
        except ValueError:
            self.query_one("#estimate", Static).update("Estimated total time (delay only): unavailable")
            return
        seconds = max(0, len(self.csv_rows) - 1) * delay
        self.query_one("#estimate", Static).update(f"Estimated total time (delay only): {seconds:.1f} seconds")

    @on(Button.Pressed, "#confirm_back")
    def back_to_csv(self) -> None:
        self._show_stage("step_csv")

    @on(Button.Pressed, "#submission_start")
    def start_submission(self) -> None:
        try:
            delay = float(self.query_one("#delay_input", Input).value)
        except ValueError:
            self._show_error("delay_error", "Enter a delay of at least 1.0 seconds.")
            return
        if delay < 1.0:
            self._show_error("delay_error", "Delay must be at least 1.0 seconds.")
            return

        self.cancel_event = threading.Event()
        progress = self.query_one("#progress_bar", ProgressBar)
        progress.update(total=len(self.csv_rows), progress=0)
        self.query_one("#live_counts", Static).update("Success: 0  Failed: 0")
        self.query_one("#current_row", Static).update("Starting...")
        self.query_one("#submission_stop", Button).disabled = False
        self.query_one("#submission_start", Button).disabled = True
        self._show_stage("step_progress")
        self._submit_rows(self.form_url, self.questions, self.csv_rows, delay, self.cancel_event)

    @work(thread=True, exclusive=True)
    def _submit_rows(
        self,
        form_url: str,
        questions: List[Dict[str, Any]],
        rows: List[Dict[str, str]],
        delay: float,
        cancel_event: threading.Event,
    ) -> None:
        try:
            result = run_submission(
                form_url,
                questions,
                rows,
                delay=delay,
                cancel_event=cancel_event,
                progress_callback=lambda update: self.call_from_thread(self._submission_progress, update),
            )
            self.call_from_thread(self._submission_finished, result)
        except Exception as exc:
            self.call_from_thread(self._submission_crashed, str(exc))

    def _submission_progress(self, update: Dict[str, Any]) -> None:
        self.query_one("#progress_bar", ProgressBar).update(
            total=update["total"], progress=update["completed"]
        )
        self.query_one("#live_counts", Static).update(
            f"Success: {update['success']}  Failed: {update['failed']}"
        )
        self.query_one("#current_row", Static).update(
            f"Row {update['row']} of {update['total']}: {update['status']}"
        )

    def _submission_finished(self, result: Dict[str, Any]) -> None:
        self.last_result = result
        self._render_result(result)

    def _submission_crashed(self, message: str) -> None:
        self.last_result = {"success": 0, "failed": 0, "completed": 0, "failures": []}
        self.last_result["failures"] = [{"row": 0, "message": f"Submission stopped: {message}"}]
        self._render_result(self.last_result)

    def _render_result(self, result: Dict[str, Any]) -> None:
        failures = result.get("failures", [])[:5]
        failure_text = "\n".join(
            f"Row {failure['row']}: {failure['message']}" for failure in failures
        ) or "No failures."
        self.query_one("#result_counts", Static).update(
            f"Total submitted: {result.get('completed', 0)}  "
            f"Success: {result.get('success', 0)}  Failed: {result.get('failed', 0)}"
            + ("  (stopped)" if result.get("stopped") else "")
        )
        self.query_one("#failure_summary", Static).update(
            "First failure messages:\n" + failure_text
        )
        self.query_one("#submission_start", Button).disabled = False
        self._show_stage("step_result")

    @on(Button.Pressed, "#submission_stop")
    def stop_submission(self) -> None:
        self.cancel_event.set()
        self.query_one("#current_row", Static).update("Stopping after the current row...")
        self.query_one("#submission_stop", Button).disabled = True

    @on(Button.Pressed, "#run_again")
    def run_again(self) -> None:
        self.form_url = ""
        self.questions = []
        self.csv_path = ""
        self.csv_rows = []
        self.missing_headers = []
        self.query_one("#form_url", Input).value = ""
        self.query_one("#csv_path", Input).value = "responses.csv"
        self.query_one("#csv_path", Input).display = True
        self.query_one("#csv_load", Button).display = True
        self.query_one("#csv_back", Button).display = True
        self.query_one("#template_exit", Button).display = False
        self.query_one("#confirm_missing", Button).display = False
        self.query_one("#question_table", DataTable).clear(columns=True)
        self.query_one("#questions_next", Button).disabled = True
        self._show_stage("step_form")
        self.query_one("#form_url", Input).focus()

    @on(Button.Pressed, "#template_exit")
    @on(Button.Pressed, "#result_exit")
    def exit_app(self) -> None:
        self.exit()


def main() -> None:
    GFormFiller().run()


if __name__ == "__main__":
    main()
