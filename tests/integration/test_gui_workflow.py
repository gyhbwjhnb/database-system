"""Real database workflow through the optional desktop interface."""

from __future__ import annotations

import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from dbms.gui.app import DatabaseApp
from dbms.gui.session import DatabaseSession
from dbms.storage import StorageEngine


class GuiWorkflowTests(unittest.TestCase):
    def test_session_runs_script_keeps_errors_and_switches_databases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first"
            second = Path(directory) / "second"
            session = DatabaseSession(first)
            try:
                records = session.execute_text(
                    "CREATE TABLE notes (id INT, body TEXT);"
                    "INSERT INTO notes VALUES (1, 'hello; world');"
                    "SELECT missing FROM notes;"
                    "SELECT body FROM notes WHERE id = 1;"
                )
                self.assertEqual(len(records), 4)
                self.assertEqual(sum(record.error is not None for record in records), 1)
                self.assertEqual(records[-1].result.rows, [("hello; world",)])
                self.assertEqual(session.list_tables(), ("notes",))
                self.assertEqual(session.get_schema("notes").columns[0].name, "id")

                # Writes are flushed after each successful statement, even
                # while the GUI session remains open.
                observer = StorageEngine(str(first))
                try:
                    self.assertEqual([row.values for row in observer.scan("notes")], [(1, "hello; world")])
                finally:
                    observer.close()

                session.switch_database(second)
                self.assertEqual(session.list_tables(), ())
                session.switch_database(first)
                self.assertEqual(session.list_tables(), ("notes",))
            finally:
                session.close()

    def test_window_can_execute_and_display_results(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"graphical display unavailable: {error}")
        root.withdraw()
        with tempfile.TemporaryDirectory() as directory:
            session = DatabaseSession(directory)
            try:
                app = DatabaseApp(root, session)
                app.editor.insert(
                    "1.0",
                    "CREATE TABLE people (id INT, name TEXT);"
                    "INSERT INTO people VALUES (1, 'Alice');"
                    "SELECT name FROM people;",
                )
                app._run_sql()
                self.assertEqual(len(app.records), 3)
                self.assertEqual(app.tables.get(0), "people")
                self.assertEqual(app.result_table["columns"], ("col_0",))
                rows = app.result_table.get_children()
                self.assertEqual(len(rows), 1)
                self.assertEqual(app.result_table.item(rows[0], "values"), ("Alice",))
            finally:
                session.close()
                root.destroy()


if __name__ == "__main__":
    unittest.main()
