FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev
COPY alembic.ini ./
COPY migrations ./migrations
RUN useradd --create-home athena
USER athena
EXPOSE 8000
# The app writes its own structured request logs. Uvicorn's access log would add client
# addresses and full query strings (search terms), so it is turned off.
# Beyond 64 requests in flight, answer 503 at once instead of queueing behind the database
# pool. On SIGTERM, stop accepting connections and give in-flight requests 20 seconds.
CMD ["/app/.venv/bin/uvicorn", "athena.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--limit-concurrency", "64", "--timeout-graceful-shutdown", "20"]
