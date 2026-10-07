from app import map_question_columns, normalize_header


def test_email_header_variants_normalize_and_match_question():
    assert {normalize_header(value) for value in ["E-MAIL ID", "Email ID", "e-mail id", "emailid"]} == {"emailid"}
    for header in ["E-MAIL ID", "Email ID", "e-mail id", "emailid"]:
        question = {"title": "E-MAIL ID"}
        assert map_question_columns([question], [header]) == 1
        assert question["col"] == header


def test_trailing_colon_and_absent_colon_match():
    question = {"title": "Your Home State:"}
    assert map_question_columns([question], ["Your Home State"]) == 1
    assert question["col"] == "Your Home State"


def test_department_slashes_and_spaces_match():
    title = "DEPARTMENT/ BRANCH/ SPECIALISATION"
    assert normalize_header(title) == "departmentbranchspecialisation"
    question = {"title": title}
    assert map_question_columns([question], ["DEPARTMENTBRANCHSPECIALISATION"]) == 1
    assert question["col"] == "DEPARTMENTBRANCHSPECIALISATION"


def test_unmatched_question_uses_none_and_does_not_raise():
    question = {"title": "Question not in CSV"}
    assert map_question_columns([question], ["Name"]) == 0
    assert question["col"] is None
