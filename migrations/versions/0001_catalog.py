"""Initial catalog and ingestion provenance. Frozen schema, independent of application models."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE papers (
            id UUID PRIMARY KEY,
            title TEXT NOT NULL,
            abstract TEXT,
            authors JSONB NOT NULL,
            topics JSONB NOT NULL,
            venue TEXT,
            publication_date DATE NOT NULL,
            primary_source VARCHAR(20) NOT NULL,
            landing_url TEXT NOT NULL,
            doi TEXT,
            work_type VARCHAR(60) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            search_document TSVECTOR GENERATED ALWAYS AS (
                setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(abstract, '')), 'B')
            ) STORED
        );
        CREATE INDEX ix_papers_date_id ON papers (publication_date DESC, id DESC);
        CREATE INDEX ix_papers_search ON papers USING GIN (search_document);
        CREATE TABLE identifiers (
            scheme VARCHAR(20) NOT NULL,
            value TEXT NOT NULL,
            paper_id UUID NOT NULL REFERENCES papers(id),
            PRIMARY KEY (scheme, value)
        );
        CREATE INDEX ix_identifiers_paper_id ON identifiers(paper_id);
        CREATE TABLE source_records (
            source VARCHAR(20) NOT NULL,
            source_id TEXT NOT NULL,
            paper_id UUID NOT NULL REFERENCES papers(id),
            payload JSONB NOT NULL,
            source_updated_at TIMESTAMPTZ,
            fetched_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (source, source_id)
        );
        CREATE INDEX ix_source_records_paper_id ON source_records(paper_id);
        CREATE TABLE import_runs (
            id UUID PRIMARY KEY,
            source VARCHAR(20) NOT NULL,
            query TEXT NOT NULL,
            status VARCHAR(20) NOT NULL,
            processed INTEGER NOT NULL,
            inserted INTEGER NOT NULL,
            updated INTEGER NOT NULL,
            rejected INTEGER NOT NULL,
            last_source_id TEXT,
            error TEXT,
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ
        );
    """)


def downgrade():
    op.execute("DROP TABLE import_runs, source_records, identifiers, papers")
