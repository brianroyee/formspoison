from pathlib import Path

from parser import parse_form_schema


def test_sample_form_extracts_expected_questions_types_and_entries():
    fixture = Path(__file__).parent / "fixtures" / "sample_form.html"
    questions = parse_form_schema(fixture.read_text(encoding="utf-8"))

    assert len(questions) == 13
    assert [(question["type"], question["entry"]) for question in questions] == [
        (0, 1001), (0, 1002), (0, 1003), (0, 1004), (0, 1005), (0, 1006),
        (2, 1007), (2, 1008), (4, 1009), (0, 1010), (0, 1011), (0, 1012), (0, 1013),
    ]
    assert questions[0]["title"] == "Name"
    assert questions[8]["type_name"] == "checkboxes"
