from csv_data import validate_csv_headers

def test_headers_match_exactly_after_trimming_whitespace():
    questions = [{"title": "E-MAIL ID"}, {"title": "Your Home State:"}]
    missing, extra = validate_csv_headers(questions, [" E-MAIL ID ", "Your Home State:"])

    assert missing == []
    assert extra == []
    assert [question["col"] for question in questions] == ["E-MAIL ID", "Your Home State:"]


def test_header_matching_is_case_and_punctuation_sensitive():
    questions = [{"title": "E-MAIL ID"}, {"title": "Your Home State:"}]
    missing, extra = validate_csv_headers(questions, ["Email ID", "Your Home State"])

    assert missing == ["E-MAIL ID", "Your Home State:"]
    assert extra == ["Email ID", "Your Home State"]
    assert [question["col"] for question in questions] == [None, None]


def test_reports_missing_and_extra_columns_independently():
    questions = [{"title": "Name"}, {"title": "Email"}]
    missing, extra = validate_csv_headers(questions, ["Name", "Notes"])

    assert missing == ["Email"]
    assert extra == ["Notes"]
    assert questions[0]["col"] == "Name"
    assert questions[1]["col"] is None
