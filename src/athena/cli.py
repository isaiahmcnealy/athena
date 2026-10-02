import argparse
import json
import sys

import httpx

from athena.config import get_settings
from athena.db import get_engine
from athena.ingestion.audit import catalog_audit
from athena.ingestion.providers import ProviderError, ScholarlyClient, fetch_arxiv, fetch_openalex
from athena.ingestion.seed import seed_plan
from athena.ingestion.service import run_import
from athena.ingestion.stats import catalog_stats


def emit(event, *, error=False):
    # default=str renders the dates in reports; counts and text are unaffected.
    print(json.dumps(event, default=str), file=sys.stderr if error else sys.stdout, flush=True)


def import_query(http, settings, job):
    records = (
        fetch_arxiv(http, job["query"], job["limit"])
        if job["source"] == "arxiv"
        else fetch_openalex(
            http, job["query"], job["limit"], settings.openalex_api_key.get_secret_value()
        )
    )
    return run_import(get_engine(), job["source"], job["query"], records)


def run_seed(http, settings, jobs, start_at):
    totals = dict.fromkeys(("processed", "inserted", "updated", "rejected"), 0)
    for index, job in enumerate(jobs[start_at - 1 :], start=start_at):
        # Also space requests across query boundaries, including short/empty queries.
        if index > start_at:
            http.sleep(3)
        emit({"event": "query_started", "job": index, "jobs": len(jobs), **job})
        try:
            result = import_query(http, settings, job)
        except Exception as error:
            emit(
                {
                    "event": "seed_stopped",
                    "status": "failed",
                    "job": index,
                    "error_type": type(error).__name__,
                    "provider_error": str(error) if isinstance(error, ProviderError) else None,
                    "message": "Committed records are preserved. Retry this job with the same "
                    "--source and --per-query settings and --start-at " + str(index),
                },
                error=True,
            )
            return 1
        emit({"event": "query_finished", "job": index, "topic": job["topic"], **result})
        for key in totals:
            totals[key] += result[key]
        if result["status"] != "completed":
            emit(
                {"event": "seed_stopped", "status": "partial", "job": index, **totals},
                error=True,
            )
            return 1
    emit({"event": "seed_finished", "status": "completed", **totals})
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Athena catalog administration")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "stats", help="Report actual catalog counts and PostgreSQL storage in bytes"
    )
    commands.add_parser(
        "audit", help="Report catalog coverage and data quality checks; changes nothing"
    )
    ingest = commands.add_parser("ingest", help="Import a bounded query; safe to rerun")
    ingest.add_argument("source", choices=["arxiv", "openalex"])
    ingest.add_argument("--query", help="arXiv search syntax or OpenAlex search terms")
    ingest.add_argument("--limit", type=int, default=50)
    seed = commands.add_parser("seed", help="Populate a diverse AI catalog across 21 topics")
    seed.add_argument("--per-query", type=int, default=125, help="Records per topic and source")
    seed.add_argument("--source", choices=["all", "arxiv", "openalex"], default="all")
    seed.add_argument(
        "--start-at", type=int, default=1, help="Restart at this 1-based query number"
    )
    seed.add_argument("--dry-run", action="store_true", help="Print the plan without network or DB")
    args = parser.parse_args(argv)
    if args.command in {"stats", "audit"}:
        report = catalog_stats if args.command == "stats" else catalog_audit
        try:
            emit(report(get_engine()))
        except Exception as error:
            emit({"status": "failed", "error_type": type(error).__name__}, error=True)
            sys.exit(1)
        return
    if args.command == "ingest":
        if not 1 <= args.limit <= 1000:
            parser.error("--limit must be between 1 and 1000")
        query = args.query or ("cat:cs.LG" if args.source == "arxiv" else "machine learning")
        jobs = [{"source": args.source, "query": query, "limit": args.limit}]
    else:
        if not 1 <= args.per_query <= 1000:
            parser.error("--per-query must be between 1 and 1000")
        jobs = seed_plan(args.per_query, args.source)
        if not 1 <= args.start_at <= len(jobs):
            parser.error(f"--start-at must be between 1 and {len(jobs)}")
        emit(
            {
                "event": "seed_plan",
                "requested_records": sum(job["limit"] for job in jobs[args.start_at - 1 :]),
                "note": "Queries overlap; requested records are not a unique-paper guarantee.",
                "queries": [
                    {"job": index, **job}
                    for index, job in enumerate(jobs, start=1)
                    if index >= args.start_at
                ],
            }
        )
        if args.dry_run:
            return
    settings = get_settings()
    agent = "Athena/0.1 (https://github.com/isaiahmcnealy/athena)"
    if settings.contact_email:
        agent += f" mailto:{settings.contact_email}"
    try:
        with httpx.Client(
            timeout=30, headers={"User-Agent": agent}, follow_redirects=False
        ) as client:
            http = ScholarlyClient(client)
            if args.command == "seed":
                sys.exit(run_seed(http, settings, jobs, args.start_at))
            result = import_query(http, settings, jobs[0])
        emit(result)
        return_code = 0 if result["status"] == "completed" else 1
    except Exception as error:
        emit(
            {
                "status": "failed",
                "error_type": type(error).__name__,
                "provider_error": str(error) if isinstance(error, ProviderError) else None,
                "message": "Import stopped. Check the database and provider availability. "
                "Committed records are preserved; rerun the same query to recover.",
            },
            error=True,
        )
        return_code = 1
    sys.exit(return_code)
