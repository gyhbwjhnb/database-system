"""Contract tests for member B's SQL parser; no storage is required."""

import unittest

from dbms.frontend import parse
from dbms.types import (
    Column,
    CreateIndexStmt,
    CreateTableStmt,
    DeleteStmt,
    InsertStmt,
    Predicate,
    SelectStmt,
    SQLSyntaxError,
    TableSchema,
    UpdateStmt,
)


class ParserTests(unittest.TestCase):
    def test_documented_statement_families_have_exact_ast(self):
        examples = (
            (
                "CREATE TABLE students (id INT, name TEXT, score INT);",
                CreateTableStmt(
                    TableSchema(
                        "students",
                        (Column("id", "INT"), Column("name", "TEXT"), Column("score", "INT")),
                    )
                ),
            ),
            (
                "CREATE INDEX idx_students_id ON students (id);",
                CreateIndexStmt("idx_students_id", "students", "id"),
            ),
            ("INSERT INTO students VALUES (1, 'Alice', 90);", InsertStmt("students", (1, "Alice", 90))),
            (
                "SELECT id, name FROM students WHERE id = 1;",
                SelectStmt("students", ("id", "name"), Predicate("id", "=", 1)),
            ),
            (
                "SELECT * FROM students WHERE score >= 60;",
                SelectStmt("students", None, Predicate("score", ">=", 60)),
            ),
            (
                "UPDATE students SET score = 95 WHERE id = 1;",
                UpdateStmt("students", "score", 95, Predicate("id", "=", 1)),
            ),
            ("DELETE FROM students WHERE id = 1;", DeleteStmt("students", Predicate("id", "=", 1))),
        )
        for sql, expected in examples:
            with self.subTest(sql=sql):
                self.assertEqual(parse(sql), expected)

    def test_optional_terminator_and_surrounding_whitespace(self):
        expected = SelectStmt("students", ("id",), None)
        for sql in ("SELECT id FROM students", " \t\nSELECT id FROM students ; \r\n"):
            with self.subTest(sql=sql):
                self.assertEqual(parse(sql), expected)

    def test_keywords_and_identifiers_are_case_insensitive(self):
        examples = (
            ("cReAtE TaBlE Mixed (ID iNt, NaMe tExT)", CreateTableStmt(TableSchema("mixed", (Column("id", "INT"), Column("name", "TEXT"))))),
            ("CrEaTe InDeX IDX ON MiXeD (ID)", CreateIndexStmt("idx", "mixed", "id")),
            ("iNsErT iNtO MiXeD vAlUeS (-12, 'MiXeD')", InsertStmt("mixed", (-12, "MiXeD"))),
            ("SeLeCt NaMe, ID fRoM MiXeD wHeRe ID != -12", SelectStmt("mixed", ("name", "id"), Predicate("id", "!=", -12))),
            ("UpDaTe MiXeD sEt NaMe = 'UPPER' wHeRe ID < 3", UpdateStmt("mixed", "name", "UPPER", Predicate("id", "<", 3))),
            ("DeLeTe FrOm MiXeD wHeRe ID > 3", DeleteStmt("mixed", Predicate("id", ">", 3))),
        )
        for sql, expected in examples:
            with self.subTest(sql=sql):
                self.assertEqual(parse(sql), expected)

    def test_ascii_identifier_shape(self):
        self.assertEqual(parse("SELECT _Field2 FROM _Table9"), SelectStmt("_table9", ("_field2",)))
        self.assertEqual(parse("CREATE INDEX _Index3 ON _Table9 (_Field2)"), CreateIndexStmt("_index3", "_table9", "_field2"))

    def test_single_quotes_and_literal_contents_are_preserved(self):
        values = (
            ("''", ""),
            ("'O''Brien'", "O'Brien"),
            ("''''", "'"),
            ("'a; SELECT * FROM another; b'", "a; SELECT * FROM another; b"),
            ("'-- not a comment /* either */ # text'", "-- not a comment /* either */ # text"),
            ("'中文🙂'", "中文🙂"),
            ("'  Spaces And CASE  '", "  Spaces And CASE  "),
            (r"'C:\folder\file'", r"C:\folder\file"),
        )
        for literal, expected in values:
            with self.subTest(literal=literal):
                self.assertEqual(parse(f"INSERT INTO t VALUES ({literal});"), InsertStmt("t", (expected,)))

    def test_signed_integer_literals(self):
        for literal, expected in (("0", 0), ("-0", 0), ("-42", -42), ("0012", 12)):
            with self.subTest(literal=literal):
                self.assertEqual(parse(f"INSERT INTO t VALUES ({literal})"), InsertStmt("t", (expected,)))

    def test_all_comparison_operators(self):
        for operator in ("=", "!=", "<", "<=", ">", ">="):
            with self.subTest(operator=operator):
                self.assertEqual(
                    parse(f"SELECT * FROM t WHERE c{operator}-2"),
                    SelectStmt("t", None, Predicate("c", operator, -2)),
                )

    def test_update_and_delete_without_where(self):
        self.assertEqual(parse("UPDATE t SET c = 'all'"), UpdateStmt("t", "c", "all"))
        self.assertEqual(parse("DELETE FROM t;"), DeleteStmt("t"))

    def test_projection_order_and_duplicates_are_preserved(self):
        self.assertEqual(parse("SELECT b, a, b FROM t"), SelectStmt("t", ("b", "a", "b")))

    def test_parse_leaves_value_ranges_and_schema_to_planning(self):
        huge = str(1 << 70)
        self.assertEqual(parse(f"INSERT INTO missing VALUES ({huge})"), InsertStmt("missing", (1 << 70,)))
        text = "中" * 86
        self.assertEqual(parse(f"UPDATE missing SET unknown = '{text}'"), UpdateStmt("missing", "unknown", text))
        self.assertEqual(
            parse("CREATE TABLE t (id INT, ID TEXT)"),
            CreateTableStmt(TableSchema("t", (Column("id", "INT"), Column("id", "TEXT")))),
        )

    def test_rejects_empty_and_multiple_statements(self):
        for sql in ("", " \n\t", ";", ";SELECT * FROM t", "SELECT * FROM t;;", "SELECT * FROM t; DELETE FROM t", "SELECT * FROM t DELETE FROM t"):
            with self.subTest(sql=sql):
                with self.assertRaises(SQLSyntaxError):
                    parse(sql)

    def test_rejects_comments_outside_literals(self):
        for sql in ("-- comment\nSELECT * FROM t", "SELECT * FROM t -- comment", "SELECT /* comment */ * FROM t", "SELECT * FROM t; # comment"):
            with self.subTest(sql=sql):
                with self.assertRaises(SQLSyntaxError):
                    parse(sql)

    def test_rejects_unsupported_identifier_forms(self):
        for sql in ('SELECT "id" FROM t', "SELECT `id` FROM t", "SELECT [id] FROM t", "SELECT * FROM 1table", "SELECT * FROM 学生", "SELECT naïve FROM t", "SELECT t.id FROM t", "SELECT * FROM t-name"):
            with self.subTest(sql=sql):
                with self.assertRaises(SQLSyntaxError):
                    parse(sql)

    def test_rejects_unsupported_literals_and_operators(self):
        for expression in ("1.5", "+1", "NULL", "TRUE", '"text"', "1abc", "1e3", "0x10", "'unterminated"):
            with self.subTest(expression=expression):
                with self.assertRaises(SQLSyntaxError):
                    parse(f"INSERT INTO t VALUES ({expression})")
        for operator in ("<>", "==", "=>", "=<", "!", "LIKE", "IS"):
            with self.subTest(operator=operator):
                with self.assertRaises(SQLSyntaxError):
                    parse(f"SELECT * FROM t WHERE c {operator} 1")

    def test_rejects_malformed_and_out_of_scope_grammar(self):
        invalid = (
            "CREATE TABLE t ()",
            "CREATE TABLE t (id INT,)",
            "CREATE TABLE t (id FLOAT)",
            "CREATE TABLE t (id INT PRIMARY KEY)",
            "CREATE INDEX idx ON t (id, name)",
            "CREATE INDEX idx t (id)",
            "INSERT t VALUES (1)",
            "INSERT INTO t (id) VALUES (1)",
            "INSERT INTO t VALUES ()",
            "INSERT INTO t VALUES (1,)",
            "INSERT INTO t VALUES (1), (2)",
            "SELECT FROM t",
            "SELECT *, id FROM t",
            "SELECT id, FROM t",
            "SELECT * t",
            "SELECT * FROM t WHERE id",
            "SELECT * FROM t WHERE id =",
            "SELECT * FROM t WHERE 1 = id",
            "SELECT * FROM t WHERE id = 1 AND name = 'a'",
            "SELECT * FROM t WHERE id = 1 OR id = 2",
            "SELECT * FROM t ORDER BY id",
            "SELECT COUNT(id) FROM t",
            "SELECT * FROM t JOIN other ON t.id = other.id",
            "UPDATE t SET id = 1, name = 'a'",
            "UPDATE t id = 1",
            "UPDATE t SET id != 1",
            "DELETE t",
            "DROP TABLE t",
        )
        for sql in invalid:
            with self.subTest(sql=sql):
                with self.assertRaises(SQLSyntaxError):
                    parse(sql)


if __name__ == "__main__":
    unittest.main()
