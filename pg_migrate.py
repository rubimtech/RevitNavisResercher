#!/usr/bin/env python3
"""
pg_migrate.py — Migrate data from SQLite (revit_api.db, revit_codebase.db) to PostgreSQL.

Usage:
    python pg_migrate.py [--pg-host localhost] [--pg-port 5432] [--pg-db revitnavis]
                         [--pg-user postgres] [--pg-password postgres]
                         [--batch-size 500]

Connects to PostgreSQL, creates tables from postgres/init.sql, then copies data
in batches. Idempotent: clears tables before migration.
"""

import argparse
import sqlite3
import time

import psycopg2
from psycopg2.extras import execute_values

SCHEMA_FILE = "postgres/init.sql"

TABLES_IN_ORDER = [
    "api_entries",
    "api_entry_versions",
    "api_version_tree",
    "api_content",
    "api_diffs",
    "whatsnew_entries",
    "code_files",
    "code_entries",
]

# Map: table -> (sqlite_db_file, sqlite_query, columns)
TABLE_SOURCES = {
    "api_entries": (
        "revit_api.db",
        "SELECT href, title, short_title, namespace, tag, entry_type, member_of, member_of_href, description, folder, is_structural, path, created_at FROM api_entries",
        ["href", "title", "short_title", "namespace", "tag", "entry_type", "member_of", "member_of_href", "description", "folder", "is_structural", "path", "created_at"],
    ),
    "api_entry_versions": (
        "revit_api.db",
        "SELECT href, version, status, content_hash FROM api_entry_versions",
        ["href", "version", "status", "content_hash"],
    ),
    "api_version_tree": (
        "revit_api.db",
        "SELECT version, href, parent_href, sort_order, depth FROM api_version_tree",
        ["version", "href", "parent_href", "sort_order", "depth"],
    ),
    "api_content": (
        "revit_api.db",
        "SELECT href, content_md, fetched_at, fetch_error FROM api_content",
        ["href", "content_md", "fetched_at", "fetch_error"],
    ),
    "api_diffs": (
        "revit_api.db",
        "SELECT version_from, version_to, href, diff_type, old_status, new_status FROM api_diffs",
        ["version_from", "version_to", "href", "diff_type", "old_status", "new_status"],
    ),
    "whatsnew_entries": (
        "revit_api.db",
        "SELECT id, version, section, subsection, title, content, content_type, source, created_at FROM whatsnew_entries",
        ["id", "version", "section", "subsection", "title", "content", "content_type", "source", "created_at"],
    ),
    "code_files": (
        "revit_codebase.db",
        "SELECT id, file_name, file_path, summary, full_code FROM code_files",
        ["id", "file_name", "file_path", "summary", "full_code"],
    ),
    "code_entries": (
        "revit_codebase.db",
        "SELECT id, file_name, file_path, entry_type, summary, content FROM code_entries",
        ["id", "file_name", "file_path", "entry_type", "summary", "content"],
    ),
}


def create_schema(pg_conn):
    with open(SCHEMA_FILE, "r") as f:
        schema_sql = f.read()
    with pg_conn.cursor() as cur:
        cur.execute(schema_sql)
    pg_conn.commit()
    print("Schema created/verified.")


def clear_tables(pg_conn):
    with pg_conn.cursor() as cur:
        for table in reversed(TABLES_IN_ORDER):
            cur.execute(f"DELETE FROM {table}")
    pg_conn.commit()
    print("Tables cleared.")


def migrate_table(pg_conn, table_name, batch_size):
    db_file, query, columns = TABLE_SOURCES[table_name]
    placeholders = ",".join(["%s"] * len(columns))
    col_names = ",".join(columns)
    insert_sql = f"INSERT INTO {table_name} ({col_names}) VALUES %s ON CONFLICT DO NOTHING"

    sqlite_conn = sqlite3.connect(db_file)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cur = sqlite_conn.cursor()

    sqlite_cur.execute(f"SELECT COUNT(*) as cnt FROM ({query})")
    total = sqlite_cur.fetchone()["cnt"]
    print(f"  {table_name}: {total} rows to migrate")

    sqlite_cur.execute(query)
    rows_batch = []
    count = 0
    t0 = time.time()

    for row in sqlite_cur:
        rows_batch.append(tuple(row))
        if len(rows_batch) >= batch_size:
            with pg_conn.cursor() as cur:
                execute_values(cur, insert_sql, rows_batch, page_size=batch_size)
            pg_conn.commit()
            count += len(rows_batch)
            rows_batch = []
            print(f"    {table_name}: {count}/{total} ({time.time()-t0:.1f}s)")

    if rows_batch:
        with pg_conn.cursor() as cur:
            execute_values(cur, insert_sql, rows_batch, page_size=batch_size)
        pg_conn.commit()
        count += len(rows_batch)

    sqlite_conn.close()
    print(f"  {table_name}: migrated {count} rows in {time.time()-t0:.1f}s")


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite -> PostgreSQL")
    parser.add_argument("--pg-host", default="localhost")
    parser.add_argument("--pg-port", type=int, default=5432)
    parser.add_argument("--pg-db", default="revitnavis")
    parser.add_argument("--pg-user", default="postgres")
    parser.add_argument("--pg-password", default="postgres")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    pg_conn = psycopg2.connect(
        host=args.pg_host,
        port=args.pg_port,
        dbname=args.pg_db,
        user=args.pg_user,
        password=args.pg_password,
    )

    create_schema(pg_conn)
    clear_tables(pg_conn)

    for table in TABLES_IN_ORDER:
        migrate_table(pg_conn, table, args.batch_size)

    pg_conn.close()
    print("\nMigration complete!")


if __name__ == "__main__":
    main()
