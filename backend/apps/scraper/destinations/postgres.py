"""
Push rows into a user-supplied external Postgres database.

config:
    dsn:    postgres connection string (required)
    table:  destination table name (required)
    schema: optional schema name (default "public")

Creates the table if missing (all columns TEXT + an auto id), then appends rows.
Identifiers are quoted via ``psycopg2.sql`` so table/column names can't inject.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from .base import BaseDestination, DeliveryResult


class PostgresDestination(BaseDestination):
    def validate(self) -> None:
        if not self.config.get('dsn'):
            raise ValueError("postgres destination requires 'dsn'")
        if not self.config.get('table'):
            raise ValueError("postgres destination requires 'table'")

    def deliver(self, columns: List[str], rows: List[Dict[str, Any]]) -> DeliveryResult:
        self.validate()
        if not rows:
            return DeliveryResult(success=True, rows_delivered=0)

        import psycopg2
        from psycopg2 import sql

        schema = self.config.get('schema', 'public')
        table = self.config['table']

        def _val(v: Any) -> Any:
            if isinstance(v, (dict, list)):
                return json.dumps(v, ensure_ascii=False)
            return v

        table_ident = sql.Identifier(schema, table)
        col_idents = [sql.Identifier(c) for c in columns]

        conn = psycopg2.connect(self.config['dsn'])
        try:
            conn.autocommit = False
            with conn.cursor() as cur:
                cols_ddl = sql.SQL(', ').join(
                    sql.SQL("{} TEXT").format(sql.Identifier(c)) for c in columns
                )
                cur.execute(sql.SQL(
                    "CREATE TABLE IF NOT EXISTS {} (_id BIGSERIAL PRIMARY KEY, {})"
                ).format(table_ident, cols_ddl))

                # The table may predate columns that later runs discovered —
                # without this every INSERT fails once the schema grows.
                for c in columns:
                    cur.execute(sql.SQL(
                        "ALTER TABLE {} ADD COLUMN IF NOT EXISTS {} TEXT"
                    ).format(table_ident, sql.Identifier(c)))

                insert = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    table_ident,
                    sql.SQL(', ').join(col_idents),
                    sql.SQL(', ').join(sql.Placeholder() * len(columns)),
                )
                for row in rows:
                    cur.execute(insert, [_val(row.get(c)) for c in columns])
            conn.commit()
            return DeliveryResult(success=True, rows_delivered=len(rows),
                                  detail={'table': f"{schema}.{table}"})
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            return DeliveryResult(success=False, error=str(e))
        finally:
            conn.close()
