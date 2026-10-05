import httpx
import pytest
import respx

from app.services.sources.http import PoliteHttpClient, SourceHTTPError
from app.services.sources.text import (
    dedupe_hash,
    detect_employment_type,
    detect_remote,
    html_to_text,
    normalize_key,
)


def test_html_to_text_strips_tags_keeps_structure_and_caps() -> None:
    html = "<h2>About</h2><p>We build <b>robots</b>.</p><ul><li>Python</li><li>ROS&nbsp;2</li></ul><script>x()</script>"
    assert html_to_text(html) == "About\nWe build robots.\n\n- Python\n- ROS 2"
    assert html_to_text("&lt;p&gt;Double &amp;amp; encoded&lt;/p&gt;") == "Double & encoded"
    assert len(html_to_text("<p>" + "word " * 5000 + "</p>")) <= 12_000
    assert html_to_text(None) == ""


@pytest.mark.parametrize(
    ("title", "hint", "expected"),
    [
        ("Software Engineering Intern", None, "internship"),
        ("Summer Internship - Backend", "Full-time", "internship"),  # title wins
        ("Backend Engineer", "Full time", "full_time"),
        ("Backend Engineer", "FullTime", "full_time"),
        ("Backend Engineer", "Intern", "internship"),
        ("Data Engineer (Contract)", None, "contract"),
        ("Designer", "PartTime", "part_time"),
        ("Internal Tools Engineer", None, None),  # "Internal" is not "intern"
        ("Backend Engineer", None, None),
    ],
)
def test_detect_employment_type(title: str, hint: str | None, expected: str | None) -> None:
    assert detect_employment_type(title, hint) == expected


@pytest.mark.parametrize(
    ("location", "workplace", "is_remote", "expected"),
    [
        ("Remote - India", None, None, True),
        ("Bengaluru", "onsite", None, False),
        ("Bengaluru", "Hybrid", None, False),
        ("Anywhere", None, None, True),
        ("Bengaluru", None, None, None),
        ("Bengaluru", "remote", None, True),
        ("Remote", "onsite", False, False),  # explicit flag wins
    ],
)
def test_detect_remote(
    location: str, workplace: str | None, is_remote: bool | None, expected: bool | None
) -> None:
    assert detect_remote(location, workplace, is_remote) == expected


def test_dedupe_hash_normalises_case_punctuation_cities_and_domain() -> None:
    a = dedupe_hash("www.Acme.com", "Acme", "Backend Engineer (Python)", "Bangalore, India")
    b = dedupe_hash("acme.com", "ACME Inc", "backend engineer python", "bengaluru india")
    assert a == b
    assert a != dedupe_hash("acme.com", "Acme", "Frontend Engineer", "Bengaluru, India")
    # Without a domain, the company name is the key.
    assert dedupe_hash(None, "Acme", "SWE", None) == dedupe_hash(None, "acme", "swe", "")
    assert normalize_key("Gurgaon") == "gurugram"


# --- PoliteHttpClient --------------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@respx.mock
async def test_requests_to_one_host_are_spaced_one_second_apart() -> None:
    respx.get(url__startswith="https://a.example/").mock(return_value=httpx.Response(200, json={}))
    respx.get(url__startswith="https://b.example/").mock(return_value=httpx.Response(200, json={}))
    clock = Clock()
    http = PoliteHttpClient(sleep=clock.sleep, clock=clock)
    await http.get("https://a.example/1")
    await http.get("https://b.example/1")  # other host: no wait
    await http.get("https://a.example/2")  # same host: waits out the remaining interval
    assert clock.sleeps == [pytest.approx(1.0)]


@respx.mock
async def test_retries_server_errors_then_succeeds() -> None:
    route = respx.get("https://a.example/x").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200),
        ]
    )
    clock = Clock()
    http = PoliteHttpClient(min_interval_seconds=0, sleep=clock.sleep, clock=clock)
    response = await http.get("https://a.example/x")
    assert response.status_code == 200
    assert route.call_count == 3
    assert clock.sleeps[-1] >= 7  # Retry-After honoured


@respx.mock
async def test_client_errors_are_not_retried() -> None:
    route = respx.get("https://a.example/missing").mock(return_value=httpx.Response(404))
    http = PoliteHttpClient(min_interval_seconds=0, sleep=Clock().sleep)
    with pytest.raises(SourceHTTPError) as err:
        await http.get("https://a.example/missing")
    assert err.value.status == 404
    assert route.call_count == 1


@respx.mock
async def test_network_errors_retried_then_raised() -> None:
    route = respx.get("https://a.example/down").mock(side_effect=httpx.ConnectError("refused"))
    http = PoliteHttpClient(min_interval_seconds=0, max_retries=2, sleep=Clock().sleep)
    with pytest.raises(SourceHTTPError, match="network error"):
        await http.get("https://a.example/down")
    assert route.call_count == 3
