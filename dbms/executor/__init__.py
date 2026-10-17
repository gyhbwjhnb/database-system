"""Execute validated plans through the public storage interface.

The frontend owns SQL parsing and semantic validation. This module only
interprets plans, so it can be tested with an in-memory StoragePort as well as
the disk-backed StorageEngine.
"""

from __future__ import annotations

from collections.abc import Iterator

from dbms.contracts import StoragePort
from dbms.types import (
    CreateIndexPlan,
    CreateTablePlan,
    DeletePlan,
    InsertPlan,
    Plan,
    Predicate,
    Result,
    RowRef,
    SelectPlan,
    UpdatePlan,
    Value,
)


def _column_positions(storage: StoragePort, table: str) -> dict[str, int]:
    schema = storage.get_schema(table)
    return {column.name: position for position, column in enumerate(schema.columns)}


def _matches(row: RowRef, predicate: Predicate | None, positions: dict[str, int]) -> bool:
    if predicate is None:
        return True

    actual = row.values[positions[predicate.column]]
    expected = predicate.value
    if predicate.op == "=":
        return actual == expected
    if predicate.op == "!=":
        return actual != expected
    if predicate.op == "<":
        return actual < expected
    if predicate.op == "<=":
        return actual <= expected
    if predicate.op == ">":
        return actual > expected
    if predicate.op == ">=":
        return actual >= expected
    raise ValueError(f"unsupported predicate operator: {predicate.op!r}")


def _candidates(
    storage: StoragePort, table: str, predicate: Predicate | None, access: str
) -> Iterator[RowRef]:
    if access == "seq":
        return storage.scan(table)
    if access == "index_eq":
        if predicate is None or predicate.op != "=":
            raise ValueError("index_eq requires an equality predicate")
        return storage.lookup_eq(table, predicate.column, predicate.value)
    raise ValueError(f"unsupported access path: {access!r}")


def _matching_rows(
    storage: StoragePort,
    table: str,
    predicate: Predicate | None,
    access: str,
    positions: dict[str, int],
) -> Iterator[RowRef]:
    for row in _candidates(storage, table, predicate, access):
        # An index returns candidates; the predicate is always checked against
        # the current row, including when storage returns a stale candidate.
        if _matches(row, predicate, positions):
            yield row


def _scan_label(access: str) -> str:
    return "IndexEqScan" if access == "index_eq" else "SeqScan"


def execute(plan: Plan, storage: StoragePort) -> Result:
    """Run one validated plan and return its rows, count and plan label.

    Expected database errors propagate to the caller. The executor does not
    print, parse SQL, or open files itself.
    """
    if isinstance(plan, CreateTablePlan):
        storage.create_table(plan.schema)
        return Result(plan_label="CreateTable")

    if isinstance(plan, CreateIndexPlan):
        storage.create_index(plan.name, plan.table, plan.column)
        return Result(plan_label="CreateIndex")

    if isinstance(plan, InsertPlan):
        storage.insert(plan.table, plan.values)
        return Result(affected_rows=1, plan_label="Insert")

    if isinstance(plan, SelectPlan):
        positions = _column_positions(storage, plan.table)
        projection = tuple(positions[column] for column in plan.columns)
        rows = [
            tuple(row.values[position] for position in projection)
            for row in _matching_rows(storage, plan.table, plan.predicate, plan.access, positions)
        ]
        return Result(columns=plan.columns, rows=rows, plan_label=_scan_label(plan.access))

    if isinstance(plan, UpdatePlan):
        positions = _column_positions(storage, plan.table)
        target_position = positions[plan.column]
        # Materialize before changing any row or index. In particular, an
        # UPDATE may change the key used by the candidate iterator.
        matches = list(
            _matching_rows(storage, plan.table, plan.predicate, plan.access, positions)
        )
        for row in matches:
            new_values: list[Value] = list(row.values)
            new_values[target_position] = plan.value
            storage.update(plan.table, row.rid, tuple(new_values))
        return Result(
            affected_rows=len(matches), plan_label="Update" + _scan_label(plan.access)
        )

    if isinstance(plan, DeletePlan):
        positions = _column_positions(storage, plan.table)
        matches = list(
            _matching_rows(storage, plan.table, plan.predicate, plan.access, positions)
        )
        for row in matches:
            storage.delete(plan.table, row.rid)
        return Result(
            affected_rows=len(matches), plan_label="Delete" + _scan_label(plan.access)
        )

    raise TypeError(f"unsupported execution plan: {type(plan).__name__}")


__all__ = ["execute"]
