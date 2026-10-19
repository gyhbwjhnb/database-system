"""Semantic and access-path contract tests using only CatalogPort metadata."""

import unittest

from dbms.frontend import parse, plan
from dbms.types import (
    Column,
    CreateIndexPlan,
    CreateIndexStmt,
    CreateTablePlan,
    CreateTableStmt,
    DeletePlan,
    DeleteStmt,
    InsertPlan,
    InsertStmt,
    Predicate,
    SchemaError,
    SelectPlan,
    SelectStmt,
    SQLSyntaxError,
    TableSchema,
    TypeMismatchError,
    UpdatePlan,
    UpdateStmt,
)


STUDENTS = TableSchema("students", (Column("id", "INT"), Column("name", "TEXT"), Column("score", "INT")))


class FakeCatalog:
    """A deliberately minimal catalog with no row access or storage methods."""

    def __init__(self, schemas=(STUDENTS,), indexes=()):
        self.schemas = {schema.name: schema for schema in schemas}
        self.indexes = set(indexes)
        self.calls = []

    def get_schema(self, table):
        self.calls.append(("get_schema", table))
        try:
            return self.schemas[table]
        except KeyError:
            raise SchemaError(f"Unknown table: {table}") from None

    def has_index(self, table, column):
        self.calls.append(("has_index", table, column))
        schema = self.schemas.get(table)
        if schema is None or column not in {item.name for item in schema.columns}:
            raise SchemaError(f"Unknown table/column: {table}.{column}")
        return (table, column) in self.indexes


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.catalog = FakeCatalog()

    def planned(self, sql, catalog=None):
        return plan(parse(sql), self.catalog if catalog is None else catalog)

    def test_all_plan_families_have_exact_fields(self):
        examples = (
            ("CREATE TABLE other (id INT, name TEXT)", CreateTablePlan(TableSchema("other", (Column("id", "INT"), Column("name", "TEXT"))))),
            ("CREATE INDEX idx ON students (id)", CreateIndexPlan("idx", "students", "id")),
            ("INSERT INTO students VALUES (1, 'Alice', 90)", InsertPlan("students", (1, "Alice", 90))),
            ("SELECT name, id FROM students WHERE score >= 60", SelectPlan("students", ("name", "id"), Predicate("score", ">=", 60), "seq")),
            ("UPDATE students SET score = 95 WHERE name != 'Bob'", UpdatePlan("students", "score", 95, Predicate("name", "!=", "Bob"), "seq")),
            ("DELETE FROM students WHERE id < 0", DeletePlan("students", Predicate("id", "<", 0), "seq")),
        )
        for sql, expected in examples:
            with self.subTest(sql=sql):
                self.assertEqual(self.planned(sql), expected)

    def test_wildcard_expands_in_schema_order(self):
        self.assertEqual(self.planned("SELECT * FROM students"), SelectPlan("students", ("id", "name", "score"), None, "seq"))

    def test_projection_order_and_duplicates_survive_planning(self):
        self.assertEqual(self.planned("SELECT name, id, name FROM students"), SelectPlan("students", ("name", "id", "name"), None, "seq"))

    def test_access_selection_for_every_read_or_modify_family(self):
        for indexed in (False, True):
            catalog = FakeCatalog(indexes=(("students", "id"),) if indexed else ())
            for operator in ("=", "!=", "<", "<=", ">", ">="):
                predicate = Predicate("id", operator, 7)
                access = "index_eq" if indexed and operator == "=" else "seq"
                cases = (
                    (SelectStmt("students", None, predicate), SelectPlan("students", ("id", "name", "score"), predicate, access)),
                    (UpdateStmt("students", "score", 95, predicate), UpdatePlan("students", "score", 95, predicate, access)),
                    (DeleteStmt("students", predicate), DeletePlan("students", predicate, access)),
                )
                for statement, expected in cases:
                    with self.subTest(indexed=indexed, operator=operator, family=type(statement).__name__):
                        self.assertEqual(plan(statement, catalog), expected)

    def test_no_predicate_always_uses_sequential_scan(self):
        catalog = FakeCatalog(indexes=(("students", "id"), ("students", "name"), ("students", "score")))
        for statement, expected in (
            (SelectStmt("students", None), SelectPlan("students", ("id", "name", "score"), None, "seq")),
            (UpdateStmt("students", "score", 1), UpdatePlan("students", "score", 1, None, "seq")),
            (DeleteStmt("students"), DeletePlan("students", None, "seq")),
        ):
            with self.subTest(family=type(statement).__name__):
                self.assertEqual(plan(statement, catalog), expected)

    def test_index_on_another_column_does_not_change_access(self):
        catalog = FakeCatalog(indexes=(("students", "name"),))
        self.assertEqual(self.planned("SELECT * FROM students WHERE id = 1", catalog).access, "seq")

    def test_text_equality_can_use_an_index(self):
        catalog = FakeCatalog(indexes=(("students", "name"),))
        self.assertEqual(self.planned("SELECT name FROM students WHERE name = 'Alice'", catalog), SelectPlan("students", ("name",), Predicate("name", "=", "Alice"), "index_eq"))

    def test_all_comparisons_accept_matching_int_and_text_literals(self):
        for column, literal in (("id", "-8"), ("name", "'中文'")):
            for operator in ("=", "!=", "<", "<=", ">", ">="):
                with self.subTest(column=column, operator=operator):
                    self.planned(f"SELECT * FROM students WHERE {column} {operator} {literal}")

    def test_unknown_tables_are_schema_errors(self):
        for sql in ("CREATE INDEX idx ON missing (id)", "INSERT INTO missing VALUES (1)", "SELECT * FROM missing", "UPDATE missing SET id = 1", "DELETE FROM missing"):
            with self.subTest(sql=sql):
                with self.assertRaises(SchemaError):
                    self.planned(sql)

    def test_unknown_columns_are_schema_errors(self):
        for sql in ("CREATE INDEX idx ON students (missing)", "SELECT missing FROM students", "SELECT * FROM students WHERE missing = 1", "UPDATE students SET missing = 1", "UPDATE students SET id = 1 WHERE missing = 1", "DELETE FROM students WHERE missing = 1"):
            with self.subTest(sql=sql):
                with self.assertRaises(SchemaError):
                    self.planned(sql)

    def test_insert_requires_all_values_in_schema_order(self):
        for sql in ("INSERT INTO students VALUES (1)", "INSERT INTO students VALUES (1, 'A')", "INSERT INTO students VALUES (1, 'A', 2, 3)"):
            with self.subTest(sql=sql):
                with self.assertRaises(SchemaError):
                    self.planned(sql)

    def test_wrong_insert_types_are_rejected(self):
        for values in (("1", "Alice", 2), (1, 2, 3), (1, "Alice", "3")):
            with self.subTest(values=values):
                with self.assertRaises(TypeMismatchError):
                    plan(InsertStmt("students", values), self.catalog)

    def test_wrong_update_types_are_rejected(self):
        for column, value in (("id", "1"), ("name", 1), ("score", "90")):
            with self.subTest(column=column):
                with self.assertRaises(TypeMismatchError):
                    plan(UpdateStmt("students", column, value), self.catalog)

    def test_wrong_predicate_types_are_rejected_for_all_families(self):
        for column, value in (("id", "1"), ("name", 1)):
            predicate = Predicate(column, "=", value)
            for statement in (SelectStmt("students", None, predicate), UpdateStmt("students", "score", 1, predicate), DeleteStmt("students", predicate)):
                with self.subTest(column=column, family=type(statement).__name__):
                    with self.assertRaises(TypeMismatchError):
                        plan(statement, self.catalog)

    def test_signed_int64_boundary_values_are_valid(self):
        for value in (-(1 << 63), (1 << 63) - 1):
            with self.subTest(value=value):
                self.assertEqual(self.planned(f"INSERT INTO students VALUES ({value}, 'A', 0)").values[0], value)
                self.assertEqual(self.planned(f"UPDATE students SET id = {value}").value, value)
                self.assertEqual(self.planned(f"SELECT * FROM students WHERE id = {value}").predicate.value, value)

    def test_int64_overflow_rejected_in_insert_update_and_predicate(self):
        for value in (-(1 << 63) - 1, 1 << 63):
            statements = (InsertStmt("students", (value, "A", 0)), UpdateStmt("students", "id", value), SelectStmt("students", None, Predicate("id", "=", value)), DeleteStmt("students", Predicate("id", "=", value)))
            for statement in statements:
                with self.subTest(value=value, family=type(statement).__name__):
                    with self.assertRaises(TypeMismatchError):
                        plan(statement, self.catalog)

    def test_text_byte_limit_accepts_255_utf8_bytes(self):
        for value in ("a" * 255, "中" * 85, "🙂" * 63 + "abc", ""):
            with self.subTest(byte_count=len(value.encode("utf-8"))):
                self.assertEqual(plan(InsertStmt("students", (1, value, 0)), self.catalog), InsertPlan("students", (1, value, 0)))
                self.assertEqual(plan(UpdateStmt("students", "name", value), self.catalog).value, value)
                self.assertEqual(plan(SelectStmt("students", None, Predicate("name", "=", value)), self.catalog).predicate.value, value)

    def test_text_limit_rejects_256_or_more_utf8_bytes(self):
        for value in ("a" * 256, "中" * 86, "🙂" * 64):
            for statement in (InsertStmt("students", (1, value, 0)), UpdateStmt("students", "name", value), SelectStmt("students", None, Predicate("name", "=", value))):
                with self.subTest(byte_count=len(value.encode("utf-8")), family=type(statement).__name__):
                    with self.assertRaises(TypeMismatchError):
                        plan(statement, self.catalog)

    def test_direct_ast_does_not_treat_bool_as_int(self):
        for value in (True, False):
            for statement in (InsertStmt("students", (value, "A", 1)), UpdateStmt("students", "id", value), SelectStmt("students", None, Predicate("id", "=", value))):
                with self.subTest(value=value, family=type(statement).__name__):
                    with self.assertRaises(TypeMismatchError):
                        plan(statement, self.catalog)

    def test_direct_ast_rejects_values_outside_public_value_types(self):
        for value in (None, 1.5, b"bytes"):
            for statement in (InsertStmt("students", (value, "A", 1)), UpdateStmt("students", "name", value), SelectStmt("students", None, Predicate("name", "=", value))):
                with self.subTest(value=value, family=type(statement).__name__):
                    with self.assertRaises(TypeMismatchError):
                        plan(statement, self.catalog)

    def test_create_table_rejects_duplicate_columns(self):
        with self.assertRaises(SchemaError):
            self.planned("CREATE TABLE new_table (id INT, ID TEXT)")

    def test_create_table_rejects_empty_direct_schema(self):
        with self.assertRaises(SchemaError):
            plan(CreateTableStmt(TableSchema("empty", ())), self.catalog)

    def test_direct_ast_normalizes_identifiers(self):
        catalog = FakeCatalog(indexes=(("students", "id"),))
        self.assertEqual(
            plan(SelectStmt("STUDENTS", ("NAME", "ID"), Predicate("ID", "=", 1)), catalog),
            SelectPlan("students", ("name", "id"), Predicate("id", "=", 1), "index_eq"),
        )
        self.assertEqual(
            plan(CreateTableStmt(TableSchema("OTHER", (Column("ID", "INT"),))), catalog),
            CreateTablePlan(TableSchema("other", (Column("id", "INT"),))),
        )

    def test_invalid_direct_schema_is_a_schema_error(self):
        for schema in (
            TableSchema("bad-name", (Column("id", "INT"),)),
            TableSchema("valid", (Column("bad name", "INT"),)),
            TableSchema("valid", (Column("id", "FLOAT"),)),
            TableSchema("valid", (Column("ID", "INT"), Column("id", "TEXT"))),
        ):
            with self.subTest(schema=schema):
                with self.assertRaises(SchemaError):
                    plan(CreateTableStmt(schema), self.catalog)

    def test_unsupported_direct_predicate_operator_is_rejected(self):
        for operator in ("<>", "LIKE", "=="):
            with self.subTest(operator=operator):
                with self.assertRaises(SQLSyntaxError):
                    plan(SelectStmt("students", None, Predicate("id", operator, 1)), self.catalog)

    def test_text_with_unencodable_surrogate_is_a_type_error(self):
        value = "\ud800"
        for statement in (
            InsertStmt("students", (1, value, 0)),
            UpdateStmt("students", "name", value),
            SelectStmt("students", None, Predicate("name", "=", value)),
        ):
            with self.subTest(family=type(statement).__name__):
                with self.assertRaises(TypeMismatchError):
                    plan(statement, self.catalog)

    def test_create_table_name_collision_is_left_to_storage(self):
        schema = TableSchema("students", (Column("id", "INT"),))
        self.assertEqual(plan(CreateTableStmt(schema), self.catalog), CreateTablePlan(schema))
        self.assertEqual(self.catalog.calls, [])

    def test_create_index_validates_table_and_column_but_storage_owns_duplicates(self):
        catalog = FakeCatalog(indexes=(("students", "id"),))
        statement = CreateIndexStmt("existing_index_name", "students", "id")
        self.assertEqual(plan(statement, catalog), CreateIndexPlan("existing_index_name", "students", "id"))
        self.assertIn(("get_schema", "students"), catalog.calls)

    def test_planning_does_not_mutate_catalog_or_statement(self):
        catalog = FakeCatalog(indexes=(("students", "id"),))
        statement = SelectStmt("students", None, Predicate("id", "=", 1))
        schemas_before = dict(catalog.schemas)
        indexes_before = set(catalog.indexes)
        plan(statement, catalog)
        self.assertEqual(statement, SelectStmt("students", None, Predicate("id", "=", 1)))
        self.assertEqual(catalog.schemas, schemas_before)
        self.assertEqual(catalog.indexes, indexes_before)
        self.assertTrue(all(call[0] in {"get_schema", "has_index"} for call in catalog.calls))


if __name__ == "__main__":
    unittest.main()
