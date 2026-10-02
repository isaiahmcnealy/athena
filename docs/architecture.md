# Architecture: first working release

## Scope

Athena helps readers discover AI research and its applications across domains. It uses
existing scholarly catalogs, so useful content does not depend on creators joining the app.
This release implements the searchable catalog. Personal libraries and recommendations follow.

```text
arXiv / OpenAlex -> bounded CLI importer -> PostgreSQL
                                              ^
Browser -> FastAPI / Jinja templates ----------|
                  |
             metrics + JSON request logs
```

The UI and API share a catalog query layer. Ingestion owns provider adapters and normalized
records. PostgreSQL owns canonical papers, unique identifiers, source records, and import runs.
External APIs are never called by web requests. There is no implicit network activity on startup.

## Decisions

1. A modular monolith keeps transactions and deployments understandable. Import jobs have a
   separate execution path but share schema and libraries with the application.
2. PostgreSQL provides real transaction semantics and a GIN full-text index. The API caps page size,
   uses cursor pagination, and eager-loads provenance to avoid per-paper queries.
3. Server-rendered HTML provides an accessible, small first UI without introducing a second
   application runtime. The JSON API supports a later React client without backend replacement.
4. Ingestion uses deterministic identifiers, per-record transactions, and a short transaction-scoped
   advisory lock for identity resolution. This deliberately favors correctness over parallel write
   throughput. No network request occurs while that lock is held.
5. arXiv owns canonical title/abstract/date when present; OpenAlex supplies metadata for other papers.
   Both source records remain available. DOI links can connect records, but probable preprint/version
   matches are not guessed. A conflicting mapping requires operator review.
6. Do not infer publication review status from a metadata source or journal-reference string.
7. Secrets live in environment variables. `.env` is ignored. Upstream exception strings and payloads
   are not logged; they may contain URLs or sensitive query parameters.

## Release sequence

- **0.1 Catalog:** real imports, lexical search, filters, detail pages, provenance, tests.
- **0.2 Library:** authentication, collections, interests, follows, explicit relevance feedback.
- **0.3 Discovery:** lexical evaluation set, versioned pretrained embeddings, similar papers,
  exact-vector baseline, measured approximate indexing, model/index compatibility.
- **0.4 Operations:** replayable change pipeline when multiple consumers justify it, feature history,
  dataset/model lineage, deployment validation, load and failure experiments.

Feast, Kafka, Ray Serve, Kubernetes, cloud infrastructure, and a learned behavioral ranker remain
optional until a measurable need or a bounded educational experiment justifies them.
