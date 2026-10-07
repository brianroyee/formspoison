import csv
import os
import re
import time
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from playwright.sync_api import sync_playwright


def _normalize_choice_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def _matches_choice_option(target: str, label: str) -> bool:
    target_norm = _normalize_choice_text(target)
    label_norm = _normalize_choice_text(label)
    if not target_norm or not label_norm:
        return False
    if target_norm == label_norm:
        return True
    if target_norm in label_norm:
        return True
    target_tokens = [token for token in target_norm.split() if token]
    if not target_tokens:
        return False
    return all(token in label_norm for token in target_tokens[: min(3, len(target_tokens))])


def _set_form_value(page, selector: str, value: str) -> None:
    locator = page.locator(selector).first
    if locator.count() == 0:
        return
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


def click_choice(page, role: str, text: str) -> None:
    selectors = [
        f'[role="{role}"][aria-label="{text}"]',
        f'[role="{role}"]',
    ]

    for selector in selectors[:1]:
        locator = page.locator(selector)
        if locator.count() > 0:
            matches = locator.all()
            for candidate in matches:
                aria = candidate.get_attribute("aria-label") or ""
                if _matches_choice_option(text, aria):
                    candidate.click()
                    return

    radio_locator = page.locator(f'[role="{role}"]')
    candidates = radio_locator.all()
    for candidate in candidates:
        label = candidate.get_attribute("aria-label") or candidate.text_content() or ""
        if _matches_choice_option(text, label):
            candidate.click()
            return

    raise RuntimeError(f"No matching {role} found for: {text}")


def _safe_row_name(row: Dict[str, str], questions: Iterable[Dict[str, str]]) -> str:
    for question in questions:
        col = question.get("col")
        if not col:
            continue
        value = row.get(col, "")
        if value and str(value).strip():
            return str(value)
    return "row"


def _fill_question(page, question: Dict[str, object], value: str) -> None:
    entry = question.get("entry")
    qtype = int(question.get("type", -1))
    selector = f'input[name="entry.{entry}"]'

    if qtype in (0, 1, 9, 10):
        entry_selector = f'input[name="entry.{entry}"], textarea[name="entry.{entry}"]'
        next_value = value
        if qtype == 9:
            next_value = value[:10] if len(value) >= 10 else value
        elif qtype == 10:
            next_value = value[:5] if len(value) >= 5 else value
        _set_form_value(page, entry_selector, next_value)
    elif qtype in (2, 5):
        click_choice(page, "radio", value)
    elif qtype == 3:
        page.locator('[role="listbox"]').click()
        page.locator('[role="option"]').filter(has_text=re.compile(rf"^\s*{re.escape(value)}\s*$")).first.click()
    elif qtype == 4:
        for token in [part.strip() for part in re.split(r"[;,]", value) if part.strip()]:
            click_choice(page, "checkbox", token)


def _submission_delay(delay: Optional[float]) -> float:
    """Return a non-negative per-submission delay from an argument or environment."""
    raw_delay = str(delay) if delay is not None else os.environ.get("GFORM_SUBMIT_DELAY", "1.5")
    try:
        return max(0.0, float(raw_delay))
    except ValueError:
        raise ValueError("Submission delay must be a non-negative number of seconds.")


def run_submission(
    form_url: str,
    questions: List[Dict[str, object]],
    csv_path: str,
    log_callback: Optional[Callable[[str], None]] = None,
    delay: Optional[float] = None,
) -> Dict[str, int]:
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    with open(csv_path, newline="", encoding="utf-8-sig") as csvfile:
        reader = csv.DictReader(csvfile)
        rows = list(reader)

    matched_questions = [q for q in questions if q.get("col")]
    success = 0
    failed = 0
    submit_delay = _submission_delay(delay)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=os.environ.get("FORM_FILLER_HEADLESS", "0").strip().lower() in {"1", "true", "yes", "on"})
        try:
            for index, row in enumerate(rows, start=1):
                if index > 1 and submit_delay > 0:
                    if log_callback:
                        log_callback(f"Waiting {submit_delay:g}s before next submission…")
                    time.sleep(submit_delay)
                name = _safe_row_name(row, matched_questions)
                if log_callback:
                    log_callback(f"Row {index}: {name}")
                try:
                    page = browser.new_page()
                    page.goto(form_url, wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_timeout(2_000)
                    for question in matched_questions:
                        col = str(question.get("col", "")).strip()
                        if not col:
                            continue
                        value = row.get(col, "")
                        if value is None or str(value).strip() == "":
                            continue
                        _fill_question(page, question, str(value).strip())

                    submit_button = page.locator('[role="button"]').filter(has_text=re.compile(r"^\s*Submit\s*$")).first
                    if submit_button.count() == 0:
                        raise RuntimeError("Submit button not found.")
                    submit_button.click()

                    submission_success = page.locator("text=/Your response has been recorded|Thanks for submitting|Form submitted|Response recorded/i").first
                    try:
                        submission_success.wait_for(state="visible", timeout=20_000)
                    except Exception:
                        original_url = page.url
                        page.wait_for_timeout(2_000)
                        if page.url != original_url and "viewform" not in page.url:
                            pass
                        else:
                            raise
                    success += 1
                    if log_callback:
                        log_callback(f"Success={success} Failed={failed}")
                except Exception as exc:
                    failed += 1
                    if log_callback:
                        log_callback(f"Row {index} failed: {exc.__class__.__name__}: {exc}")
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
        finally:
            browser.close()

    return {"success": success, "failed": failed}
