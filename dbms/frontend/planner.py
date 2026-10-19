"""Semantic validation and access-path selection using only CatalogPort."""

from __future__ import annotations

import re

from dbms.contracts import CatalogPort
from dbms.types import (
    AccessPath,
    Column,
    CreateIndexPlan,
    CreateIndexStmt,
    CreateTablePlan,
    CreateTableStmt,
    DeletePlan,
    DeleteStmt,
    InsertPlan,
    InsertStmt,
    Plan,
    Predicate,
    SchemaError,
    SelectPlan,
    SelectStmt,
    SQLSyntaxError,
    Statement,
    TableSchema,
    TypeMismatchError,
    UpdatePlan,
    UpdateStmt,
    Value,
)


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*", re.ASCII)
_OPERATORS = ("=", "!=", "<", "<=", ">", ">=")
_INT_MIN = -(1 << 63)
_INT_MAX = (1 << 63) - 1


def _name(value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise SchemaError(f"Invalid identifier: {value!r}")
    return value.lower()


def _column(schema: TableSchema, name: str) -> Column:
    for column in schema.columns:
        if column.name == name:
            return column
    raise SchemaError(f"Unknown column {name!r} in table {schema.name!r}")


def _value(value: Value, column: Column) -> None:
    """Validate literal bounds here, before any executor or storage writes."""
    if column.type == "INT":
        if type(value) is not int:
            raise TypeMismatchError(f"Column {column.name!r} requires INT")
        if not _INT_MIN <= value <= _INT_MAX:
            raise TypeMismatchError(
                f"Column {column.name!r}: INT must be in [{_INT_MIN}, {_INT_MAX}]"
            )
    elif column.type == "TEXT":
        if not isinstance(value, str):
            raise TypeMismatchError(f"Column {column.name!r} requires TEXT")
        try:
            size = len(value.encode("utf-8"))
        except UnicodeEncodeError as error:
            raise TypeMismatchError(
                f"Column {column.name!r}: TEXT must be valid UTF-8"
            ) from error
        if size > 255:
            raise TypeMismatchError(
                f"Column {column.name!r}: TEXT is {size} UTF-8 bytes (maximum 255)"
            )
    else:
        raise SchemaError(f"Unsupported column type: {column.type!r}")


def _predicate(predicate: Predicate | None, schema: TableSchema) -> Predicate | None:
    if predicate is None:
        return None
    column = _name(predicate.column)
    if predicate.op not in _OPERATORS:
        raise SQLSyntaxError(f"Unsupported comparison operator: {predicate.op!r}")
    _value(predicate.value, _column(schema, column))
    return Predicate(column, predicate.op, predicate.value)


def _access(predicate: Predicate | None, table: str, catalog: CatalogPort) -> AccessPath:
    if predicate is not None and predicate.op == "=":
        if catalog.has_index(table, predicate.column):
            return "index_eq"
    return "seq"


def plan(statement: Statement, catalog: CatalogPort) -> Plan:
    """Return a validated, handle-free plan; never read or modify table rows.

    Duplicate table/index names and repeated indexes on a column are ultimately
    checked by StorageEngine, as the frozen CatalogPort has no name-list API.
    """
    if isinstance(statement, CreateTableStmt):
        name = _name(statement.schema.name)
        if not statement.schema.columns:
            raise SchemaError("A table must have at least one column")
        columns = []
        seen = set()
        for column in statement.schema.columns:
            column_name = _name(column.name)
            if column_name in seen:
                raise SchemaError(f"Duplicate column: {column_name!r}")
            if column.type not in ("INT", "TEXT"):
                raise SchemaError(f"Unsupported column type: {column.type!r}")
            seen.add(column_name)
            columns.append(Column(column_name, column.type))
        return CreateTablePlan(TableSchema(name, tuple(columns)))

    if not isinstance(
        statement, (CreateIndexStmt, InsertStmt, SelectStmt, UpdateStmt, DeleteStmt)
    ):
        raise SQLSyntaxError(f"Unsupported statement type: {type(statement).__name__}")

    table = _name(statement.table)
    schema = catalog.get_schema(table)

    if isinstance(statement, CreateIndexStmt):
        name = _name(statement.name)
        column = _name(statement.column)
        _column(schema, column)
        return CreateIndexPlan(name, table, column)

    if isinstance(statement, InsertStmt):
        if len(statement.values) != len(schema.columns):
            raise SchemaError(
                f"Table {table!r} expects {len(schema.columns)} values; "
                f"received {len(statement.values)}"
            )
        for value, column in zip(statement.values, schema.columns):
            _value(value, column)
        return InsertPlan(table, tuple(statement.values))

    predicate = _predicate(statement.predicate, schema)

    if isinstance(statement, SelectStmt):
        if statement.columns is None:
            columns = tuple(column.name for column in schema.columns)
        else:
            if not statement.columns:
                raise SchemaError("SELECT requires at least one column")
            columns = tuple(_name(column) for column in statement.columns)
            for column in columns:
                _column(schema, column)
        return SelectPlan(table, columns, predicate, _access(predicate, table, catalog))

    if isinstance(statement, UpdateStmt):
        column = _name(statement.column)
        _value(statement.value, _column(schema, column))
        return UpdatePlan(
            table, column, statement.value, predicate, _access(predicate, table, catalog)
        )

    return DeletePlan(table, predicate, _access(predicate, table, catalog))
