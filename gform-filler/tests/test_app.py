import asyncio

import pytest
from textual.containers import Vertical
from textual.widgets import Button, Input, Static

import app as app_module
from app import GFormFiller, is_valid_form_url, main


@pytest.mark.parametrize(
    "url",
    [
        "https://forms.gle/abc123",
        "http://forms.gle/abc123",
        "https://docs.google.com/forms/d/e/form-id/viewform",
        "https://DOCS.GOOGLE.COM/forms/d/e/form-id/viewform?usp=sharing",
    ],
)
def test_accepts_supported_google_form_urls(url: str):
    assert is_valid_form_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://forms.gle",
        "https://example.com/forms/d/e/form-id/viewform",
        "https://docs.google.com/forms/d/form-id/viewform",
        "https://docs.google.com.evil.test/forms/d/e/form-id/viewform",
        "javascript:alert(1)",
    ],
)
def test_rejects_unsupported_urls(url: str):
    assert not is_valid_form_url(url)


def test_first_tui_step_requests_form_url_and_keeps_invalid_url_inline():
    async def check_app():
        app = GFormFiller()
        async with app.run_test() as pilot:
            assert app.query_one("#step_form", Vertical).display
            assert app.query_one("#form_url", Input).value == ""
            app.query_one("#form_url", Input).value = "not-a-form"
            clicked = await pilot.click("#form_next")
            assert clicked
            await pilot.pause()
            assert app.query_one("#step_form", Vertical).display
            assert "forms.gle" in str(app.query_one("#form_error", Static).render())

    asyncio.run(check_app())


def test_valid_url_scans_questions_then_creates_template(tmp_path, monkeypatch):
    questions = [{
        "title": "Name",
        "entry": 123,
        "type": 0,
        "type_name": "short text",
        "required": True,
        "col": None,
    }]
    monkeypatch.setattr(app_module, "fetch_form_html", lambda url: "form html")
    monkeypatch.setattr(app_module, "parse_form_schema", lambda html: questions)

    async def check_flow():
        app = GFormFiller()
        async with app.run_test(size=(100, 40)) as pilot:
            app.query_one("#form_url", Input).value = "https://forms.gle/sample"
            assert await pilot.click("#form_next")
            for _ in range(20):
                await pilot.pause(0.05)
                if app.questions:
                    break

            assert app.questions == questions
            assert app.query_one("#step_questions", Vertical).display
            assert app.query_one("#question_table").row_count == 1
            assert await pilot.click("#questions_next")

            csv_path = tmp_path / "responses.csv"
            app.query_one("#csv_path", Input).value = str(csv_path)
            assert await pilot.click("#csv_load")
            assert csv_path.exists()
            assert "Fill this in, then restart the app." in str(app.query_one("#csv_message", Static).render())
            assert app.query_one("#template_exit", Button).display

    asyncio.run(check_flow())


def test_main_launches_tui_without_reading_cli_arguments(monkeypatch):
    launched = []
    monkeypatch.setattr(GFormFiller, "run", lambda self: launched.append(self))

    main()

    assert len(launched) == 1
    assert isinstance(launched[0], GFormFiller)
