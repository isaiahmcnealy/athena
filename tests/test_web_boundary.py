"""Request limits and query interpretation that need no database."""

import pytest
from fastapi.testclient import TestClient

from athena.catalog import CatalogQuery, identifier_lookup
from athena.ratelimit import RateLimiter


def test_budget_allows_a_burst_then_refills_steadily():
    now = [0.0]
    limiter = RateLimiter(60, clock=lambda: now[0])
    assert all(limiter.retry_after("a") == 0 for _ in range(60))
    assert limiter.retry_after("a") == pytest.approx(1.0)
    assert limiter.retry_after("b") == 0  # Clients do not share a budget.
    now[0] += 1.0
    assert limiter.retry_after("a") == 0
    assert limiter.retry_after("a") > 0


def test_refused_requests_do_not_extend_the_wait():
    now = [0.0]
    limiter = RateLimiter(60, clock=lambda: now[0])
    for _ in range(60):
        limiter.retry_after("a")
    for _ in range(100):
        assert limiter.retry_after("a") == pytest.approx(1.0)


def test_tracked_clients_are_bounded():
    limiter = RateLimiter(60, max_clients=3, clock=lambda: 0.0)
    for client in "abcd":
        limiter.retry_after(client)
    assert list(limiter.clients) == ["b", "c", "d"]


def test_rejects_a_non_positive_budget():
    with pytest.raises(ValueError):
        RateLimiter(0)


def test_throttled_requests_get_429_while_health_and_static_stay_open(monkeypatch):
    from athena import main

    monkeypatch.setattr(main, "limiter", RateLimiter(2))
    client = TestClient(main.app)
    # An invalid ID is rejected by validation, so no database is needed.
    assert [client.get("/papers/not-a-uuid").status_code for _ in range(3)] == [422, 422, 429]
    refused = client.get("/api/papers")
    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) >= 1
    assert "X-Request-ID" in refused.headers
    assert client.get("/health/live").status_code == 200
    assert client.get("/static/app.css").status_code == 200


def test_about_page_needs_no_database_and_states_sources():
    from athena import main

    response = TestClient(main.app).get("/about")
    assert response.status_code == 200
    assert "arXiv" in response.text and "OpenAlex" in response.text
    assert "no cookies" in response.text


@pytest.mark.parametrize(
    ("terms", "expected"),
    [
        ("10.1234/Test", ("doi", "10.1234/test")),
        ("https://doi.org/10.1234/test", ("doi", "10.1234/test")),
        ("2401.00001", ("arxiv", "2401.00001")),
        ("arXiv:2401.00001v3", ("arxiv", "2401.00001")),
        ("https://arxiv.org/abs/2401.00001", ("arxiv", "2401.00001")),
        ("graph neural networks", None),
        ("", None),
    ],
)
def test_identifier_queries_are_recognized(terms, expected):
    assert identifier_lookup(terms) == expected


def test_ordering_defaults_to_relevance_only_when_terms_can_be_scored():
    assert CatalogQuery().ordering == "newest"
    assert CatalogQuery(sort="relevance").ordering == "newest"
    assert CatalogQuery(q="graph learning").ordering == "relevance"
    assert CatalogQuery(q="graph learning", sort="newest").ordering == "newest"
    assert CatalogQuery(q="10.1234/test").ordering == "newest"
