"""Isolated CLI checks: mocks exercise contracts, never a replacement backend."""

from __future__ import annotations

import io
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from dbms.frontend.cli import main, split_statements, write_result
from dbms.types import Result, SchemaError, SQLSyntaxError, StorageError


class SplitStatementsTests(unittest.TestCase):
    def test_quoted_semicolons_and_doubled_quotes(self):
        self.assertEqual(
            split_statements("INSERT INTO t VALUES ('it''s; fine'); SELECT * FROM t;"),
            ["INSERT INTO t VALUES ('it''s; fine')", "SELECT * FROM t"],
        )

    def test_optional_terminal_semicolon_and_empty_statements(self):
        self.assertEqual(split_statements(" ;\n; SELECT * FROM t\n ; ;SELECT * FROM u"), ["SELECT * FROM t", "SELECT * FROM u"])
        self.assertEqual(split_statements("; \n;"), [])

    def test_strings_can_span_lines(self):
        self.assertEqual(split_statements("INSERT INTO t VALUES ('first;\nsecond');"), ["INSERT INTO t VALUES ('first;\nsecond')"])

    def test_unclosed_string_is_kept_for_parser_error(self):
        self.assertEqual(split_statements("INSERT INTO t VALUES ('bad; SELECT * FROM t;"), ["INSERT INTO t VALUES ('bad; SELECT * FROM t;"])

    def test_empty_and_escaped_quote_strings(self):
        self.assertEqual(split_statements("INSERT INTO t VALUES (''); INSERT INTO t VALUES (''''); SELECT * FROM t"), ["INSERT INTO t VALUES ('')", "INSERT INTO t VALUES ('''')", "SELECT * FROM t"])


class ResultOutputTests(unittest.TestCase):
    def test_query_header_rows_and_plan(self):
        output = io.StringIO()
        write_result(Result(columns=("id", "name"), rows=[(7, "Alice")], plan_label="IndexEqScan"), output)
        text = output.getvalue()
        self.assertIn("Plan: IndexEqScan", text)
        self.assertIn("| id | name  |", text)
        self.assertIn("| 7  | Alice |", text)
        self.assertIn("1 row(s).", text)
        self.assertNotIn("affected", text)

    def test_empty_query_shows_columns_and_count(self):
        output = io.StringIO()
        write_result(Result(columns=("id",), plan_label="SeqScan"), output)
        self.assertIn("| id |", output.getvalue())
        self.assertIn("0 row(s).", output.getvalue())

    def test_write_affected_count_and_label(self):
        output = io.StringIO()
        write_result(Result(affected_rows=3, plan_label="DeleteSeqScan"), output)
        self.assertEqual(output.getvalue(), "Plan: DeleteSeqScan\n3 row(s) affected.\n")

    def test_controls_do_not_break_table_rows(self):
        output = io.StringIO()
        write_result(Result(columns=("name",), rows=[("a\nb\t\\c",)], plan_label="SeqScan"), output)
        self.assertIn("a\\nb\\t\\\\c", output.getvalue())

    def test_chinese_headers_values_and_combining_text_align(self):
        output = io.StringIO()
        write_result(Result(columns=("姓名", "备注"), rows=[("张三", "e\u0301")], plan_label="SeqScan"), output)
        self.assertEqual(output.getvalue(), "Plan: SeqScan\n+------+------+\n| 姓名 | 备注 |\n+------+------+\n| 张三 | e\u0301    |\n+------+------+\n1 row(s).\n")

    def test_terminal_controls_are_escaped(self):
        output = io.StringIO()
        write_result(Result(columns=("text",), rows=[("a\x1b\x07\x7fb",)], plan_label="SeqScan"), output)
        self.assertIn("a\\x1b\\x07\\x7fb", output.getvalue())
        self.assertNotIn("\x1b", output.getvalue())

    def test_invalid_result_is_a_programmer_error(self):
        with self.assertRaisesRegex(ValueError, "row width"):
            write_result(Result(columns=("id",), rows=[(1, 2)], plan_label="SeqScan"), io.StringIO())


class CLITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.script = Path(self.directory.name) / "input.sql"
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.storage = Mock(spec=["close"])
        self.factory = Mock(return_value=self.storage)
        self.parse = Mock(side_effect=lambda sql: sql)
        self.plan = Mock(side_effect=lambda statement, catalog: statement)
        self.execute = Mock(return_value=Result(affected_rows=1, plan_label="Insert"))

    def run_cli(self, sql=None, *, stdin=None, args=()):
        arguments = ["--db", str(Path(self.directory.name) / "data")]
        if sql is not None:
            self.script.write_text(sql, encoding="utf-8")
            arguments.extend(["--file", str(self.script)])
        arguments.extend(args)
        return main(arguments, stdin=io.StringIO("") if stdin is None else stdin, stdout=self.stdout, stderr=self.stderr, storage_factory=self.factory, execute_fn=self.execute, parse_fn=self.parse, plan_fn=self.plan)

    def test_script_runs_pipeline_in_order_and_closes(self):
        events = []
        self.parse.side_effect = lambda sql: events.append(("parse", sql)) or sql
        self.plan.side_effect = lambda statement, catalog: events.append(("plan", statement, catalog)) or statement
        self.execute.side_effect = lambda plan, storage: events.append(("execute", plan, storage)) or Result(plan_label="Insert", affected_rows=1)
        self.assertEqual(self.run_cli("first; second; third"), 0)
        self.assertEqual([item[:2] for item in events], [(stage, sql) for sql in ("first", "second", "third") for stage in ("parse", "plan", "execute")])
        self.assertTrue(all(item[2] is self.storage for item in events if len(item) == 3))
        self.storage.close.assert_called_once_with()
        self.factory.assert_called_once_with(str(Path(self.directory.name) / "data"), buffer_pages=64)
        self.assertEqual(self.stderr.getvalue(), "")

    def test_parse_error_continues_and_script_returns_failure(self):
        self.parse.side_effect = [SQLSyntaxError("bad SQL"), "valid"]
        self.assertEqual(self.run_cli("bad; good;"), 1)
        self.assertEqual(self.parse.call_count, 2)
        self.execute.assert_called_once_with("valid", self.storage)
        self.assertIn("Error: bad SQL", self.stderr.getvalue())
        self.storage.close.assert_called_once_with()

    def test_planning_error_continues(self):
        self.plan.side_effect = [SchemaError("unknown table"), "valid"]
        self.assertEqual(self.run_cli("bad; good;"), 1)
        self.execute.assert_called_once_with("valid", self.storage)
        self.assertIn("unknown table", self.stderr.getvalue())

    def test_execution_error_continues(self):
        self.execute.side_effect = [StorageError("disk full"), Result(plan_label="Insert", affected_rows=1)]
        self.assertEqual(self.run_cli("first; second;"), 1)
        self.assertEqual(self.execute.call_count, 2)
        self.assertIn("disk full", self.stderr.getvalue())
        self.assertIn("1 row(s) affected", self.stdout.getvalue())

    def test_multiline_interactive_and_exit(self):
        source = io.StringIO("INSERT INTO t\nVALUES ('it''s;\nfine'); SELECT * FROM t;\n.exit\nignored;\n")
        self.assertEqual(self.run_cli(stdin=source), 0)
        self.assertEqual([call.args[0] for call in self.parse.call_args_list], ["INSERT INTO t\nVALUES ('it''s;\nfine')", "SELECT * FROM t"])
        self.assertIn("...> ", self.stdout.getvalue())
        self.storage.close.assert_called_once_with()

    def test_interactive_eof_accepts_final_statement(self):
        self.assertEqual(self.run_cli(stdin=io.StringIO("SELECT *\nFROM t")), 0)
        self.parse.assert_called_once_with("SELECT *\nFROM t")
        self.storage.close.assert_called_once_with()

    def test_exit_discards_pending_statement_outside_string(self):
        self.assertEqual(self.run_cli(stdin=io.StringIO("SELECT *\n.exit\nignored;\n")), 0)
        self.parse.assert_not_called()
        self.storage.close.assert_called_once_with()

    def test_exit_inside_multiline_string_is_sql_text(self):
        self.assertEqual(self.run_cli(stdin=io.StringIO("INSERT INTO t VALUES ('first\n.exit\nlast');\n.exit\n")), 0)
        self.parse.assert_called_once_with("INSERT INTO t VALUES ('first\n.exit\nlast')")

    def test_interactive_error_does_not_end_session(self):
        self.parse.side_effect = [SQLSyntaxError("bad SQL"), "good"]
        self.assertEqual(self.run_cli(stdin=io.StringIO("bad;\ngood;\n.exit\n")), 0)
        self.execute.assert_called_once_with("good", self.storage)
        self.assertIn("bad SQL", self.stderr.getvalue())

    def test_control_c_during_input_closes(self):
        source = Mock()
        source.readline.side_effect = KeyboardInterrupt
        self.assertEqual(self.run_cli(stdin=source), 130)
        self.storage.close.assert_called_once_with()
        self.assertIn("Interrupted", self.stderr.getvalue())

    def test_control_c_during_execution_closes(self):
        self.execute.side_effect = KeyboardInterrupt
        self.assertEqual(self.run_cli("first; second;"), 130)
        self.assertEqual(self.execute.call_count, 1)
        self.storage.close.assert_called_once_with()

    def test_close_error_is_reported_and_nonzero(self):
        self.storage.close.side_effect = StorageError("flush failed")
        self.assertEqual(self.run_cli("first;"), 1)
        self.assertIn("Error closing database: flush failed", self.stderr.getvalue())

    def test_close_error_keeps_interrupt_status(self):
        self.execute.side_effect = KeyboardInterrupt
        self.storage.close.side_effect = OSError("write failed")
        self.assertEqual(self.run_cli("first;"), 130)
        self.assertIn("Error closing database", self.stderr.getvalue())

    def test_unexpected_programmer_error_propagates_but_closes(self):
        self.execute.side_effect = RuntimeError("implementation bug")
        with self.assertRaisesRegex(RuntimeError, "implementation bug"):
            self.run_cli("first; second;")
        self.storage.close.assert_called_once_with()

    def test_database_open_errors_are_reported(self):
        for error in (StorageError("invalid database"), OSError("permission denied")):
            with self.subTest(error=error):
                self.factory.side_effect = error
                self.assertEqual(self.run_cli("first;"), 1)
        self.storage.close.assert_not_called()

    def test_custom_buffer_capacity(self):
        self.assertEqual(self.run_cli("", args=("--buffer-pages", "2")), 0)
        self.assertEqual(self.factory.call_args.kwargs, {"buffer_pages": 2})

    def test_script_bom_is_accepted(self):
        self.assertEqual(self.run_cli("\ufefffirst;"), 0)
        self.parse.assert_called_once_with("first")

    def test_missing_script_does_not_open_storage(self):
        self.assertEqual(main(["--db", "unused", "--file", str(self.script)], stdout=self.stdout, stderr=self.stderr, storage_factory=self.factory, execute_fn=self.execute), 1)
        self.factory.assert_not_called()
        self.assertIn("Error reading SQL file", self.stderr.getvalue())

    def test_bad_utf8_is_reported_without_opening_storage(self):
        self.script.write_bytes(b"\xff")
        self.assertEqual(main(["--db", "unused", "--file", str(self.script)], stdout=self.stdout, stderr=self.stderr, storage_factory=self.factory, execute_fn=self.execute), 1)
        self.factory.assert_not_called()
        self.assertIn("Error reading SQL file", self.stderr.getvalue())

    def test_missing_backend_is_explicit_and_does_not_create_data(self):
        database = Path(self.directory.name) / "must-not-exist"
        with patch("dbms.frontend.cli.importlib.import_module", return_value=SimpleNamespace()):
            self.assertEqual(main(["--db", str(database)], stdout=self.stdout, stderr=self.stderr), 1)
        self.assertIn("member A: dbms.storage.StorageEngine", self.stderr.getvalue())
        self.assertIn("member C: dbms.executor.execute", self.stderr.getvalue())
        self.assertFalse(database.exists())

    def test_backend_internal_import_error_is_not_hidden(self):
        with patch("dbms.frontend.cli.importlib.import_module", side_effect=ImportError("backend bug")):
            with self.assertRaisesRegex(ImportError, "backend bug"):
                main(["--db", "unused"], stdout=self.stdout, stderr=self.stderr)

    def test_help_works_without_backend(self):
        completed = subprocess.run([sys.executable, "-m", "dbms", "--help"], cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--db PATH", completed.stdout)
        self.assertIn("--file PATH", completed.stdout)
        self.assertIn("--buffer-pages N", completed.stdout)
        self.assertNotIn("Backend unavailable", completed.stderr)

    def test_invalid_buffer_capacity_is_argument_error(self):
        for value in ("0", "-1", "x"):
            with self.subTest(value=value), patch("sys.stderr", self.stderr):
                with self.assertRaises(SystemExit) as raised:
                    self.run_cli("", args=("--buffer-pages", value))
                self.assertEqual(raised.exception.code, 2)
        self.factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
