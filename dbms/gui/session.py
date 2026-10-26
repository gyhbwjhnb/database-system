"""Database operations shared by the desktop UI and its tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Callable

from dbms.contracts import StoragePort
from dbms.executor import execute
from dbms.frontend import parse, plan
from dbms.frontend.cli import split_statements
from dbms.storage import StorageEngine
from dbms.types import DBMSError, Result, SelectPlan, TableSchema


@dataclass(frozen=True)
class ExecutionRecord:
    sql: str
    result: Result | None
    error: str | None
    elapsed_ms: float


class DatabaseSession:
    """Keep one storage engine open while the user works in the GUI."""

    def __init__(
        self,
        db_dir: str | Path,
        buffer_pages: int = 64,
        storage_factory: Callable[..., StoragePort] = StorageEngine,
    ) -> None:
        self.buffer_pages = buffer_pages
        self._storage_factory = storage_factory
        self.db_dir = Path(db_dir).expanduser().resolve()
        self.storage: StoragePort | None = storage_factory(
            str(self.db_dir), buffer_pages=buffer_pages
        )

    def _require_storage(self) -> StoragePort:
        if self.storage is None:
            raise RuntimeError("database session is closed")
        return self.storage

    def execute_text(self, text: str) -> list[ExecutionRecord]:
        """Run each statement, recording expected errors and continuing."""
        storage = self._require_storage()
        records: list[ExecutionRecord] = []
        for sql in split_statements(text):
            start = perf_counter()
            try:
                query_plan = plan(parse(sql), storage)
                result = execute(query_plan, storage)
                if not isinstance(query_plan, SelectPlan):
                    storage.flush()
            except (DBMSError, OSError, UnicodeError) as error:
                records.append(
                    ExecutionRecord(sql, None, str(error), (perf_counter() - start) * 1000)
                )
            else:
                records.append(
                    ExecutionRecord(sql, result, None, (perf_counter() - start) * 1000)
                )
        return records

    def list_tables(self) -> tuple[str, ...]:
        return self._require_storage().list_tables()

    def get_schema(self, table: str) -> TableSchema:
        return self._require_storage().get_schema(table)

    def buffer_stats(self) -> tuple[int, int, int, int]:
        stats = self._require_storage().get_buffer_stats()
        return (stats.hits, stats.misses, stats.evictions, stats.dirty_flushes)

    def switch_database(self, db_dir: str | Path) -> None:
        target = Path(db_dir).expanduser().resolve()
        if target == self.db_dir:
            return
        current = self._require_storage()
        replacement = self._storage_factory(str(target), buffer_pages=self.buffer_pages)
        try:
            current.close()
        except BaseException:
            replacement.close()
            raise
        self.storage = replacement
        self.db_dir = target

    def close(self) -> None:
        storage = self.storage
        if storage is not None:
            storage.close()
            self.storage = None
