"""Recursive-descent parser for the six frozen MVP SQL statement forms."""

from __future__ import annotations

from typing import cast

from dbms.types import (
    Column,
    ColumnType,
    CreateIndexStmt,
    CreateTableStmt,
    DeleteStmt,
    InsertStmt,
    Operator,
    Predicate,
    SelectStmt,
    SQLSyntaxError,
    Statement,
    TableSchema,
    UpdateStmt,
    Value,
)

from .lexer import Token, tokenize


def _integer(spelling: str) -> int:
    """Decode arbitrary-length decimal input without Python's digit-limit error.

    INT64 validation belongs to the planner. Small chunks also avoid changing
    the interpreter-wide integer-conversion security setting.
    """
    negative = spelling.startswith("-")
    digits = spelling[1:] if negative else spelling
    value = 0
    for start in range(0, len(digits), 9):
        chunk = digits[start : start + 9]
        value = value * (10 ** len(chunk)) + int(chunk)
    return -value if negative else value


class _Parser:
    def __init__(self, tokens: tuple[Token, ...]) -> None:
        self.tokens = tokens
        self.position = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.position]

    def error(self, expected: str) -> SQLSyntaxError:
        token = self.current
        found = "end of SQL" if token.kind == "EOF" else repr(token.value[:40])
        return SQLSyntaxError(
            f"Expected {expected}, found {found} at line {token.line}, "
            f"column {token.column} (offset {token.offset})"
        )

    def accept(self, kind: str) -> Token | None:
        if self.current.kind != kind:
            return None
        token = self.current
        self.position += 1
        return token

    def require(self, kind: str, description: str | None = None) -> Token:
        token = self.accept(kind)
        if token is None:
            raise self.error(description or kind)
        return token

    def identifier(self) -> str:
        return self.require("IDENT", "an identifier").value

    def literal(self) -> Value:
        token = self.accept("INTEGER")
        if token is not None:
            return _integer(token.value)
        token = self.accept("STRING")
        if token is not None:
            return token.value
        raise self.error("an integer or single-quoted string literal")

    def predicate(self) -> Predicate | None:
        if self.accept("WHERE") is None:
            return None
        column = self.identifier()
        operator = self.require("OP", "a comparison operator").value
        return Predicate(column, cast(Operator, operator), self.literal())

    def create(self) -> Statement:
        if self.accept("TABLE") is not None:
            table = self.identifier()
            self.require("(")
            columns: list[Column] = []
            while True:
                name = self.identifier()
                token = self.current
                if token.kind not in ("INT", "TEXT"):
                    raise self.error("INT or TEXT")
                self.position += 1
                columns.append(Column(name, cast(ColumnType, token.kind)))
                if self.accept(",") is None:
                    break
            self.require(")")
            return CreateTableStmt(TableSchema(table, tuple(columns)))
        if self.accept("INDEX") is not None:
            name = self.identifier()
            self.require("ON")
            table = self.identifier()
            self.require("(")
            column = self.identifier()
            self.require(")")
            return CreateIndexStmt(name, table, column)
        raise self.error("TABLE or INDEX")

    def insert(self) -> InsertStmt:
        self.require("INTO")
        table = self.identifier()
        self.require("VALUES")
        self.require("(")
        values = [self.literal()]
        while self.accept(",") is not None:
            values.append(self.literal())
        self.require(")")
        return InsertStmt(table, tuple(values))

    def select(self) -> SelectStmt:
        columns: tuple[str, ...] | None
        if self.accept("*") is not None:
            columns = None
        else:
            names = [self.identifier()]
            while self.accept(",") is not None:
                names.append(self.identifier())
            columns = tuple(names)
        self.require("FROM")
        table = self.identifier()
        return SelectStmt(table, columns, self.predicate())

    def update(self) -> UpdateStmt:
        table = self.identifier()
        self.require("SET")
        column = self.identifier()
        if self.current.kind != "OP" or self.current.value != "=":
            raise self.error("=")
        self.position += 1
        value = self.literal()
        return UpdateStmt(table, column, value, self.predicate())

    def delete(self) -> DeleteStmt:
        self.require("FROM")
        table = self.identifier()
        return DeleteStmt(table, self.predicate())

    def statement(self) -> Statement:
        token = self.current
        if token.kind not in ("CREATE", "INSERT", "SELECT", "UPDATE", "DELETE"):
            raise self.error("CREATE, INSERT, SELECT, UPDATE or DELETE")
        self.position += 1
        parsers = {
            "CREATE": self.create,
            "INSERT": self.insert,
            "SELECT": self.select,
            "UPDATE": self.update,
            "DELETE": self.delete,
        }
        statement = parsers[token.kind]()
        self.accept(";")
        self.require("EOF", "the end of a single SQL statement")
        return statement


def parse(sql: str) -> Statement:
    """Parse exactly one statement; leave schema and value checks to plan()."""
    return _Parser(tokenize(sql)).statement()
