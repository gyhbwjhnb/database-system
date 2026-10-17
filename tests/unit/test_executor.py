"""Executor behavior at the public StoragePort boundary."""

from __future__ import annotations

import unittest

from dbms.executor import execute
from dbms.types import (
    BufferStats,
    Column,
    CreateIndexPlan,
    CreateTablePlan,
    DeletePlan,
    InsertPlan,
    Predicate,
    RID,
    RowRef,
    SelectPlan,
    TableSchema,
    UpdatePlan,
    Value,
)


SCHEMA = TableSchema(
    "students", (Column("id", "INT"), Column("name", "TEXT"), Column("score", "INT"))
)


class FakeStorage:
    """Minimal in-memory port; scan and index iterators are live."""

    def __init__(self) -> None:
        self.schemas: dict[str, TableSchema] = {}
        self.rows: dict[RID, tuple[Value, ...]] = {}
        self.indexes: dict[tuple[str, str], dict[Value, list[RID]]] = {}
        self.next_slot = 0
        self.scan_calls = 0
        self.lookup_calls = 0
        self.extra_candidates: list[RowRef] = []

    def get_schema(self, table: str) -> TableSchema:
        return self.schemas[table]

    def has_index(self, table: str, column: str) -> bool:
        return (table, column) in self.indexes

    def create_table(self, schema: TableSchema) -> None:
        self.schemas[schema.name] = schema

    def create_index(self, name: str, table: str, column: str) -> None:
        position = self._position(table, column)
        mapping: dict[Value, list[RID]] = {}
        for rid, values in self.rows.items():
            mapping.setdefault(values[position], []).append(rid)
        self.indexes[(table, column)] = mapping

    def insert(self, table: str, values: tuple[Value, ...]) -> RID:
        rid = RID(0, self.next_slot)
        self.next_slot += 1
        self.rows[rid] = values
        self._add_indexes(table, rid, values)
        return rid

    def scan(self, table: str):
        self.scan_calls += 1
        for rid, values in self.rows.items():
            yield RowRef(rid, values)

    def lookup_eq(self, table: str, column: str, value: Value):
        self.lookup_calls += 1
        yield from self.extra_candidates
        # Keep this iterator live: changing an index while consuming it may
        # skip candidates unless the executor first materializes all matches.
        for rid in self.indexes[(table, column)].get(value, []):
            if rid in self.rows:
                yield RowRef(rid, self.rows[rid])

    def update(self, table: str, rid: RID, values: tuple[Value, ...]) -> None:
        old = self.rows[rid]
        self._remove_indexes(table, rid, old)
        self.rows[rid] = values
        self._add_indexes(table, rid, values)

    def delete(self, table: str, rid: RID) -> None:
        old = self.rows.pop(rid)
        self._remove_indexes(table, rid, old)

    def get_buffer_stats(self) -> BufferStats:
        return BufferStats(0, 0, 0, 0)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass

    def _position(self, table: str, column: str) -> int:
        return next(
            i for i, item in enumerate(self.schemas[table].columns) if item.name == column
        )

    def _add_indexes(self, table: str, rid: RID, values: tuple[Value, ...]) -> None:
        for (owner, column), mapping in self.indexes.items():
            if owner == table:
                mapping.setdefault(values[self._position(table, column)], []).append(rid)

    def _remove_indexes(self, table: str, rid: RID, values: tuple[Value, ...]) -> None:
        for (owner, column), mapping in self.indexes.items():
            if owner == table:
                mapping[values[self._position(table, column)]].remove(rid)


class ExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.storage = FakeStorage()
        execute(CreateTablePlan(SCHEMA), self.storage)
        for values in ((1, "Alice", 90), (2, "Bob", 60), (3, "Cara", 90)):
            execute(InsertPlan("students", values), self.storage)

    def test_select_projection_and_all_comparison_operators(self) -> None:
        cases = {
            "=": {1},
            "!=": {2, 3},
            "<": set(),
            "<=": {1},
            ">": {2, 3},
            ">=": {1, 2, 3},
        }
        for operator, expected in cases.items():
            with self.subTest(operator=operator):
                result = execute(
                    SelectPlan(
                        "students", ("id",), Predicate("id", operator, 1), "seq"
                    ),
                    self.storage,
                )
                self.assertEqual(result.columns, ("id",))
                self.assertEqual({row[0] for row in result.rows}, expected)
                self.assertEqual(result.affected_rows, 0)
                self.assertEqual(result.plan_label, "SeqScan")

        all_columns = execute(
            SelectPlan("students", ("id", "name", "score"), None, "seq"), self.storage
        )
        self.assertEqual(len(all_columns.rows), 3)
        self.assertIn((1, "Alice", 90), all_columns.rows)

    def test_text_comparison_uses_unicode_order_and_projection_order(self) -> None:
        result = execute(
            SelectPlan(
                "students", ("score", "name"), Predicate("name", ">", "Bob"), "seq"
            ),
            self.storage,
        )
        self.assertEqual(result.rows, [(90, "Cara")])

    def test_index_candidates_are_rechecked(self) -> None:
        execute(CreateIndexPlan("idx_score", "students", "score"), self.storage)
        self.storage.extra_candidates.append(RowRef(RID(4, 4), (99, "Stale", 10)))
        result = execute(
            SelectPlan(
                "students", ("id",), Predicate("score", "=", 90), "index_eq"
            ),
            self.storage,
        )
        self.assertEqual({row[0] for row in result.rows}, {1, 3})
        self.assertEqual(result.plan_label, "IndexEqScan")
        self.assertEqual(self.storage.lookup_calls, 1)
        self.assertEqual(self.storage.scan_calls, 0)

    def test_update_indexed_column_materializes_candidates(self) -> None:
        execute(CreateIndexPlan("idx_score", "students", "score"), self.storage)
        result = execute(
            UpdatePlan(
                "students", "score", 80, Predicate("score", "=", 90), "index_eq"
            ),
            self.storage,
        )
        self.assertEqual(result.affected_rows, 2)
        self.assertEqual(result.plan_label, "UpdateIndexEqScan")
        self.assertEqual(self.storage.indexes[("students", "score")].get(90, []), [])
        self.assertEqual(len(self.storage.indexes[("students", "score")][80]), 2)

    def test_unconditional_update_and_delete_materialize_scan(self) -> None:
        updated = execute(UpdatePlan("students", "score", 70, None, "seq"), self.storage)
        self.assertEqual(updated.affected_rows, 3)
        self.assertEqual(updated.plan_label, "UpdateSeqScan")
        self.assertEqual({row[2] for row in self.storage.rows.values()}, {70})

        deleted = execute(DeletePlan("students", None, "seq"), self.storage)
        self.assertEqual(deleted.affected_rows, 3)
        self.assertEqual(deleted.plan_label, "DeleteSeqScan")
        self.assertEqual(self.storage.rows, {})

    def test_index_delete_and_write_result_shapes(self) -> None:
        created = execute(CreateIndexPlan("idx_score", "students", "score"), self.storage)
        self.assertEqual((created.columns, created.rows, created.affected_rows), ((), [], 0))
        deleted = execute(
            DeletePlan("students", Predicate("score", "=", 90), "index_eq"),
            self.storage,
        )
        self.assertEqual(deleted.affected_rows, 2)
        self.assertEqual(deleted.plan_label, "DeleteIndexEqScan")
        self.assertEqual(list(self.storage.rows.values()), [(2, "Bob", 60)])

    def test_storage_exception_is_not_swallowed(self) -> None:
        class FailingStorage(FakeStorage):
            def insert(self, table, values):
                raise RuntimeError("disk failed")

        with self.assertRaisesRegex(RuntimeError, "disk failed"):
            execute(InsertPlan("students", (4, "Dan", 75)), FailingStorage())


if __name__ == "__main__":
    unittest.main()
