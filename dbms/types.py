"""Frozen cross-module data contract (v1).

All public structures crossing storage, frontend, executor and CLI boundaries
live here. Implementations may add private types inside their own packages.
Compatible with Python 3.10+.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias


Value: TypeAlias = int | str
ColumnType: TypeAlias = Literal["INT", "TEXT"]
Operator: TypeAlias = Literal["=", "!=", "<", "<=", ">", ">="]
AccessPath: TypeAlias = Literal["seq", "index_eq"]


class DBMSError(Exception):
    """Base class for expected, user-visible DBMS errors."""


class SQLSyntaxError(DBMSError):
    """SQL text is outside the supported grammar or malformed."""


class SchemaError(DBMSError):
    """A table, column or index is missing, duplicated or otherwise invalid."""


class TypeMismatchError(DBMSError):
    """A value has the wrong type or exceeds the supported value range."""


class StorageError(DBMSError):
    """A storage operation failed, including an unsupported row expansion."""


@dataclass(frozen=True)
class Column:
    name: str
    type: ColumnType


@dataclass(frozen=True)
class TableSchema:
    name: str
    columns: tuple[Column, ...]


@dataclass(frozen=True)
class RID:
    page_no: int
    slot_no: int


@dataclass(frozen=True)
class RowRef:
    rid: RID
    values: tuple[Value, ...]


@dataclass(frozen=True)
class Predicate:
    column: str
    op: Operator
    value: Value


# Parsed SQL. SelectStmt.columns=None means SELECT *; all other column lists
# keep SQL order. Semantic validation belongs to plan(), not parse().
@dataclass(frozen=True)
class CreateTableStmt:
    schema: TableSchema


@dataclass(frozen=True)
class CreateIndexStmt:
    name: str
    table: str
    column: str


@dataclass(frozen=True)
class InsertStmt:
    table: str
    values: tuple[Value, ...]


@dataclass(frozen=True)
class SelectStmt:
    table: str
    columns: tuple[str, ...] | None
    predicate: Predicate | None = None


@dataclass(frozen=True)
class UpdateStmt:
    table: str
    column: str
    value: Value
    predicate: Predicate | None = None


@dataclass(frozen=True)
class DeleteStmt:
    table: str
    predicate: Predicate | None = None


Statement: TypeAlias = (
    CreateTableStmt
    | CreateIndexStmt
    | InsertStmt
    | SelectStmt
    | UpdateStmt
    | DeleteStmt
)


# Validated execution plans. SelectPlan.columns is always expanded: never None.
@dataclass(frozen=True)
class CreateTablePlan:
    schema: TableSchema


@dataclass(frozen=True)
class CreateIndexPlan:
    name: str
    table: str
    column: str


@dataclass(frozen=True)
class InsertPlan:
    table: str
    values: tuple[Value, ...]


@dataclass(frozen=True)
class SelectPlan:
    table: str
    columns: tuple[str, ...]
    predicate: Predicate | None
    access: AccessPath


@dataclass(frozen=True)
class UpdatePlan:
    table: str
    column: str
    value: Value
    predicate: Predicate | None
    access: AccessPath


@dataclass(frozen=True)
class DeletePlan:
    table: str
    predicate: Predicate | None
    access: AccessPath


Plan: TypeAlias = (
    CreateTablePlan
    | CreateIndexPlan
    | InsertPlan
    | SelectPlan
    | UpdatePlan
    | DeletePlan
)


@dataclass
class Result:
    columns: tuple[str, ...] = ()
    rows: list[tuple[Value, ...]] = field(default_factory=list)
    affected_rows: int = 0
    plan_label: str = ""


@dataclass(frozen=True)
class BufferStats:
    hits: int
    misses: int
    evictions: int
    dirty_flushes: int
