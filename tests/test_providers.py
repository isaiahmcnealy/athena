import httpx
import pytest
from pydantic import ValidationError

from athena.ingestion.providers import (
    ProviderError,
    ScholarlyClient,
    fetch_arxiv,
    fetch_openalex,
    parse_arxiv,
    parse_openalex,
)
from athena.ingestion.schemas import PaperRecord, arxiv_id, normalize_doi

ARXIV_XML = b"""<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
<entry><id>http://arxiv.org/abs/2401.00001v2</id><title> Graph\n learning </title>
<summary>Abstract text.</summary><published>2024-01-01T00:00:00Z</published>
<updated>2024-01-03T00:00:00Z</updated><author><name>A. Researcher</name></author>
<category term="cs.LG"/><arxiv:doi>https://doi.org/10.1234/ABC</arxiv:doi></entry></feed>"""


def test_arxiv_versions_share_identity_and_keep_updated_time():
    paper = parse_arxiv(ARXIV_XML)[0]
    assert paper.source_id == "2401.00001"
    assert paper.title == "Graph learning"
    assert paper.doi == "10.1234/abc"
    assert paper.source_updated_at.day == 3
    assert paper.authors == ["A. Researcher"]


@pytest.mark.parametrize("value", ["10.1234/ABC", "https://doi.org/10.1234/ABC", "doi:10.1234/ABC"])
def test_doi_normalization(value):
    assert normalize_doi(value) == "10.1234/abc"


def test_invalid_identifiers():
    assert normalize_doi("not-a-doi") is None
    assert arxiv_id("https://arxiv.org/pdf/hep-th/9901001v3.pdf") == "hep-th/9901001"
    with pytest.raises(ValueError):
        arxiv_id("https://example.org/abs/123")


def test_openalex_omits_abstract_and_accepts_missing_optional_metadata():
    paper = parse_openalex(
        {
            "id": "https://openalex.org/W123",
            "title": "A paper",
            "publication_date": "2024-02-01",
            "primary_location": None,
            "abstract_inverted_index": {"Licensed": [0]},
        }
    )
    assert paper.abstract is None
    assert "abstract_inverted_index" not in paper.payload
    assert paper.venue is None
    assert paper.authors == []


def test_openalex_recognizes_versioned_arxiv_links_and_ignores_untrusted_hosts():
    work = {
        "id": "https://openalex.org/W123",
        "title": "A paper",
        "publication_date": "2024-02-01",
        "primary_location": {"landing_page_url": "https://arxiv.org/abs/2401.00001v3"},
        "locations": [
            {"pdf_url": "https://arxiv.org/pdf/2401.00001v2.pdf"},
            {"landing_page_url": "https://example.org/abs/2401.99999"},
        ],
    }
    assert parse_openalex(work).arxiv == "2401.00001"
    work["locations"].append({"landing_page_url": "https://arxiv.org/abs/2401.00002"})
    assert parse_openalex(work).arxiv is None


def test_openalex_derives_arxiv_identity_from_the_arxiv_datacite_doi():
    work = {
        "id": "https://openalex.org/W123",
        "title": "A paper",
        "publication_date": "2024-02-01",
        "doi": "https://doi.org/10.48550/arXiv.2401.00001",
        "primary_location": {"landing_page_url": "https://doi.org/10.48550/arxiv.2401.00001"},
    }
    assert parse_openalex(work).arxiv == "2401.00001"
    assert parse_openalex({**work, "doi": "https://doi.org/10.1234/arxiv.2401.00001"}).arxiv is None
    work["locations"] = [{"landing_page_url": "https://arxiv.org/abs/2401.00002"}]
    assert parse_openalex(work).arxiv is None


def test_upstream_links_cannot_inject_javascript(record):
    with pytest.raises(ValidationError):
        PaperRecord.model_validate({**record.model_dump(), "landing_url": "javascript:alert(1)"})


def test_retry_throttling_then_success():
    statuses = iter([429, 503, 200])
    delays = []
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(next(statuses), headers={"Retry-After": "4"})
        )
    ) as client:
        response = ScholarlyClient(client, sleep=delays.append).get("https://example.org")
    assert response.status_code == 200
    assert delays == [4, 4]


def test_retry_budget_and_secret_redaction():
    requests = []

    def reject(request):
        requests.append(request)
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(reject)) as client:
        with pytest.raises(ProviderError) as error:
            ScholarlyClient(client, sleep=lambda _: None).get("https://example.org?api_key=secret")
    assert len(requests) == 5
    assert "secret" not in str(error.value)


def test_authentication_errors_are_not_retried():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(401))) as client:
        with pytest.raises(ProviderError, match="401"):
            ScholarlyClient(client, sleep=lambda _: pytest.fail("Unexpected retry")).get(
                "https://example.org"
            )


def test_long_retry_after_stops_without_retrying_early():
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(429, headers={"Retry-After": "120"})
        )
    ) as client:
        with pytest.raises(ProviderError, match="cooldown"):
            ScholarlyClient(client, sleep=lambda _: pytest.fail("Unexpected retry")).get(
                "https://example.org"
            )


def arxiv_feed(count, total):
    entries = "".join(
        f"<entry><id>http://arxiv.org/abs/2401.{number:05}v1</id><title>Paper</title>"
        "<published>2024-01-01T00:00:00Z</published><updated>2024-01-01T00:00:00Z</updated>"
        "</entry>"
        for number in range(count)
    )
    return (
        '<feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">'
        f"<opensearch:totalResults>{total}</opensearch:totalResults>{entries}</feed>"
    ).encode()


def test_arxiv_refetches_a_short_page_inside_the_reported_result_window():
    pages = iter([arxiv_feed(1, 40), arxiv_feed(3, 40)])
    delays = []
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=next(pages)))
    ) as client:
        records = list(fetch_arxiv(ScholarlyClient(client, sleep=delays.append), "cat:cs.LG", 3))
    assert len(records) == 3
    assert delays == [3]


def test_arxiv_incomplete_pages_fail_visibly_but_short_final_pages_are_accepted():
    def fetch(count, total):
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=arxiv_feed(count, total))
            )
        ) as client:
            return list(fetch_arxiv(ScholarlyClient(client, sleep=lambda _: None), "cat:cs.LG", 3))

    assert len(fetch(2, 2)) == 2
    with pytest.raises(ProviderError, match="incomplete page"):
        fetch(0, 40)


def test_openalex_pagination_and_key_header():
    seen = []

    def respond(request):
        seen.append(request)
        number = len(seen)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": f"https://openalex.org/W{number}",
                        "title": "Paper",
                        "publication_date": "2024-01-01",
                    }
                ],
                "meta": {"next_cursor": "page2" if number == 1 else None},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        records = list(
            fetch_openalex(ScholarlyClient(client, sleep=lambda _: None), "graph", 2, "key")
        )
    assert len(records) == 2
    assert seen[1].url.params["cursor"] == "page2"
    assert seen[0].headers["Authorization"] == "Bearer key"
    assert "key" not in str(seen[0].url)
    assert "type:article|review|preprint" in seen[0].url.params["filter"]
    assert "to_publication_date:" in seen[0].url.params["filter"]
    assert "is_retracted:false" in seen[0].url.params["filter"]
