import csv
import datetime
import re
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple, Union

EntryValue = Union[str, List[str]]


def split_checkbox_values(value: str) -> List[str]:
    return [part.strip() for part in re.split(r"[|;]", value) if part.strip()]


def validate_csv_headers(questions: Sequence[Dict[str, Any]], headers: Sequence[str]) -> Tuple[List[str], List[str]]:
    cleaned_headers = [header.strip() for header in headers]
    expected_titles = [str(question["title"]).strip() for question in questions]
    available = set(cleaned_headers)

    for question, title in zip(questions, expected_titles):
        question["col"] = title if title in available else None

    missing = [title for title in expected_titles if title not in available]
    expected = set(expected_titles)
    extra = [header for header in cleaned_headers if header not in expected]
    return missing, extra


def _validate_value(question: Dict[str, Any], value: str, row_number: int) -> None:
    title = str(question["title"])
    question_type = int(question.get("type", -1))

    if question_type == 9:
        try:
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
                raise ValueError
            datetime.date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"CSV row {row_number}: date for '{title}' must use YYYY-MM-DD.") from exc
    elif question_type == 10:
        try:
            if not re.match(r"^\d{2}:\d{2}$", value):
                raise ValueError
            datetime.time.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"CSV row {row_number}: time for '{title}' must use HH:MM.") from exc
    elif question_type == 5 and not re.match(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$", value):
        raise ValueError(f"CSV row {row_number}: scale value for '{title}' must be numeric.")


def read_response_csv(
    csv_path: Union[str, Path], questions: Sequence[Dict[str, Any]]
) -> Tuple[List[Dict[str, str]], List[str], List[str]]:
    with open(csv_path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        try:
            raw_headers = next(reader)
        except StopIteration as exc:
            raise ValueError("CSV is empty; it must include a header row.") from exc

        headers = [header.strip() for header in raw_headers]
        if len(headers) != len(set(headers)):
            raise ValueError("CSV contains duplicate column headers after trimming whitespace.")
        missing, extra = validate_csv_headers(questions, headers)
        rows: List[Dict[str, str]] = []

        for row_number, values in enumerate(reader, start=2):
            if not any(value.strip() for value in values):
                continue
            if len(values) > len(headers):
                raise ValueError(f"CSV row {row_number} has more values than the header row.")
            row = {
                header: values[index].strip() if index < len(values) else ""
                for index, header in enumerate(headers)
            }
            for question in questions:
                column = question.get("col")
                value = row.get(column, "") if column else ""
                if value:
                    _validate_value(question, value, row_number)
            rows.append(row)

    return rows, missing, extra


def create_template_csv(csv_path: Union[str, Path], questions: Sequence[Dict[str, Any]]) -> str:
    destination = Path(csv_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([str(question["title"]).strip() for question in questions])
        writer.writerow([""] * len(questions))
    return str(destination)


def build_entry_values(questions: Sequence[Dict[str, Any]], row: Dict[str, str]) -> Dict[str, EntryValue]:
    values: Dict[str, EntryValue] = {}
    for question in questions:
        column = question.get("col")
        value = row.get(column, "").strip() if column else ""
        if not value:
            continue

        entry_id = f"entry.{int(question['entry'])}"
        if int(question.get("type", -1)) == 4:
            checkbox_values = split_checkbox_values(value)
            if checkbox_values:
                values[entry_id] = checkbox_values
        else:
            values[entry_id] = value
    return values
