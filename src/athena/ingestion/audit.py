"""A read-only data quality report for the catalog. It changes nothing and repairs nothing."""

from sqlalchemy import text

SECTIONS = {
    "totals": """
        SELECT
            (SELECT count(*) FROM papers) AS papers,
            (SELECT count(*) FROM source_records) AS source_records,
            (SELECT count(*) FROM identifiers) AS identifier_keys,
            (SELECT min(publication_date) FROM papers) AS earliest_publication,
            (SELECT max(publication_date) FROM papers) AS latest_publication,
            (SELECT min(fetched_at) FROM source_records) AS oldest_fetch,
            (SELECT max(fetched_at) FROM source_records) AS latest_fetch
    """,
    # Which providers hold a record for each paper, not only the one that owns its metadata.
    "source_coverage": """
        SELECT sources, count(*) AS papers
        FROM (
            SELECT string_agg(DISTINCT source, '+' ORDER BY source) AS sources
            FROM source_records GROUP BY paper_id
        ) per_paper
        GROUP BY sources ORDER BY sources
    """,
    "by_year": """
        SELECT extract(year FROM publication_date)::int AS year, count(*) AS papers
        FROM papers GROUP BY 1 ORDER BY 1 DESC
    """,
    "by_type": """
        SELECT primary_source, work_type, count(*) AS papers
        FROM papers GROUP BY 1, 2 ORDER BY 3 DESC, 1, 2
    """,
    # Search and any later text model see only the title when the abstract is missing.
    "text_availability": """
        SELECT primary_source,
               count(*) AS papers,
               count(*) FILTER (WHERE abstract IS NULL) AS without_abstract,
               count(*) FILTER (WHERE venue IS NULL) AS without_venue,
               count(*) FILTER (WHERE doi IS NULL) AS without_doi,
               count(*) FILTER (WHERE jsonb_array_length(authors) = 0) AS without_authors,
               count(*) FILTER (WHERE jsonb_array_length(topics) = 0) AS without_topics
        FROM papers GROUP BY 1 ORDER BY 1
    """,
    "top_topics": """
        SELECT topic, count(*) AS papers
        FROM papers, jsonb_array_elements_text(topics) AS topic
        GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 25
    """,
    "import_runs": """
        SELECT status, count(*) AS runs, coalesce(sum(rejected), 0) AS rejected_records
        FROM import_runs GROUP BY 1 ORDER BY 1
    """,
}

# Each check counts records a reader or a recommender could trip over. Zero is the goal.
CHECKS = {
    "future_publication_dates": "SELECT count(*) FROM papers WHERE publication_date > current_date",
    # Titles never drive merges, so these are reported for review, not treated as errors.
    "papers_sharing_a_title": """
        SELECT coalesce(sum(copies), 0) FROM (
            SELECT count(*) AS copies FROM papers GROUP BY lower(title) HAVING count(*) > 1
        ) shared
    """,
    "titles_shared_by_several_papers": """
        SELECT count(*) FROM (
            SELECT 1 FROM papers GROUP BY lower(title) HAVING count(*) > 1
        ) shared
    """,
    # An OpenAlex paper whose DOI is an arXiv DOI, while that arXiv ID belongs to another paper.
    "unmerged_arxiv_doi_pairs": """
        SELECT count(*) FROM papers p
        JOIN identifiers i ON i.scheme = 'arxiv'
            AND lower(p.doi) = '10.48550/arxiv.' || lower(i.value)
            AND i.paper_id <> p.id
    """,
    "papers_without_a_source_record": """
        SELECT count(*) FROM papers p
        WHERE NOT EXISTS (SELECT 1 FROM source_records s WHERE s.paper_id = p.id)
    """,
    "papers_without_an_identifier": """
        SELECT count(*) FROM papers p
        WHERE NOT EXISTS (SELECT 1 FROM identifiers i WHERE i.paper_id = p.id)
    """,
    "imports_left_running": "SELECT count(*) FROM import_runs WHERE status = 'running'",
    "records_rejected_for_identity_conflicts": "SELECT coalesce(sum(rejected), 0) FROM import_runs",
}


def catalog_audit(engine) -> dict:
    with engine.connect() as connection:
        # One snapshot for every query, and a guarantee that the audit cannot write.
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        report = {
            name: [dict(row) for row in connection.execute(text(query)).mappings()]
            for name, query in SECTIONS.items()
        }
        report["totals"] = report["totals"][0]
        report["checks"] = {
            name: int(connection.execute(text(query)).scalar_one())
            for name, query in CHECKS.items()
        }
        return report
