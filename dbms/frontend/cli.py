"""SQL input and result presentation; execution remains member C's job.

``main`` accepts explicit dependencies and streams so CLI behavior can be
tested without implementing either the storage or execution module.
``split_statements`` also accepts an unterminated final statement: the parser
then reports malformed SQL, including an unclosed string, in the normal way.
"""

from __future__ import annotations

import argparse
import importlib
import sys
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import TextIO

from dbms.contracts import ExecuteFn, ParseFn, PlanFn, StoragePort
from dbms.types import DBMSError, Result


StorageFactory = Callable[..., StoragePort]


class BackendUnavailableError(DBMSError):
    """A separately owned storage or executor export is not yet available."""


def _split_complete(sql: str) -> tuple[list[str], str, bool]:
    """Return complete statements, the suffix and its open-string state."""
    statements: list[str] = []
    start = 0
    position = 0
    in_string = False
    while position < len(sql):
        character = sql[position]
        if character == "'":
            if in_string and position + 1 < len(sql) and sql[position + 1] == "'":
                position += 2
                continue
            in_string = not in_string
        elif character == ";" and not in_string:
            statement = sql[start:position].strip()
            if statement:
                statements.append(statement)
            start = position + 1
        position += 1
    return statements, sql[start:], in_string


def split_statements(sql: str) -> list[str]:
    """Split a script, preserving semicolons and doubled quotes in strings.

    Empty statements are ignored. A final nonblank statement needs no trailing
    semicolon. This helper only splits SQL; syntax validation belongs to parse.
    """
    statements, remainder, _ = _split_complete(sql)
    if remainder.strip():
        statements.append(remainder.strip())
    return statements


def _cell_text(value: object) -> str:
    escapes = {"\\": "\\\\", "\r": "\\r", "\n": "\\n", "\t": "\\t"}
    return "".join(
        escapes.get(character, f"\\x{ord(character):02x}")
        if character in escapes or unicodedata.category(character) == "Cc"
        else character
        for character in str(value)
    )


def _display_width(text: str) -> int:
    """Approximate terminal cells for CJK and combining Unicode characters."""
    return sum(
        0 if unicodedata.combining(character)
        else 2 if unicodedata.east_asian_width(character) in ("W", "F")
        else 1
        for character in text
    )


def write_result(result: Result, stream: TextIO) -> None:
    """Display a Result without reading storage or interpreting a plan."""
    print(f"Plan: {result.plan_label}", file=stream)
    if not result.columns:
        print(f"{result.affected_rows} row(s) affected.", file=stream)
        return

    headers = tuple(_cell_text(column) for column in result.columns)
    rows = [tuple(_cell_text(value) for value in row) for row in result.rows]
    widths = [_display_width(column) for column in headers]
    for row in rows:
        if len(row) != len(headers):
            raise ValueError("Result row width does not match its columns")
        widths = [max(width, _display_width(value)) for width, value in zip(widths, row)]
    border = "+" + "+".join("-" * (width + 2) for width in widths) + "+"

    def write_row(row: tuple[str, ...]) -> None:
        cells = [value + " " * (width - _display_width(value)) for value, width in zip(row, widths)]
        print("| " + " | ".join(cells) + " |", file=stream)

    print(border, file=stream)
    write_row(headers)
    print(border, file=stream)
    for row in rows:
        write_row(row)
    print(border, file=stream)
    print(f"{len(rows)} row(s).", file=stream)


def _load_backend(
    storage_factory: StorageFactory | None, execute_fn: ExecuteFn | None
) -> tuple[StorageFactory, ExecuteFn]:
    missing: list[str] = []
    if storage_factory is None:
        storage_factory = getattr(importlib.import_module("dbms.storage"), "StorageEngine", None)
        if storage_factory is None:
            missing.append("member A: dbms.storage.StorageEngine")
    if execute_fn is None:
        execute_fn = getattr(importlib.import_module("dbms.executor"), "execute", None)
        if execute_fn is None:
            missing.append("member C: dbms.executor.execute")
    if missing:
        raise BackendUnavailableError(
            "Backend unavailable (" + "; ".join(missing) + "). "
            "Part B requires these modules to run SQL; merge their implementations first."
        )
    return storage_factory, execute_fn


def _positive_pages(value: str) -> int:
    try:
        pages = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("buffer pages must be a positive integer") from error
    if pages <= 0:
        raise argparse.ArgumentTypeError("buffer pages must be a positive integer")
    return pages


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the documented ``python -m dbms`` argument parser."""
    parser = argparse.ArgumentParser(description="Run the course DBMS SQL command line.")
    parser.add_argument("--db", required=True, metavar="PATH", help="database directory")
    parser.add_argument("--file", metavar="PATH", help="execute a UTF-8 SQL script")
    parser.add_argument("--buffer-pages", type=_positive_pages, default=64, metavar="N", help="storage buffer capacity (default: 64)")
    return parser


def _execute_statements(
    statements: Iterable[str],
    storage: StoragePort,
    parse_fn: ParseFn,
    plan_fn: PlanFn,
    execute_fn: ExecuteFn,
    stdout: TextIO,
    stderr: TextIO,
) -> bool:
    """Execute in order; return whether any expected SQL error occurred."""
    had_error = False
    for sql in statements:
        try:
            result = execute_fn(plan_fn(parse_fn(sql), storage), storage)
        except DBMSError as error:
            print(f"Error: {error}", file=stderr)
            had_error = True
        else:
            write_result(result, stdout)
    return had_error


def _interactive(
    storage: StoragePort,
    parse_fn: ParseFn,
    plan_fn: PlanFn,
    execute_fn: ExecuteFn,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    buffer = ""
    in_string = False
    while True:
        stdout.write("...> " if buffer.strip() else "dbms> ")
        stdout.flush()
        line = stdin.readline()
        if line == "":
            # EOF is a statement boundary even when its semicolon was omitted.
            _execute_statements(split_statements(buffer), storage, parse_fn, plan_fn, execute_fn, stdout, stderr)
            return 0
        if line.strip() == ".exit" and not in_string:
            return 0
        buffer += line
        statements, buffer, in_string = _split_complete(buffer)
        _execute_statements(statements, storage, parse_fn, plan_fn, execute_fn, stdout, stderr)


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    storage_factory: StorageFactory | None = None,
    execute_fn: ExecuteFn | None = None,
    parse_fn: ParseFn | None = None,
    plan_fn: PlanFn | None = None,
) -> int:
    """Run a session and close its storage in every exit path.

    Explicit dependency overrides are intended for tests and embedding. Normal
    execution imports the public A/B/C interfaces, with no stand-in backend.
    Script errors return 1 after all statements; Ctrl-C returns 130. Interactive
    SQL errors are displayed while the session remains usable. A standalone
    ``.exit`` outside a quoted string discards unfinished input and exits.
    """
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    args = build_argument_parser().parse_args(argv)

    script: str | None = None
    if args.file is not None:
        try:
            script = Path(args.file).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            print(f"Error reading SQL file: {error}", file=stderr)
            return 1

    storage: StoragePort | None = None
    status = 0
    try:
        storage_factory, execute_fn = _load_backend(storage_factory, execute_fn)
        if parse_fn is None or plan_fn is None:
            from dbms.frontend import parse, plan

            parse_fn = parse if parse_fn is None else parse_fn
            plan_fn = plan if plan_fn is None else plan_fn
        try:
            storage = storage_factory(args.db, buffer_pages=args.buffer_pages)
        except OSError as error:
            print(f"Error opening database: {error}", file=stderr)
            return 1
        if script is None:
            status = _interactive(storage, parse_fn, plan_fn, execute_fn, stdin, stdout, stderr)
        else:
            status = int(_execute_statements(split_statements(script), storage, parse_fn, plan_fn, execute_fn, stdout, stderr))
    except DBMSError as error:
        print(f"Error: {error}", file=stderr)
        status = 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=stderr)
        status = 130
    finally:
        if storage is not None:
            try:
                storage.close()
            except (DBMSError, OSError) as error:
                print(f"Error closing database: {error}", file=stderr)
                if status == 0:
                    status = 1
    return status
