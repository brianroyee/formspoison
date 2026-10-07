import csv
from pathlib import Path

import pytest

from csv_data import build_entry_values, create_template_csv, read_response_csv, split_checkbox_values


def test_template_uses_question_titles_and_one_blank_row(tmp_path: Path):
    questions = [{"title": "Nombre", "entry": 12}, {"title": "Ciudad de México", "entry": 13}]
    destination = create_template_csv(tmp_path / "nested" / "responses.csv", questions)

    with open(destination, newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert Path(destination).is_absolute()
    assert rows == [["Nombre", "Ciudad de México"], ["", ""]]


def test_csv_accepts_bom_accented_text_and_skips_blank_rows(tmp_path: Path):
    csv_path = tmp_path / "responses.csv"
    csv_path.write_text("\ufeffNombre,Estado\nJosé,México\n,\n", encoding="utf-8")
    questions = [{"title": "Nombre", "entry": 1, "type": 0}, {"title": "Estado", "entry": 2, "type": 0}]

    rows, missing, extra = read_response_csv(csv_path, questions)

    assert rows == [{"Nombre": "José", "Estado": "México"}]
    assert missing == []
    assert extra == []


def test_checkbox_values_split_on_pipe_and_semicolon():
    assert split_checkbox_values("One | Two; Three") == ["One", "Two", "Three"]
    questions = [{"title": "Topics", "entry": 456, "type": 4, "col": "Topics"}]
    assert build_entry_values(questions, {"Topics": "One | Two; Three"}) == {
        "entry.456": ["One", "Two", "Three"]
    }


def test_empty_answers_are_omitted_from_entry_values():
    questions = [{"title": "Name", "entry": 7, "type": 0, "col": "Name"}]
    assert build_entry_values(questions, {"Name": "  "}) == {}


def test_date_time_and_scale_formats_are_validated(tmp_path: Path):
    csv_path = tmp_path / "typed.csv"
    questions = [
        {"title": "Date", "entry": 1, "type": 9},
        {"title": "Time", "entry": 2, "type": 10},
        {"title": "Score", "entry": 3, "type": 5},
    ]
    csv_path.write_text("Date,Time,Score\n2026-10-07,09:30,4.5\n", encoding="utf-8")

    rows, missing, _ = read_response_csv(csv_path, questions)

    assert len(rows) == 1
    assert missing == []

    csv_path.write_text("Date,Time,Score\n07-10-2026,9:30,four\n", encoding="utf-8")
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        read_response_csv(csv_path, questions)
