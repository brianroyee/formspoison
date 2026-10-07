from types import SimpleNamespace

import pytest

import submitter


class FakeResponse:
    def __init__(self, status: int):
        self.status = status
        self.url = "https://docs.google.com/forms/d/e/form-id/formResponse"
        self.request = SimpleNamespace(method="POST")


class FakeResponseContext:
    def __init__(self, status: int, matcher):
        self.value = FakeResponse(status)
        assert matcher(self.value)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeLocator:
    @property
    def first(self):
        return self

    def filter(self, **kwargs):
        return self

    def count(self):
        return 1

    def click(self):
        pass

    def evaluate(self, *args):
        pass


class FakePage:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.goto_calls = []
        self.close_calls = 0

    def goto(self, url, **kwargs):
        self.goto_calls.append(url)

    def locator(self, selector):
        return FakeLocator()

    def expect_response(self, matcher, **kwargs):
        return FakeResponseContext(self.statuses.pop(0), matcher)

    def close(self):
        self.close_calls += 1


class FakeBrowser:
    def __init__(self, statuses):
        self.page = FakePage(statuses)
        self.new_page_calls = 0
        self.close_calls = 0

    def new_page(self):
        self.new_page_calls += 1
        return self.page

    def close(self):
        self.close_calls += 1


class FakeChromium:
    def __init__(self, browser):
        self.browser = browser
        self.launch_calls = 0

    def launch(self, **kwargs):
        self.launch_calls += 1
        return self.browser


class FakePlaywright:
    def __init__(self, statuses):
        self.browser = FakeBrowser(statuses)
        self.chromium = FakeChromium(self.browser)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_submission_counts_http_results_reuses_page_and_obeys_delay(tmp_path, monkeypatch):
    fake_playwright = FakePlaywright([200, 503, 302])
    monkeypatch.setattr(submitter, "sync_playwright", lambda: fake_playwright)
    sleeps = []
    monkeypatch.setattr(submitter.time, "sleep", sleeps.append)
    monkeypatch.setattr(submitter.random, "uniform", lambda low, high: 0.2)
    monkeypatch.chdir(tmp_path)
    rows = [{"private": "never-log-this"}, {"private": "never-log-this"}, {"private": "never-log-this"}]
    progress = []

    result = submitter.run_submission(
        "https://forms.gle/example",
        [],
        rows,
        delay=1.5,
        progress_callback=progress.append,
    )

    assert (result["completed"], result["success"], result["failed"]) == (3, 2, 1)
    assert result["failures"] == [{"row": 2, "message": "Unexpected HTTP status 503"}]
    assert fake_playwright.chromium.launch_calls == 1
    assert fake_playwright.browser.new_page_calls == 1
    assert len(fake_playwright.browser.page.goto_calls) == 3
    assert sleeps == pytest.approx([1.7, 1.7])
    assert [event["status"] for event in progress] == ["success", "failed", "success"]
    assert "never-log-this" not in (tmp_path / "submission_log.txt").read_text(encoding="utf-8")
    assert "row=2 status=failed http=503" in (tmp_path / "submission_log.txt").read_text(encoding="utf-8")


def test_submission_stops_after_current_row_without_extra_delay(tmp_path, monkeypatch):
    fake_playwright = FakePlaywright([200, 200])
    monkeypatch.setattr(submitter, "sync_playwright", lambda: fake_playwright)
    sleeps = []
    monkeypatch.setattr(submitter.time, "sleep", sleeps.append)
    monkeypatch.chdir(tmp_path)
    cancellation = submitter.threading.Event()

    def stop_after_first_row(update):
        cancellation.set()

    result = submitter.run_submission(
        "https://forms.gle/example",
        [],
        [{}, {}],
        delay=1.0,
        cancel_event=cancellation,
        progress_callback=stop_after_first_row,
    )

    assert result["completed"] == 1
    assert result["stopped"] is True
    assert len(fake_playwright.browser.page.goto_calls) == 1
    assert sleeps == []


def test_submission_delay_cannot_be_less_than_one_second():
    with pytest.raises(ValueError, match="at least 1.0"):
        submitter.run_submission("https://forms.gle/example", [], [], delay=0.9)
