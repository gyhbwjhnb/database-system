"""Double-click this file on Windows to open the database desktop UI."""

from pathlib import Path

from dbms.gui.app import main


if __name__ == "__main__":
    default_db = Path(__file__).resolve().parent / "gui_data"
    raise SystemExit(main(["--db", str(default_db)]))
