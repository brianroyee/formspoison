import csv
import math
import os
import random
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

from playwright.sync_api import sync_playwright

from csv_data import EntryValue, build_entry_values, split_checkbox_values


def _normalize_choice_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def _matches_choice_option(target: str, label: str) -> bool:
    target_norm = _normalize_choice_text(target)
    label_norm = _normalize_choice_text(label)
    if not target_norm or not label_norm:
        return False
    if target_norm == label_norm or target_norm in label_norm:
        return True
    target_tokens = target_norm.split()
    return bool(target_tokens) and all(token in label_norm for token in target_tokens[: min(3, len(target_tokens))])


def _set_form_value(page: Any, selector: str, value: str) -> None:
    locator = page.locator(selector).first
    if locator.count() == 0:
        raise RuntimeError("Answer field was not found.")
    locator.evaluate(
        """
        (element, nextValue) => {
            const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
            if (descriptor && descriptor.set) {
                descriptor.set.call(element, nextValue);
            } else {
                element.value = nextValue;
            }
            element.setAttribute('value', nextValue);
            ['input', 'change', 'blur'].forEach((eventName) => {
                element.dispatchEvent(new Event(eventName, { bubbles: true }));
            });
        }
        """,
        value,
    )


def _click_choice(page: Any, role: str, value: str) -> None:
    for candidate in page.locator(f'[role="{role}"]').all():
        label = candidate.get_attribute("aria-label") or candidate.text_content() or ""
        if _matches_choice_option(value, label):
            candidate.click()
            return
    raise RuntimeError(f"No matching {role} option was found.")


def _fill_question(page: Any, question: Dict[str, Any], value: EntryValue) -> None:
    entry = int(question["entry"])
    question_type = int(question.get("type", -1))
    if question_type in (0, 1, 9, 10):
        _set_form_value(page, f'input[name="entry.{entry}"], textarea[name="entry.{entry}"]', str(value))
    elif question_type in (2, 5):
        _click_choice(page, "radio", str(value))
    elif question_type == 3:
        page.locator('[role="listbox"]').click()
        option = page.locator('[role="option"]').filter(
            has_text=re.compile(rf"^\s*{re.escape(str(value))}\s*$")
        ).first
        if option.count() == 0:
            raise RuntimeError("No matching dropdown option was found.")
        option.click()
    elif question_type == 4:
        checkbox_values = value if isinstance(value, list) else split_checkbox_values(str(value))
        for checkbox_value in checkbox_values:
            _click_choice(page, "checkbox", checkbox_value)


def _submit_form_row(page: Any, form_url: str, questions: Sequence[Dict[str, Any]], row: Dict[str, str]) -> int:
    page.goto(form_url, wait_until="domcontentloaded", timeout=60_000)
    entry_values = build_entry_values(questions, row)
    for question in questions:
        entry_key = f"entry.{int(question['entry'])}"
        value = entry_values.get(entry_key)
        if value is not None:
            _fill_question(page, question, value)

    submit_button = page.locator('[role="button"]').filter(
        has_text=re.compile(r"^\s*Submit\s*$")
    ).first
    if submit_button.count() == 0:
        raise RuntimeError("Submit button was not found.")

    with page.expect_response(
        lambda response: response.request.method == "POST" and "formResponse" in response.url,
        timeout=60_000,
    ) as response_info:
        submit_button.click()
    return int(response_info.value.status)


def _submission_delay(delay: float) -> float:
    try:
        parsed_delay = float(delay)
    except (TypeError, ValueError) as exc:
        raise ValueError("Submission delay must be a number of at least 1.0 seconds.") from exc
    if not math.isfinite(parsed_delay) or parsed_delay < 1.0:
        raise ValueError("Submission delay must be at least 1.0 seconds.")
    return parsed_delay


def _write_submission_log(row_number: int, status: str) -> None:
    timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    with open("submission_log.txt", "a", encoding="utf-8") as handle:
        handle.write(f"{timestamp} row={row_number} status={status}\n")


def run_submission(
    form_url: str,
    questions: Sequence[Dict[str, Any]],
    rows: Sequence[Dict[str, str]],
    delay: float = 1.5,
    cancel_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    submit_delay = _submission_delay(delay)
    total = len(rows)
    success = 0
    failed = 0
    completed = 0
    failures: List[Dict[str, Any]] = []
    cancellation = cancel_event or threading.Event()
    stopped = False

    if total == 0:
        return {"total": 0, "completed": 0, "success": 0, "failed": 0, "failures": [], "stopped": False}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=os.environ.get("FORM_FILLER_HEADLESS", "0").strip().lower() in {"1", "true", "yes", "on"}
        )
        page = browser.new_page()
        try:
            for row_number, row in enumerate(rows, start=1):
                if cancellation.is_set():
                    stopped = True
                    break

                try:
                    http_status = _submit_form_row(page, form_url, questions, row)
                    if http_status in (200, 302):
                        success += 1
                        row_status = f"success http={http_status}"
                        ui_status = "success"
                    else:
                        failed += 1
                        message = f"Unexpected HTTP status {http_status}"
                        failures.append({"row": row_number, "message": message})
                        row_status = f"failed http={http_status}"
                        ui_status = "failed"
                except Exception as exc:
                    failed += 1
                    message = f"Submission error ({type(exc).__name__})"
                    failures.append({"row": row_number, "message": message})
                    row_status = f"failed error={type(exc).__name__}"
                    ui_status = "failed"

                completed += 1
                _write_submission_log(row_number, row_status)
                if progress_callback:
                    progress_callback({
                        "row": row_number,
                        "total": total,
                        "completed": completed,
                        "success": success,
                        "failed": failed,
                        "status": ui_status,
                    })

                if cancellation.is_set():
                    stopped = completed < total
                    break
                if row_number < total:
                    time.sleep(submit_delay + random.uniform(0.0, 0.3))
        finally:
            page.close()
            browser.close()

    return {
        "total": total,
        "completed": completed,
        "success": success,
        "failed": failed,
        "failures": failures,
        "stopped": stopped,
    }
