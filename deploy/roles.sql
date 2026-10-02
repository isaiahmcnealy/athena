-- Least-privilege PostgreSQL roles for the release stack. Safe to rerun.
-- deploy.sh runs this as the owning role inside the db container after migrations.
-- Passwords are read from the container environment, never from a command line.
\set ON_ERROR_STOP on
\getenv web_password ATHENA_WEB_DB_PASSWORD
\getenv ingest_password ATHENA_INGEST_DB_PASSWORD

SELECT 'CREATE ROLE athena_web' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'athena_web') \gexec
SELECT 'CREATE ROLE athena_ingest' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'athena_ingest') \gexec

ALTER ROLE athena_web WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'web_password';
ALTER ROLE athena_ingest WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'ingest_password';
-- The web application only reads. Enforce that in the session as well as through grants.
ALTER ROLE athena_web SET default_transaction_read_only = on;

REVOKE ALL ON DATABASE :"DBNAME" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"DBNAME" TO athena_web, athena_ingest;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO athena_web, athena_ingest;

-- Reset before granting so a removed privilege does not survive a later release.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM athena_web, athena_ingest;
GRANT SELECT ON papers, identifiers, source_records TO athena_web;
GRANT SELECT, INSERT, UPDATE ON papers, identifiers, source_records, import_runs TO athena_ingest;
