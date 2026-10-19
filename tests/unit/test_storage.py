"""Unit tests for the storage module owned by member A.

Covers catalog metadata (A1), pages and row encoding (A2), the LRU buffer
pool (A3), table APIs (A4), persistent equality indexes (A5) and restart
durability.  Run with::

    python -m unittest tests.unit.test_storage -v
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from dbms.storage import StorageEngine
from dbms.types import (
    Column,
    RID,
    SchemaError,
    StorageError,
    TableSchema,
    TypeMismatchError,
)

INT_MIN = -(2**63)
INT_MAX = 2**63 - 1


def schema(name: str, *columns: tuple[str, str]) -> TableSchema:
    return TableSchema(
        name, tuple(Column(col_name, col_type) for col_name, col_type in columns)
    )


class StorageTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.db_dir = tempfile.mkdtemp(prefix="dbms_test_")

    def tearDown(self) -> None:
        # Best-effort close any engine the test created.
        engine = getattr(self, "engine", None)
        if engine is not None:
            try:
                engine.close()
            except Exception:
                pass
        shutil.rmtree(self.db_dir, ignore_errors=True)

    def make_engine(self, buffer_pages: int = 64) -> StorageEngine:
        self.engine = StorageEngine(self.db_dir, buffer_pages=buffer_pages)
        return self.engine


class TestBasicCrud(StorageTestBase):
    def test_create_insert_scan(self) -> None:
        engine = self.make_engine()
        engine.create_table(schema("students", ("id", "INT"), ("name", "TEXT")))
        engine.insert("students", (1, "Alice"))
        engine.insert("students", (2, "Bob"))

        rows = [ref.values for ref in engine.scan("students")]
        self.assertEqual(set(rows), {(1, "Alice"), (2, "Bob")})

    def test_identifiers_are_lowercased_values_keep_case(self) -> None:
        engine = self.make_engine()
        engine.create_table(schema("Students", ("ID", "INT"), ("Name", "TEXT")))
        engine.insert("STUDENTS", (1, "Alice"))

        fetched = engine.get_schema("STUDENTS")
        self.assertEqual(fetched.name, "students")
        self.assertEqual([c.name for c in fetched.columns], ["id", "name"])

        rows = [ref.values for ref in engine.scan("Students")]
        self.assertEqual(rows, [(1, "Alice")])  # text case preserved

    def test_empty_table_scan(self) -> None:
        engine = self.make_engine()
        engine.create_table(schema("t", ("a", "INT")))
        self.assertEqual(list(engine.scan("t")), [])

    def test_duplicate_table(self) -> None:
        engine = self.make_engine()
        engine.create_table(schema("t", ("a", "INT")))
        with self.assertRaises(SchemaError):
            engine.create_table(schema("T", ("a", "INT")))

    def test_unknown_table_and_column(self) -> None:
        engine = self.make_engine()
        with self.assertRaises(SchemaError):
            engine.get_schema("nope")
        with self.assertRaises(SchemaError):
            list(engine.scan("nope"))
        engine.create_table(schema("t", ("a", "INT")))
        with self.assertRaises(SchemaError):
            engine.has_index("t", "missing")
        with self.assertRaises(SchemaError):
            engine.has_index("nope", "a")

    def test_invalid_identifier(self) -> None:
        engine = self.make_engine()
        with self.assertRaises(SchemaError):
            engine.create_table(schema("1bad", ("a", "INT")))
        with self.assertRaises(SchemaError):
            engine.create_table(schema("bad-name", ("a", "INT")))
        with self.assertRaises(SchemaError):
            engine.create_table(
                schema("t", ("a", "INT"), ("a", "INT"))  # duplicate column
            )

    def test_column_count_mismatch(self) -> None:
        engine = self.make_engine()
        engine.create_table(schema("t", ("a", "INT"), ("b", "INT")))
        with self.assertRaises(SchemaError):
            engine.insert("t", (1,))
        with self.assertRaises(SchemaError):
            engine.insert("t", (1, 2, 3))

    def test_type_mismatch(self) -> None:
        engine = self.make_engine()
        engine.create_table(schema("t", ("a", "INT"), ("b", "TEXT")))
        with self.assertRaises(TypeMismatchError):
            engine.insert("t", ("x", "y"))
        with self.assertRaises(TypeMismatchError):
            engine.insert("t", (1, 2))
        # bool is not a valid INT
        with self.assertRaises(TypeMismatchError):
            engine.insert("t", (True, "y"))

    def test_int_range_and_text_limit(self) -> None:
        engine = self.make_engine()
        engine.create_table(schema("t", ("a", "INT"), ("b", "TEXT")))
        engine.insert("t", (INT_MAX, "ok"))
        engine.insert("t", (INT_MIN, "ok"))
        with self.assertRaises(TypeMismatchError):
            engine.insert("t", (INT_MAX + 1, "ok"))
        with self.assertRaises(TypeMismatchError):
            engine.insert("t", (INT_MIN - 1, "ok"))
        with self.assertRaises(TypeMismatchError):
            engine.insert("t", (1, "x" * 256))  # 256 ASCII bytes
        # 255 bytes is allowed.
        engine.insert("t", (3, "x" * 255))

    def test_text_multibyte_counts_as_bytes(self) -> None:
        engine = self.make_engine()
        engine.create_table(schema("t", ("b", "TEXT")))
        # Each Chinese character is 3 UTF-8 bytes. 85 chars = 255 bytes.
        engine.insert("t", ("中" * 85,))
        with self.assertRaises(TypeMismatchError):
            engine.insert("t", ("中" * 86,))  # 258 bytes


class TestCrossPage(StorageTestBase):
    def test_rows_span_multiple_pages(self) -> None:
        engine = self.make_engine()
        # One ~200-byte text field -> ~19 rows/page.
        engine.create_table(schema("big", ("payload", "TEXT")))
        n = 40
        for i in range(n):
            engine.insert("big", (f"{i:03d}" + "x" * 197,))

        rows = list(engine.scan("big"))
        self.assertEqual(len(rows), n)
        pages = {ref.rid.page_no for ref in rows}
        self.assertGreaterEqual(len(pages), 3)
        # Slot numbers restart on each page and stay within range.
        for ref in rows:
            self.assertGreaterEqual(ref.rid.slot_no, 0)


class TestUpdateDelete(StorageTestBase):
    def _setup(self) -> StorageEngine:
        engine = self.make_engine()
        engine.create_table(
            schema("students", ("id", "INT"), ("name", "TEXT"), ("score", "INT"))
        )
        return engine

    def test_delete_hides_row_and_blocks_repeat(self) -> None:
        engine = self._setup()
        rid = engine.insert("students", (1, "Alice", 90))
        engine.delete("students", rid)
        self.assertEqual(list(engine.scan("students")), [])
        with self.assertRaises(StorageError):
            engine.delete("students", rid)

    def test_delete_unknown_rid(self) -> None:
        engine = self._setup()
        with self.assertRaises(StorageError):
            engine.delete("students", RID(0, 0))
        with self.assertRaises(StorageError):
            engine.delete("students", RID(99, 99))

    def test_update_keeps_rid_and_can_shrink(self) -> None:
        engine = self._setup()
        rid = engine.insert("students", (1, "Alice", 90))
        # Shorter text and lower score fit in the allocated slot.
        engine.update("students", rid, (1, "Al", 80))
        refs = list(engine.scan("students"))
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].rid, rid)
        self.assertEqual(refs[0].values, (1, "Al", 80))

    def test_update_too_long_raises(self) -> None:
        engine = self._setup()
        rid = engine.insert("students", (1, "Alice", 90))
        # Growing the text beyond the original slot must fail.
        with self.assertRaises(StorageError):
            engine.update("students", rid, (1, "A" * 255, 90))
        # Row must be unchanged after the failed update.
        refs = list(engine.scan("students"))
        self.assertEqual(refs[0].values, (1, "Alice", 90))

    def test_update_unknown_rid(self) -> None:
        engine = self._setup()
        with self.assertRaises(StorageError):
            engine.update("students", RID(0, 0), (1, "x", 1))


class TestIndex(StorageTestBase):
    def _setup(self, indexed: bool = False) -> StorageEngine:
        engine = self.make_engine()
        engine.create_table(
            schema("students", ("id", "INT"), ("name", "TEXT"), ("score", "INT"))
        )
        engine.insert("students", (1, "Alice", 90))
        engine.insert("students", (2, "Bob", 80))
        engine.insert("students", (3, "Alice", 70))
        if indexed:
            engine.create_index("idx_students_id", "students", "id")
        return engine

    def test_create_index_backfills_and_duplicate_keys(self) -> None:
        engine = self.make_engine()
        engine.create_table(schema("t", ("id", "INT"), ("v", "TEXT")))
        engine.insert("t", (5, "a"))
        engine.insert("t", (5, "b"))
        engine.insert("t", (6, "c"))
        engine.create_index("idx_t_id", "t", "id")

        rows = [ref.values for ref in engine.lookup_eq("t", "id", 5)]
        self.assertEqual(set(rows), {(5, "a"), (5, "b")})
        self.assertTrue(engine.has_index("t", "id"))
        self.assertFalse(engine.has_index("t", "v"))

    def test_lookup_without_index_raises(self) -> None:
        engine = self._setup(indexed=False)
        with self.assertRaises(SchemaError):
            list(engine.lookup_eq("students", "id", 1))

    def test_index_on_empty_table(self) -> None:
        engine = self.make_engine()
        engine.create_table(schema("t", ("id", "INT")))
        engine.create_index("idx_t_id", "t", "id")
        self.assertEqual(list(engine.lookup_eq("t", "id", 1)), [])

    def test_update_indexed_column_moves_key(self) -> None:
        engine = self._setup(indexed=True)
        rid = next(
            ref.rid
            for ref in engine.lookup_eq("students", "id", 1)
        )
        # id is the indexed column; change 1 -> 10.
        engine.update("students", rid, (10, "Alice", 90))
        self.assertEqual(list(engine.lookup_eq("students", "id", 1)), [])
        rows = [ref.values for ref in engine.lookup_eq("students", "id", 10)]
        self.assertEqual(rows, [(10, "Alice", 90)])

    def test_update_non_indexed_column_keeps_index(self) -> None:
        engine = self._setup(indexed=True)
        rid = next(iter(engine.lookup_eq("students", "id", 2))).rid
        # Change only the non-indexed INT score (same encoded length); the
        # name stays "Bob" so the record fits in its slot.
        engine.update("students", rid, (2, "Bob", 100))
        rows = [ref.values for ref in engine.lookup_eq("students", "id", 2)]
        self.assertEqual(rows, [(2, "Bob", 100)])

    def test_delete_removes_index_entry(self) -> None:
        engine = self._setup(indexed=True)
        rid = next(iter(engine.lookup_eq("students", "id", 3))).rid
        engine.delete("students", rid)
        self.assertEqual(list(engine.lookup_eq("students", "id", 3)), [])

    def test_duplicate_index_name_and_column(self) -> None:
        engine = self._setup(indexed=True)
        with self.assertRaises(SchemaError):
            engine.create_index("idx_students_id", "students", "score")
        with self.assertRaises(SchemaError):
            engine.create_index("other_name", "students", "id")
        # Index name is globally unique even across tables.
        engine.create_table(schema("other", ("id", "INT")))
        with self.assertRaises(SchemaError):
            engine.create_index("idx_students_id", "other", "id")

    def test_lookup_type_mismatch(self) -> None:
        engine = self._setup(indexed=True)
        with self.assertRaises(TypeMismatchError):
            list(engine.lookup_eq("students", "id", "1"))


class TestDurability(StorageTestBase):
    def test_restart_preserves_rows_and_index(self) -> None:
        engine = StorageEngine(self.db_dir, buffer_pages=64)
        engine.create_table(
            schema("students", ("id", "INT"), ("name", "TEXT"), ("score", "INT"))
        )
        engine.create_index("idx_students_id", "students", "id")
        engine.insert("students", (1, "Alice", 90))
        engine.insert("students", (2, "Alice", 85))
        engine.insert("students", (3, "Bob", 70))
        engine.close()

        reopened = StorageEngine(self.db_dir, buffer_pages=64)
        self.addCleanup(reopened.close)

        rows = {ref.values for ref in reopened.scan("students")}
        self.assertEqual(
            rows, {(1, "Alice", 90), (2, "Alice", 85), (3, "Bob", 70)}
        )
        dup = {ref.values for ref in reopened.lookup_eq("students", "id", 1)}
        self.assertEqual(dup, {(1, "Alice", 90)})
        # Duplicate-name checks still work after restart.
        with self.assertRaises(SchemaError):
            reopened.create_table(
                schema("students", ("id", "INT"), ("name", "TEXT"))
            )

    def test_writes_after_reopen_are_recovered(self) -> None:
        engine = StorageEngine(self.db_dir)
        engine.create_table(schema("t", ("id", "INT")))
        engine.insert("t", (1,))
        engine.close()

        reopened = StorageEngine(self.db_dir)
        reopened.insert("t", (2,))
        reopened.create_index("idx_t_id", "t", "id")
        reopened.close()

        again = StorageEngine(self.db_dir)
        self.addCleanup(again.close)
        self.assertEqual(
            {ref.values for ref in again.scan("t")}, {(1,), (2,)}
        )


class TestBufferPool(StorageTestBase):
    def test_hits_on_repeated_access(self) -> None:
        engine = self.make_engine(buffer_pages=4)
        engine.create_table(schema("t", ("id", "INT")))
        engine.insert("t", (1,))
        engine.flush()
        for _ in range(3):
            list(engine.scan("t"))
        stats = engine.get_buffer_stats()
        self.assertGreaterEqual(stats.hits, 2)

    def test_lru_eviction_and_dirty_flush(self) -> None:
        # 2-page buffer, rows span >= 3 pages.
        engine = self.make_engine(buffer_pages=2)
        engine.create_table(schema("big", ("payload", "TEXT")))
        for i in range(40):
            engine.insert("big", (f"{i:03d}" + "x" * 197,))

        stats = engine.get_buffer_stats()
        self.assertGreaterEqual(stats.evictions, 1)
        self.assertGreaterEqual(stats.dirty_flushes, 1)

        # A sequential scan with the tiny buffer also evicts pages.
        before = engine.get_buffer_stats().evictions
        list(engine.scan("big"))
        self.assertGreater(engine.get_buffer_stats().evictions, before)

    def test_dirty_data_survives_eviction_and_restart(self) -> None:
        engine = StorageEngine(self.db_dir, buffer_pages=2)
        engine.create_table(schema("big", ("payload", "TEXT")))
        for i in range(40):
            engine.insert("big", (f"{i:03d}" + "x" * 197,))
        engine.close()  # flush + close

        reopened = StorageEngine(self.db_dir, buffer_pages=2)
        self.addCleanup(reopened.close)
        self.assertEqual(len(list(reopened.scan("big"))), 40)


class TestLifecycle(StorageTestBase):
    def test_close_is_idempotent_and_reuses(self) -> None:
        engine = self.make_engine()
        engine.create_table(schema("t", ("id", "INT")))
        engine.close()
        engine.close()  # must not raise
        with self.assertRaises(StorageError):
            engine.insert("t", (1,))
        with self.assertRaises(StorageError):
            engine.get_buffer_stats()

    def test_flush_then_reopen(self) -> None:
        engine = self.make_engine()
        engine.create_table(schema("t", ("id", "INT")))
        engine.insert("t", (42,))
        engine.flush()
        engine.flush()  # idempotent, no dirty pages
        engine.close()

        reopened = StorageEngine(self.db_dir)
        self.addCleanup(reopened.close)
        self.assertEqual([ref.values for ref in reopened.scan("t")], [(42,)])


if __name__ == "__main__":
    unittest.main()
