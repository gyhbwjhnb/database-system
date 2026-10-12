"""Structural interfaces to implement or mock in separate modules.

These Protocols are type contracts, not implementations. The concrete
StorageEngine is owned by member A; parse/plan by B; execute by C.
"""

from __future__ import annotations

from typing import Callable, Iterator, Protocol, TypeAlias

from .types import BufferStats, Plan, Result, RID, RowRef, Statement, TableSchema, Value


class CatalogPort(Protocol):
    def get_schema(self, table: str) -> TableSchema: ...

    def has_index(self, table: str, column: str) -> bool: ...


class StoragePort(CatalogPort, Protocol):
    def create_table(self, schema: TableSchema) -> None: ...

    def create_index(self, name: str, table: str, column: str) -> None: ...

    def insert(self, table: str, values: tuple[Value, ...]) -> RID: ...

    def scan(self, table: str) -> Iterator[RowRef]: ...

    def lookup_eq(self, table: str, column: str, value: Value) -> Iterator[RowRef]: ...

    def update(self, table: str, rid: RID, values: tuple[Value, ...]) -> None: ...

    def delete(self, table: str, rid: RID) -> None: ...

    def get_buffer_stats(self) -> BufferStats: ...

    def flush(self) -> None: ...

    def close(self) -> None: ...


ParseFn: TypeAlias = Callable[[str], Statement]
PlanFn: TypeAlias = Callable[[Statement, CatalogPort], Plan]
ExecuteFn: TypeAlias = Callable[[Plan, StoragePort], Result]
