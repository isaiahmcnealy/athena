import argparse
import json
import sys

import httpx

from athena.config import get_settings
from athena.db import get_engine
from athena.ingestion.providers import ScholarlyClient, fetch_arxiv, fetch_openalex
from athena.ingestion.service import run_import


def main():
    parser = argparse.ArgumentParser(description="Athena catalog administration")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="Import a bounded query; safe to rerun")
    ingest.add_argument("source", choices=["arxiv", "openalex"])
    ingest.add_argument("--query", help="arXiv search syntax or OpenAlex search terms")
    ingest.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        parser.error("--limit must be between 1 and 1000")
    settings = get_settings()
    query = args.query or ("cat:cs.LG" if args.source == "arxiv" else "machine learning")
    agent = "Athena/0.1 (https://github.com/isaiahmcnealy/athena)"
    if settings.contact_email:
        agent += f" mailto:{settings.contact_email}"
    try:
        with httpx.Client(
            timeout=30, headers={"User-Agent": agent}, follow_redirects=False
        ) as client:
            http = ScholarlyClient(client)
            records = (
                fetch_arxiv(http, query, args.limit)
                if args.source == "arxiv"
                else fetch_openalex(
                    http, query, args.limit, settings.openalex_api_key.get_secret_value()
                )
            )
            result = run_import(get_engine(), args.source, query, records)
        print(json.dumps(result))
        return_code = 0 if result["status"] == "completed" else 1
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "message": "Import stopped. Check the database and provider availability. "
                    "Committed records are preserved; rerun the same query to recover.",
                }
            ),
            file=sys.stderr,
        )
        return_code = 1
    sys.exit(return_code)
