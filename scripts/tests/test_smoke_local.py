import importlib.util
import io
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest


@pytest.fixture
def smoke(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "smoke-local.py"
    spec = importlib.util.spec_from_file_location("smoke_local", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # A deterministic clock keeps deadline tests fast without real network calls.
    now = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        module.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds)
    )
    return module


def test_retries_startup_failures_until_ready(smoke, monkeypatch):
    outcomes = iter(
        [
            ConnectionResetError("reset"),
            URLError(ConnectionRefusedError("refused")),
            TimeoutError("timed out"),
            HTTPError(smoke.BASE_URL, 503, "unavailable", {}, None),
            {"status": "ok"},
        ]
    )
    calls = []

    def request(method, path, **kwargs):
        calls.append((method, path, kwargs["timeout"]))
        result = next(outcomes)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(smoke, "request", request)
    smoke.wait_until_ready()
    assert len(calls) == 5
    assert all(
        method == "GET" and path == "/api/health/ready" for method, path, _ in calls
    )
    assert all(0 < timeout <= 2 for _, _, timeout in calls)


def test_readiness_timeout_bounds_requests_and_reports_diagnostics(smoke, monkeypatch):
    timeouts = []

    def request(method, path, *, timeout):
        timeouts.append(timeout)
        smoke.time.sleep(timeout)
        raise ConnectionResetError("reset")

    monkeypatch.setattr(smoke, "request", request)
    with pytest.raises(TimeoutError, match="API not ready.*after 3s.*logs api migrate"):
        smoke.wait_until_ready(timeout=3)
    assert timeouts == [2, 0.75]
    assert smoke.time.monotonic() == 3


@pytest.mark.parametrize("status", [400, 401, 404, 500])
def test_unexpected_http_errors_fail_immediately(smoke, monkeypatch, status):
    error = HTTPError(smoke.BASE_URL, status, "unexpected", {}, None)

    def request(*args, **kwargs):
        raise error

    monkeypatch.setattr(smoke, "request", request)
    with pytest.raises(HTTPError) as caught:
        smoke.wait_until_ready()
    assert caught.value is error
    assert smoke.time.monotonic() == 0


def test_invalid_readiness_payload_fails_immediately(smoke, monkeypatch):
    monkeypatch.setattr(smoke, "request", lambda *args, **kwargs: {"status": "broken"})
    with pytest.raises(AssertionError, match="Unexpected readiness response"):
        smoke.wait_until_ready()
    assert smoke.time.monotonic() == 0


@pytest.mark.parametrize("expected", [200, 503])
def test_request_propagates_unexpected_status_and_accepts_expected_status(
    smoke, monkeypatch, expected
):
    error = HTTPError(
        smoke.BASE_URL,
        503,
        "unavailable",
        {"X-Request-ID": "test-request", "Cache-Control": "no-store"},
        io.BytesIO(b'{"detail": "unavailable"}'),
    )

    def open_request(req, *, timeout):
        raise error

    monkeypatch.setattr(smoke.OPENER, "open", open_request)
    if expected == 503:
        assert smoke.request("GET", "/api/health/ready", expected=503) == {
            "detail": "unavailable"
        }
    else:
        with pytest.raises(HTTPError) as caught:
            smoke.request("GET", "/api/health/ready")
        assert caught.value is error
    assert error.closed
