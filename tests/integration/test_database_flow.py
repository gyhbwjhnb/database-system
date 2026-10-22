"""End-to-end contract tests; become active when A and B land their modules."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from dbms.executor import execute


ROOT = Path(__file__).resolve().parents[2]


def _components():
    try:
        from dbms.frontend import parse, plan
        from dbms.storage import StorageEngine
    except ImportError:
        return None
    return (parse, plan, StorageEngine)


class DatabaseFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        components = _components()
        if components is None:
            self.skipTest("A storage and B frontend have not been integrated yet")
        self.parse, self.plan, self.StorageEngine = components

    def run_sql(self, storage, sql):
        return execute(self.plan(self.parse(sql), storage), storage)

    def test_index_updates_deletes_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = self.StorageEngine(directory)
            try:
                self.run_sql(storage, "CREATE TABLE students (id INT, name TEXT, score INT)")
                for row in (
                    "INSERT INTO students VALUES (1, 'Alice', 90)",
                    "INSERT INTO students VALUES (2, 'Bob', 60)",
                    "INSERT INTO students VALUES (3, 'Cara', 90)",
                ):
                    self.run_sql(storage, row)

                query = "SELECT id FROM students WHERE score = 90"
                before = self.run_sql(storage, query)
                self.assertEqual(before.plan_label, "SeqScan")
                self.assertEqual({row[0] for row in before.rows}, {1, 3})

                self.run_sql(storage, "CREATE INDEX idx_score ON students (score)")
                after = self.run_sql(storage, query)
                self.assertEqual(after.plan_label, "IndexEqScan")
                self.assertEqual({row[0] for row in after.rows}, {1, 3})

                updated = self.run_sql(
                    storage, "UPDATE students SET score = 80 WHERE score = 90"
                )
                self.assertEqual(updated.affected_rows, 2)
                self.assertEqual(self.run_sql(storage, query).rows, [])
                self.assertEqual(
                    {row[0] for row in self.run_sql(
                        storage, "SELECT id FROM students WHERE score = 80"
                    ).rows},
                    {1, 3},
                )

                deleted = self.run_sql(storage, "DELETE FROM students WHERE score = 80")
                self.assertEqual(deleted.affected_rows, 2)
                self.assertEqual(
                    self.run_sql(storage, "SELECT id FROM students WHERE score = 80").rows,
                    [],
                )
            finally:
                storage.close()

            reopened = self.StorageEngine(directory)
            try:
                result = self.run_sql(reopened, "SELECT id, name FROM students")
                self.assertEqual(result.rows, [(2, "Bob")])
                self.assertEqual(
                    self.run_sql(
                        reopened, "SELECT id FROM students WHERE score = 80"
                    ).plan_label,
                    "IndexEqScan",
                )
            finally:
                reopened.close()

    def test_cli_continues_after_error_and_reports_failure(self) -> None:
        if not (ROOT / "dbms" / "__main__.py").is_file():
            self.skipTest("B CLI has not been integrated yet")
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "input.sql"
            script.write_text(
                "CREATE TABLE students (id INT, name TEXT);\n"
                "SELECT missing FROM students;\n"
                "INSERT INTO students VALUES (1, 'Alice');\n",
                encoding="utf-8",
            )
            db_dir = Path(directory) / "db"
            completed = subprocess.run(
                [sys.executable, "-m", "dbms", "--db", str(db_dir), "--file", str(script)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0, completed.stdout)
            storage = self.StorageEngine(str(db_dir))
            try:
                result = self.run_sql(storage, "SELECT id, name FROM students")
                self.assertEqual(result.rows, [(1, "Alice")])
            finally:
                storage.close()


if __name__ == "__main__":
    unittest.main()
