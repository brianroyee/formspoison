import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from playwright.sync_api import sync_playwright

TYPE_NAMES = {
    0: "short text",
    1: "paragraph",
    2: "multiple choice",
    3: "dropdown",
    4: "checkboxes",
    5: "linear scale",
    9: "date",
    10: "time",
}


def _normalize_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"[^a-z0-9]", "", text.lower())


def fetch_form_html(form_url: str) -> str:
    """Open the target form in a browser and return the page HTML."""
    headless = os.environ.get("FORM_FILLER_HEADLESS", "0").strip().lower() in {"1", "true", "yes", "on"}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless, slow_mo=80 if not headless else None)
        page = browser.new_page()
        try:
            page.goto(form_url, wait_until="networkidle", timeout=60_000)
            return page.content()
        finally:
            browser.close()


def _extract_public_data(html: str) -> List[Any]:
    marker = "FB_PUBLIC_LOAD_DATA_"
    idx = html.find(marker)
    if idx == -1:
        raise ValueError("Google Forms payload marker not found in page source.")

    tail = html[idx + len(marker):]
    start = tail.find("[")
    if start == -1:
        raise ValueError("Google Forms payload array start not found.")

    decoder = json.JSONDecoder()
    parsed, _ = decoder.raw_decode(tail[start:])
    return parsed


def parse_form_schema(form_html: str) -> List[Dict[str, Any]]:
    """Parse the Google Forms payload and return the normalized question schema."""
    payload = _extract_public_data(form_html)
    if not isinstance(payload, list) or len(payload) < 2:
        raise ValueError("Unexpected form payload structure.")

    form_data = payload[1]
    if not isinstance(form_data, list) or len(form_data) < 2:
        raise ValueError("Missing form payload data structure.")

    items = form_data[1]
    if not isinstance(items, list):
        raise ValueError("Question items are missing.")

    questions: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, list) or len(item) < 5:
            continue

        title = item[1] if isinstance(item[1], str) else None
        if not title or not title.strip():
            continue

        type_code = item[3]
        if not isinstance(type_code, int):
            continue

        required = bool(item[2]) if len(item) > 2 else False
        entry_id = None
        options: List[str] = []

        payload_slot = item[4] if len(item) > 4 else None
        if isinstance(payload_slot, list) and payload_slot:
            first = payload_slot[0]
            if isinstance(first, list):
                if first:
                    entry_id = first[0]
                if len(first) > 1 and isinstance(first[1], list):
                    for opt in first[1]:
                        if isinstance(opt, list) and opt:
                            options.append(str(opt[0]))
                        elif isinstance(opt, str):
                            options.append(opt)

        # Support the legacy payload shape described in the original brief.
        if entry_id is None and isinstance(type_code, list) and type_code and isinstance(type_code[0], list):
            legacy = type_code[0]
            entry_id = legacy[0] if legacy else None
            if len(legacy) > 1 and isinstance(legacy[1], list):
                for opt in legacy[1]:
                    if isinstance(opt, list) and opt:
                        options.append(str(opt[0]))
                    elif isinstance(opt, str):
                        options.append(opt)
            type_code = item[4]

        if isinstance(type_code, list) and type_code and isinstance(type_code[0], list):
            type_code = item[3]

        if entry_id is None:
            continue

        question = {
            "title": title,
            "entry": int(entry_id),
            "type": int(type_code),
            "type_name": TYPE_NAMES.get(int(type_code), f"type_{type_code}"),
            "col": "",
            "required": required,
            "options": options,
        }
        questions.append(question)

    return questions


def find_question_by_entry(questions: List[Dict[str, Any]], entry_id: int) -> Optional[Dict[str, Any]]:
    for question in questions:
        if int(question.get("entry", -1)) == int(entry_id):
            return question
    return None
