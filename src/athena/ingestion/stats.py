from sqlalchemy import text


def catalog_stats(engine):
    with engine.connect() as connection:
        summary = dict(
            connection.execute(
                text("""
                    SELECT
                        (SELECT count(*) FROM papers) AS papers,
                        (SELECT count(*) FROM source_records) AS source_records,
                        (SELECT count(*) FROM identifiers) AS identifier_keys,
                        (SELECT count(*) FROM (
                            SELECT paper_id FROM source_records
                            GROUP BY paper_id HAVING count(DISTINCT source) > 1
                        ) shared) AS multi_source_papers,
                        pg_database_size(current_database()) AS database_bytes
                """)
            )
            .mappings()
            .one()
        )
        summary["relations"] = [
            dict(row)
            for row in connection.execute(
                text("""
                    SELECT relname AS name,
                           pg_total_relation_size(relid) AS total_bytes,
                           pg_indexes_size(relid) AS index_bytes
                    FROM pg_statio_user_tables
                    WHERE schemaname = current_schema()
                      AND relname IN ('papers', 'source_records', 'identifiers', 'import_runs')
                    ORDER BY relname
                """)
            ).mappings()
        ]
        summary["catalog_bytes"] = sum(row["total_bytes"] for row in summary["relations"])
        return summary
