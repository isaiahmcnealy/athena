import re
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx
from defusedxml import ElementTree

from athena.ingestion.schemas import PaperRecord, arxiv_id

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"
# Backoff of 3, 6, 12, and 24 seconds rides out brief upstream outages during bulk imports.
ATTEMPTS = 5
# arXiv registers each paper's DataCite DOI as 10.48550/arXiv.<identifier>.
ARXIV_DOI = re.compile(r"(?:https?://(?:dx\.)?doi\.org/)?10\.48550/arxiv\.(.+)", re.IGNORECASE)


class ProviderError(Exception):
    """Safe-to-log upstream error. Never includes URLs, headers, or credentials."""


def retry_delay(value: str | None, attempt: int) -> float:
    if value:
        try:
            return max(0, float(value))
        except ValueError:
            try:
                return max(0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
            except (ValueError, TypeError):
                pass
    return 3 * 2**attempt


class ScholarlyClient:
    def __init__(self, client: httpx.Client, sleep: Callable[[float], None] = time.sleep):
        self.client = client
        self.sleep = sleep

    def get(self, url: str, **kwargs) -> httpx.Response:
        for attempt in range(ATTEMPTS):
            final = attempt == ATTEMPTS - 1
            try:
                response = self.client.get(url, **kwargs)
            except httpx.TransportError as error:
                if final:
                    raise ProviderError(
                        f"Upstream connection failed after {ATTEMPTS} attempts "
                        f"({type(error).__name__})"
                    ) from None
                self.sleep(3 * 2**attempt)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if final:
                    raise ProviderError(
                        f"Upstream HTTP {response.status_code} after {ATTEMPTS} attempts"
                    )
                delay = max(3, retry_delay(response.headers.get("retry-after"), attempt))
                if delay > 60:
                    raise ProviderError(
                        "Upstream requested a longer cooldown; retry the import later"
                    )
                self.sleep(delay)
                continue
            if response.status_code != 200:
                raise ProviderError(f"Upstream HTTP {response.status_code}; import stopped")
            if len(response.content) > 16_000_000:
                raise ProviderError("Upstream page exceeded the 16 MB response limit")
            return response
        raise ProviderError("Upstream retry budget exhausted")


def parse_arxiv(content: bytes) -> list[PaperRecord]:
    return parse_arxiv_feed(content)[0]


def parse_arxiv_feed(content: bytes) -> tuple[list[PaperRecord], int | None]:
    """Return the page's records and the total result count the feed reports, if any."""
    root = ElementTree.fromstring(content)
    if root.tag != ATOM + "feed":
        raise ProviderError("Expected an arXiv Atom feed")
    total = (root.findtext(OPENSEARCH + "totalResults") or "").strip()
    records = []
    for entry in root.findall(ATOM + "entry"):

        def value(tag, element=entry):
            return (element.findtext(tag) or "").strip()

        identifier = arxiv_id(value(ATOM + "id"))
        raw = {"atom_entry": ElementTree.tostring(entry, encoding="unicode")}
        records.append(
            PaperRecord(
                source="arxiv",
                source_id=identifier,
                arxiv=identifier,
                title=value(ATOM + "title"),
                abstract=value(ATOM + "summary") or None,
                authors=[
                    a.findtext(ATOM + "name") or "Unknown" for a in entry.findall(ATOM + "author")
                ],
                topics=[c.attrib["term"] for c in entry.findall(ATOM + "category")],
                venue=value(ARXIV + "journal_ref") or None,
                publication_date=datetime.fromisoformat(value(ATOM + "published")).date(),
                source_updated_at=datetime.fromisoformat(value(ATOM + "updated")),
                doi=value(ARXIV + "doi") or None,
                landing_url=f"https://arxiv.org/abs/{identifier}",
                work_type="preprint",
                payload=raw,
            )
        )
    return records, int(total) if total.isdigit() else None


def parse_openalex(work: dict) -> PaperRecord:
    # Keep the upstream record for provenance, but do not ingest/display publisher
    # abstract text in v1. Metadata access alone does not establish abstract reuse rights.
    work = {key: value for key, value in work.items() if key != "abstract_inverted_index"}
    primary = work.get("primary_location") or {}
    source = primary.get("source") or {}
    identifier = work["id"].rstrip("/").rsplit("/", 1)[-1]
    if not identifier.startswith("W") or not identifier[1:].isdigit():
        raise ValueError("Invalid OpenAlex work identifier")
    arxiv_ids = set()
    for location in [primary, *(work.get("locations") or [])]:
        for field in ("landing_page_url", "pdf_url"):
            url = location.get(field) or ""
            if urlparse(url).hostname not in {"arxiv.org", "www.arxiv.org"}:
                continue
            try:
                arxiv_ids.add(arxiv_id(url))
            except ValueError:
                continue
    # OpenAlex often lists an arXiv preprint only under its doi.org address.
    datacite = ARXIV_DOI.fullmatch((work.get("doi") or "").strip())
    if datacite:
        try:
            arxiv_ids.add(arxiv_id(datacite.group(1)))
        except ValueError:
            pass
    # Ambiguous links must not cause an automatic identity merge.
    arxiv = next(iter(arxiv_ids)) if len(arxiv_ids) == 1 else None
    return PaperRecord(
        source="openalex",
        source_id=identifier,
        arxiv=arxiv,
        title=work.get("title") or work.get("display_name") or "",
        authors=[a["author"]["display_name"] for a in work.get("authorships", [])],
        topics=[t["display_name"] for t in work.get("topics", [])][:100],
        venue=source.get("display_name"),
        publication_date=work["publication_date"],
        landing_url=f"https://openalex.org/{identifier}",
        doi=work.get("doi"),
        work_type=work.get("type") or "article",
        source_updated_at=(
            datetime.fromisoformat(work["updated_date"]).replace(tzinfo=UTC)
            if work.get("updated_date")
            else None
        ),
        payload=work,
    )


def fetch_arxiv(http: ScholarlyClient, query: str, limit: int) -> Iterator[PaperRecord]:
    total = 0
    for start in range(0, limit, 100):
        if start:
            http.sleep(3)
        wanted = min(100, limit - start)
        for attempt in range(3):
            response = http.get(
                "https://export.arxiv.org/api/query",
                params={
                    "search_query": query,
                    "start": start,
                    "max_results": wanted,
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                },
            )
            records, reported = parse_arxiv_feed(response.content)
            total = max(total, reported or 0)
            if len(records) >= min(wanted, total - start):
                break
            # arXiv intermittently serves a short page inside the result window it reports.
            # Accepting it would silently truncate the import, so refetch instead.
            if attempt == 2:
                raise ProviderError("arXiv returned an incomplete page after 3 attempts")
            http.sleep(3 * 2**attempt)
        yield from records
        if len(records) < wanted:
            break


def fetch_openalex(
    http: ScholarlyClient, query: str, limit: int, api_key: str = ""
) -> Iterator[PaperRecord]:
    cursor = "*"
    count = 0
    cutoff = datetime.now(UTC).date().isoformat()
    while cursor and count < limit:
        if count:
            http.sleep(1)
        response = http.get(
            "https://api.openalex.org/works",
            params={
                "search": query,
                "per_page": min(100, limit - count),
                "cursor": cursor,
                "sort": "publication_date:desc",
                "filter": (
                    f"to_publication_date:{cutoff},type:article|review|preprint,is_retracted:false"
                ),
            },
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )
        body = response.json()
        for work in body["results"]:
            yield parse_openalex(work)
            count += 1
        next_cursor = body.get("meta", {}).get("next_cursor")
        if not body["results"] or next_cursor == cursor:
            break
        cursor = next_cursor
