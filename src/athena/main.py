import json
import logging
import time
import uuid
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from athena.catalog import CatalogQuery, PaperPage, PaperView, list_papers
from athena.db import get_session
from athena.models import Paper, SourceRecord

ROOT = Path(__file__).parent
app = FastAPI(
    title="Athena", version="0.1.0", description="Research discovery across arXiv and OpenAlex"
)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")
logger = logging.getLogger("athena.requests")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
REQUESTS = Counter("athena_http_requests_total", "HTTP responses", ["method", "route", "status"])
LATENCY = Histogram("athena_http_duration_seconds", "HTTP latency", ["method", "route"])
DB = Annotated[Session, Depends(get_session)]
Filters = Annotated[CatalogQuery, Query()]


@app.middleware("http")
async def observe(request: Request, call_next):
    request_id = str(uuid.uuid4())
    started = time.monotonic()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.url.path not in {"/docs", "/redoc", "/docs/oauth2-redirect"}:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; style-src 'self'; img-src 'self' data:; "
                "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
            )
        return response
    finally:
        elapsed = time.monotonic() - started
        route = getattr(request.scope.get("route"), "path", "unmatched")
        method = request.method if request.method in {"GET", "POST", "HEAD", "OPTIONS"} else "OTHER"
        REQUESTS.labels(method, route, str(status)).inc()
        LATENCY.labels(method, route).observe(elapsed)
        logger.info(
            json.dumps(
                {
                    "request_id": request_id,
                    "method": method,
                    "route": route,
                    "status": status,
                    "duration_ms": round(elapsed * 1000, 2),
                }
            )
        )


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, error: SQLAlchemyError):
    logger.error(json.dumps({"event": "database_error", "error_type": type(error).__name__}))
    if request.url.path.startswith("/api/") or request.url.path.startswith("/health/"):
        return JSONResponse({"detail": "Catalog temporarily unavailable"}, status_code=503)
    return templates.TemplateResponse(request=request, name="unavailable.html", status_code=503)


@app.get("/health/live", tags=["health"])
def live():
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def ready(session: DB):
    session.execute(text("SELECT id FROM papers LIMIT 1"))
    return {"status": "ready"}


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})


@app.get("/api/papers", response_model=PaperPage, tags=["catalog"])
def papers(session: DB, filters: Filters):
    try:
        return list_papers(session, filters)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


def find_paper(session: Session, paper_id: uuid.UUID) -> PaperView:
    paper = session.scalar(
        select(Paper).options(selectinload(Paper.records)).where(Paper.id == paper_id)
    )
    if paper is None:
        raise HTTPException(404, "Paper not found")
    return PaperView.from_paper(paper)


@app.get("/api/papers/{paper_id}", response_model=PaperView, tags=["catalog"])
def paper_api(paper_id: uuid.UUID, session: DB):
    return find_paper(session, paper_id)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home(request: Request, session: DB, filters: Filters):
    page = papers(session, filters)
    count = session.scalar(select(func.count()).select_from(Paper))
    latest = session.scalar(select(func.max(SourceRecord.fetched_at)))
    params = filters.model_dump(exclude_none=True, exclude={"cursor"})
    next_url = (
        "/?" + urlencode({**params, "cursor": page.next_cursor}) if page.next_cursor else None
    )
    return templates.TemplateResponse(
        request=request,
        name="catalog.html",
        context={
            "page": page,
            "filters": filters,
            "catalog_count": count,
            "latest": latest,
            "next_url": next_url,
        },
    )


@app.get("/papers/{paper_id}", response_class=HTMLResponse, include_in_schema=False)
def paper_detail(request: Request, paper_id: uuid.UUID, session: DB):
    return templates.TemplateResponse(
        request=request,
        name="paper.html",
        context={
            "paper": find_paper(session, paper_id),
        },
    )
