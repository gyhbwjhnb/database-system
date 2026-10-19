"""Catalog metadata management (member A).

Stores the database version, table schemas and index definitions in
``catalog.json``.  Writes go to a temporary file followed by an atomic
replace so the catalog never ends up half-written.
"""

from __future__ import annotations

import json
import os
import tempfile

from ..types import Column, TableSchema

CATALOG_VERSION = 1
CATALOG_FILE = "catalog.json"


class Catalog:
    def __init__(self, db_dir: str):
        self._db_dir = db_dir
        self._path = os.path.join(db_dir, CATALOG_FILE)
        self._tables: dict[str, dict] = {}
        self._indexes: dict[str, dict] = {}

    @property
    def path(self) -> str:
        return self._path

    # -- persistence ------------------------------------------------------

    def load(self) -> None:
        if not os.path.exists(self._path):
            self._tables = {}
            self._indexes = {}
            return
        with open(self._path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self._tables = payload.get("tables", {})
        self._indexes = payload.get("indexes", {})

    def save(self) -> None:
        os.makedirs(self._db_dir, exist_ok=True)
        payload = {
            "version": CATALOG_VERSION,
            "tables": self._tables,
            "indexes": self._indexes,
        }
        fd, tmp_path = tempfile.mkstemp(dir=self._db_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    # -- tables -----------------------------------------------------------

    def table_exists(self, table: str) -> bool:
        return table in self._tables

    def add_table(self, schema: TableSchema) -> None:
        self._tables[schema.name] = {
            "name": schema.name,
            "columns": [
                {"name": col.name, "type": col.type} for col in schema.columns
            ],
        }

    def get_table_schema(self, table: str) -> TableSchema:
        raw = self._tables[table]
        columns = tuple(
            Column(col["name"], col["type"]) for col in raw["columns"]
        )
        return TableSchema(raw["name"], columns)

    def table_names(self) -> list[str]:
        return list(self._tables.keys())

    # -- indexes ----------------------------------------------------------

    def index_name_exists(self, name: str) -> bool:
        return name in self._indexes

    def index_on_column(self, table: str, column: str) -> bool:
        return any(
            idx["table"] == table and idx["column"] == column
            for idx in self._indexes.values()
        )

    def add_index(self, name: str, table: str, column: str) -> None:
        self._indexes[name] = {"name": name, "table": table, "column": column}

    def get_indexes_for_table(self, table: str) -> list[dict]:
        return [
            dict(idx)
            for idx in self._indexes.values()
            if idx["table"] == table
        ]

    def get_index(self, name: str) -> dict:
        return dict(self._indexes[name])
