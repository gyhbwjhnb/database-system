"""Exercise the real B pipeline with only the A/C boundaries replaced."""

from __future__ import annotations

import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from dbms.frontend.cli import main
from dbms.types import (
    Column,
    CreateIndexPlan,
    CreateTablePlan,
    DeletePlan,
    InsertPlan,
    Predicate,
    Result,
    SelectPlan,
    TableSchema,
    UpdatePlan,
)


class FrontendWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.schema = TableSchema("students", (Column("id", "INT"), Column("name", "TEXT")))
        self.storage = Mock(spec=["get_schema", "has_index", "close"])
        self.storage.get_schema.return_value = self.schema
        self.storage.has_index.return_value = True
        self.factory = Mock(return_value=self.storage)
        self.stdout, self.stderr = io.StringIO(), io.StringIO()

    def run_script(self, sql, execute):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "frontend.sql"
            script.write_text(sql, encoding="utf-8")
            return main(
                ["--db", str(Path(directory) / "unused-data"), "--file", str(script)],
                storage_factory=self.factory,
                execute_fn=execute,
                stdout=self.stdout,
                stderr=self.stderr,
            )

    def test_all_six_real_parser_and_planner_paths_reach_executor(self):
        expected = [
            CreateTablePlan(self.schema),
            CreateIndexPlan("idx_id", "students", "id"),
            InsertPlan("students", (1, "O'Brien; 中文")),
            SelectPlan("students", ("name", "id"), Predicate("id", "=", 1), "index_eq"),
            UpdatePlan("students", "name", "Bob", None, "seq"),
            DeletePlan("students", Predicate("id", ">=", 1), "seq"),
        ]
        labels = ["CreateTable", "CreateIndex", "Insert", "IndexEqScan", "UpdateSeqScan", "DeleteSeqScan"]
        execute = Mock(side_effect=[Result(plan_label=label) for label in labels])
        status = self.run_script(
            "CREATE TABLE Students (Id INT, Name TEXT);\n"
            "CREATE INDEX idx_id ON Students (Id);\n"
            "INSERT INTO Students VALUES (1, 'O''Brien; 中文');\n"
            "SELECT Name, Id FROM Students WHERE Id = 1;\n"
            "UPDATE Students SET Name = 'Bob';\n"
            "DELETE FROM Students WHERE Id >= 1",
            execute,
        )
        self.assertEqual(status, 0, self.stderr.getvalue())
        self.assertEqual([call.args for call in execute.call_args_list], [(item, self.storage) for item in expected])
        for label in labels:
            self.assertIn("Plan: " + label, self.stdout.getvalue())
        self.storage.close.assert_called_once_with()

    def test_syntax_and_type_errors_skip_executor_and_preserve_later_sql(self):
        execute = Mock(return_value=Result(columns=("id",), rows=[(1,)], plan_label="SeqScan"))
        status = self.run_script(
            "SELECT FROM students;\n"
            "INSERT INTO students VALUES ('wrong type', 'Alice');\n"
            "SELECT id FROM students;",
            execute,
        )
        self.assertEqual(status, 1)
        execute.assert_called_once_with(SelectPlan("students", ("id",), None, "seq"), self.storage)
        self.assertEqual(self.stderr.getvalue().count("Error:"), 2)
        self.assertIn("| 1", self.stdout.getvalue())
        self.storage.close.assert_called_once_with()

    def test_real_interactive_parser_handles_multiline_and_quoted_semicolons(self):
        execute = Mock(return_value=Result(affected_rows=1, plan_label="Insert"))
        status = main(
            ["--db", "unused"],
            storage_factory=self.factory,
            execute_fn=execute,
            stdin=io.StringIO("INSERT INTO Students\nVALUES (-1, 'Alice; O''Brien');\n.exit\n"),
            stdout=self.stdout,
            stderr=self.stderr,
        )
        self.assertEqual(status, 0, self.stderr.getvalue())
        execute.assert_called_once_with(InsertPlan("students", (-1, "Alice; O'Brien")), self.storage)
        self.storage.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
