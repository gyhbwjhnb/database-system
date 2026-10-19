"""StorageEngine: the public storage/catalog service (member A).

Implements ``dbms.contracts.StoragePort``.  Owns the catalog, heap files,
LRU buffer pool and persistent equality indexes, and validates every value
and identifier at the API boundary so malformed data cannot be written even
when the SQL frontend is bypassed.
"""

from __future__ import annotations

import os
import re
from typing import Iterator

from ..types import (
    BufferStats,
    RID,
    RowRef,
    SchemaError,
    StorageError,
    TableSchema,
    TypeMismatchError,
    Value,
    Column,
)
from . import page as page_mod
from .buffer import BufferPool
from .catalog import Catalog
from .disk import DiskManager
from .heap import HeapTable
from .index import HashIndex

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
INT_MIN = -(2**63)
INT_MAX = 2**63 - 1
MAX_TEXT_BYTES = 255


class StorageEngine:
    def __init__(self, db_dir: str, buffer_pages: int = 64):
        self._db_dir = db_dir
        os.makedirs(db_dir, exist_ok=True)
        self._tables_dir = os.path.join(db_dir, "tables")
        self._indexes_dir = os.path.join(db_dir, "indexes")
        os.makedirs(self._tables_dir, exist_ok=True)
        os.makedirs(self._indexes_dir, exist_ok=True)

        self._catalog = Catalog(db_dir)
        self._catalog.load()
        self._disk = DiskManager(self._tables_dir)
        self._buffer = BufferPool(self._disk, capacity=buffer_pages)
        self._heap = HeapTable(self._disk, self._buffer)

        # Load all persisted indexes into memory.
        self._indexes: dict[str, HashIndex] = {}
        seen: set[str] = set()
        for table in self._catalog.table_names():
            for idx in self._catalog.get_indexes_for_table(table):
                name = idx["name"]
                if name in seen:
                    continue
                seen.add(name)
                hash_index = HashIndex(
                    self._indexes_dir, idx["table"], idx["column"]
                )
                hash_index.load()
                self._indexes[name] = hash_index

        self._closed = False

    # -- shared validation ------------------------------------------------

    def _check_open(self) -> None:
        if self._closed:
            raise StorageError("storage engine is closed")

    @staticmethod
    def _check_identifier(name: object, kind: str) -> str:
        if not isinstance(name, str) or not _IDENT_RE.match(name):
            raise SchemaError(f"invalid {kind} identifier: {name!r}")
        return name.lower()

    def _require_table(self, table: str) -> TableSchema:
        if not self._catalog.table_exists(table):
            raise SchemaError(f"unknown table: {table}")
        return self._catalog.get_table_schema(table)

    @staticmethod
    def _column_index(schema: TableSchema, column: str) -> int:
        names = [col.name for col in schema.columns]
        if column not in names:
            raise SchemaError(
                f"table {schema.name} has no column {column}"
            )
        return names.index(column)

    def _validate_value(self, value: object, column: Column) -> None:
        if column.type == "INT":
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeMismatchError(
                    f"column {column.name} expects INT, got "
                    f"{type(value).__name__}"
                )
            if value < INT_MIN or value > INT_MAX:
                raise TypeMismatchError(
                    f"integer value {value} out of 64-bit range"
                )
        elif column.type == "TEXT":
            if not isinstance(value, str):
                raise TypeMismatchError(
                    f"column {column.name} expects TEXT, got "
                    f"{type(value).__name__}"
                )
            if len(value.encode("utf-8")) > MAX_TEXT_BYTES:
                raise TypeMismatchError(
                    f"text value for {column.name} exceeds "
                    f"{MAX_TEXT_BYTES} UTF-8 bytes"
                )
        else:  # pragma: no cover - guarded at table creation
            raise SchemaError(f"unknown column type {column.type}")

    def _validate_values(
        self, schema: TableSchema, values: tuple[object, ...]
    ) -> None:
        if len(values) != len(schema.columns):
            raise SchemaError(
                f"table {schema.name} has {len(schema.columns)} columns but "
                f"{len(values)} values were supplied"
            )
        for value, column in zip(values, schema.columns):
            self._validate_value(value, column)

    # -- CatalogPort ------------------------------------------------------

    def get_schema(self, table: str) -> TableSchema:
        self._check_open()
        table = self._check_identifier(table, "table")
        return self._require_table(table)

    def has_index(self, table: str, column: str) -> bool:
        self._check_open()
        table = self._check_identifier(table, "table")
        column = self._check_identifier(column, "column")
        schema = self._require_table(table)
        self._column_index(schema, column)  # validates the column
        return self._catalog.index_on_column(table, column)

    # -- DDL --------------------------------------------------------------

    def create_table(self, schema: TableSchema) -> None:
        self._check_open()
        name = self._check_identifier(schema.name, "table")

        normalized_columns: list[Column] = []
        seen_columns: set[str] = set()
        for column in schema.columns:
            col_name = self._check_identifier(column.name, "column")
            if col_name in seen_columns:
                raise SchemaError(
                    f"duplicate column {col_name} in table {name}"
                )
            seen_columns.add(col_name)
            if column.type not in ("INT", "TEXT"):
                raise SchemaError(
                    f"unsupported column type {column.type!r} for "
                    f"{col_name}"
                )
            normalized_columns.append(Column(col_name, column.type))

        if self._catalog.table_exists(name):
            raise SchemaError(f"table {name} already exists")

        normalized = TableSchema(name, tuple(normalized_columns))
        self._catalog.add_table(normalized)
        self._catalog.save()

    def create_index(self, name: str, table: str, column: str) -> None:
        self._check_open()
        name = self._check_identifier(name, "index")
        table = self._check_identifier(table, "table")
        column = self._check_identifier(column, "column")

        schema = self._require_table(table)
        col_idx = self._column_index(schema, column)

        if self._catalog.index_name_exists(name):
            raise SchemaError(f"index {name} already exists")
        if self._catalog.index_on_column(table, column):
            raise SchemaError(
                f"table {table} already has an index on column {column}"
            )

        hash_index = HashIndex(self._indexes_dir, table, column)
        # Backfill from existing rows.
        for page_no, slot_no, values in self._heap.scan_records(
            table, len(schema.columns)
        ):
            hash_index.add(values[col_idx], page_no, slot_no)
        hash_index.save()

        self._catalog.add_index(name, table, column)
        self._catalog.save()
        self._indexes[name] = hash_index

    # -- DML --------------------------------------------------------------

    def insert(self, table: str, values: tuple[Value, ...]) -> RID:
        self._check_open()
        table = self._check_identifier(table, "table")
        schema = self._require_table(table)
        self._validate_values(schema, values)

        record = page_mod.encode_row(tuple(values), schema.columns)
        page_no, slot_no = self._heap.insert_record(table, record)

        for idx in self._catalog.get_indexes_for_table(table):
            col_idx = self._column_index(schema, idx["column"])
            self._indexes[idx["name"]].add(
                values[col_idx], page_no, slot_no
            )

        return RID(page_no, slot_no)

    def scan(self, table: str) -> Iterator[RowRef]:
        self._check_open()
        table = self._check_identifier(table, "table")
        schema = self._require_table(table)
        return self._scan_iter(table, schema)

    def _scan_iter(
        self, table: str, schema: TableSchema
    ) -> Iterator[RowRef]:
        for page_no, slot_no, values in self._heap.scan_records(
            table, len(schema.columns)
        ):
            yield RowRef(
                RID(page_no, slot_no), tuple(values)  # type: ignore[arg-type]
            )

    def lookup_eq(
        self, table: str, column: str, value: Value
    ) -> Iterator[RowRef]:
        self._check_open()
        table = self._check_identifier(table, "table")
        column = self._check_identifier(column, "column")
        schema = self._require_table(table)
        col_idx = self._column_index(schema, column)

        if not self._catalog.index_on_column(table, column):
            raise SchemaError(
                f"no index on {table}({column}); cannot use index lookup"
            )
        self._validate_value(value, schema.columns[col_idx])

        index_name = self._find_index_name(table, column)
        hash_index = self._indexes[index_name]
        return self._lookup_iter(table, schema, hash_index, value)

    def _lookup_iter(
        self,
        table: str,
        schema: TableSchema,
        hash_index: HashIndex,
        value: Value,
    ) -> Iterator[RowRef]:
        for page_no, slot_no in hash_index.lookup(value):
            frame = self._buffer.fetch_page(table, page_no)
            try:
                if page_mod.is_dead(frame.data, slot_no):
                    continue  # stale index entry, skip it
                record = page_mod.get_record(frame.data, slot_no)
            except page_mod.PageError:
                continue
            values = page_mod.decode_row(record, len(schema.columns))
            yield RowRef(
                RID(page_no, slot_no), tuple(values)  # type: ignore[arg-type]
            )

    def _find_index_name(self, table: str, column: str) -> str:
        for idx in self._catalog.get_indexes_for_table(table):
            if idx["column"] == column:
                return idx["name"]
        raise SchemaError(f"no index on {table}({column})")

    def update(
        self, table: str, rid: RID, values: tuple[Value, ...]
    ) -> None:
        self._check_open()
        table = self._check_identifier(table, "table")
        schema = self._require_table(table)
        self._validate_values(schema, values)

        # Read the old record and validate the RID before any change.
        frame = self._buffer.fetch_page(table, rid.page_no)
        try:
            if page_mod.is_dead(frame.data, rid.slot_no):
                raise StorageError(
                    f"RID (page={rid.page_no}, slot={rid.slot_no}) is deleted"
                )
            old_record = page_mod.get_record(frame.data, rid.slot_no)
            old_length = page_mod.slot_allocated_length(
                frame.data, rid.slot_no
            )
        except page_mod.PageError as exc:
            raise StorageError(
                f"RID (page={rid.page_no}, slot={rid.slot_no}) does not exist"
            ) from exc

        new_record = page_mod.encode_row(tuple(values), schema.columns)
        if len(new_record) > old_length:
            raise StorageError(
                f"updated record is {len(new_record)} bytes but the slot only "
                f"holds {old_length} bytes; RID cannot move"
            )

        old_values = page_mod.decode_row(old_record, len(schema.columns))

        # Remove old index keys first, then add new keys.
        index_infos = self._catalog.get_indexes_for_table(table)
        for idx in index_infos:
            col_idx = self._column_index(schema, idx["column"])
            self._indexes[idx["name"]].remove(
                old_values[col_idx], rid.page_no, rid.slot_no
            )

        self._heap.update_record(
            table, rid.page_no, rid.slot_no, new_record
        )

        for idx in index_infos:
            col_idx = self._column_index(schema, idx["column"])
            self._indexes[idx["name"]].add(
                values[col_idx], rid.page_no, rid.slot_no
            )

    def delete(self, table: str, rid: RID) -> None:
        self._check_open()
        table = self._check_identifier(table, "table")
        schema = self._require_table(table)

        frame = self._buffer.fetch_page(table, rid.page_no)
        try:
            if page_mod.is_dead(frame.data, rid.slot_no):
                raise StorageError(
                    f"RID (page={rid.page_no}, slot={rid.slot_no}) is deleted"
                )
            old_record = page_mod.get_record(frame.data, rid.slot_no)
        except page_mod.PageError as exc:
            raise StorageError(
                f"RID (page={rid.page_no}, slot={rid.slot_no}) does not exist"
            ) from exc

        old_values = page_mod.decode_row(old_record, len(schema.columns))

        for idx in self._catalog.get_indexes_for_table(table):
            col_idx = self._column_index(schema, idx["column"])
            self._indexes[idx["name"]].remove(
                old_values[col_idx], rid.page_no, rid.slot_no
            )

        self._heap.delete_record(table, rid.page_no, rid.slot_no)

    # -- buffer / lifecycle ----------------------------------------------

    def get_buffer_stats(self) -> BufferStats:
        self._check_open()
        hits, misses, evictions, dirty_flushes = self._buffer.stats()
        return BufferStats(hits, misses, evictions, dirty_flushes)

    def flush(self) -> None:
        self._check_open()
        self._buffer.flush_all()
        for hash_index in self._indexes.values():
            hash_index.save()
        self._catalog.save()

    def close(self) -> None:
        if self._closed:
            return
        self.flush()
        self._disk.close()
        self._closed = True
