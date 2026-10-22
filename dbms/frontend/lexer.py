"""Tokenizer for the deliberately small SQL language supported by the frontend."""

from __future__ import annotations

from dataclasses import dataclass

from dbms.types import SQLSyntaxError


_KEYWORDS = frozenset(
    {
        "CREATE", "TABLE", "INDEX", "ON", "INT", "TEXT", "INSERT", "INTO",
        "VALUES", "SELECT", "FROM", "WHERE", "UPDATE", "SET", "DELETE",
    }
)


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    offset: int
    line: int
    column: int


def _identifier_start(char: str) -> bool:
    return "a" <= char <= "z" or "A" <= char <= "Z" or char == "_"


def _digit(char: str) -> bool:
    return "0" <= char <= "9"


def tokenize(sql: str) -> tuple[Token, ...]:
    """Return tokens including EOF; reject comments and unsupported characters.

    Integer tokens keep their spelling so their range can be checked by the
    planner. String tokens contain their decoded value, including doubled quotes.
    """
    if not isinstance(sql, str):
        raise SQLSyntaxError("SQL input must be a string")

    tokens: list[Token] = []
    offset = 0
    line = 1
    column = 1
    length = len(sql)

    def advance() -> str:
        nonlocal offset, line, column
        char = sql[offset]
        offset += 1
        if char == "\n":
            line += 1
            column = 1
        else:
            column += 1
        return char

    while offset < length:
        char = sql[offset]
        if char.isspace():
            advance()
            continue

        start, start_line, start_column = offset, line, column
        if _identifier_start(char):
            advance()
            while offset < length and (
                _identifier_start(sql[offset]) or _digit(sql[offset])
            ):
                advance()
            spelling = sql[start:offset]
            upper = spelling.upper()
            kind = upper if upper in _KEYWORDS else "IDENT"
            value = upper if upper in _KEYWORDS else spelling.lower()
        elif _digit(char) or (
            char == "-" and offset + 1 < length and _digit(sql[offset + 1])
        ):
            advance()
            while offset < length and _digit(sql[offset]):
                advance()
            kind, value = "INTEGER", sql[start:offset]
        elif char == "'":
            advance()
            decoded: list[str] = []
            while True:
                if offset == length:
                    raise SQLSyntaxError(
                        f"Unterminated string at line {start_line}, "
                        f"column {start_column} (offset {start})"
                    )
                current = advance()
                if current != "'":
                    decoded.append(current)
                elif offset < length and sql[offset] == "'":
                    advance()
                    decoded.append("'")
                else:
                    break
            kind, value = "STRING", "".join(decoded)
        elif char in "(),;*":
            kind = value = advance()
        elif char in "=!<>":
            value = advance()
            if offset < length and sql[offset] == "=" and char in "!<>":
                value += advance()
            if value == "!":
                raise SQLSyntaxError(
                    f"Expected != at line {start_line}, "
                    f"column {start_column} (offset {start})"
                )
            kind = "OP"
        else:
            raise SQLSyntaxError(
                f"Unsupported character {char!r} at line {start_line}, "
                f"column {start_column} (offset {start})"
            )
        tokens.append(Token(kind, value, start, start_line, start_column))

    tokens.append(Token("EOF", "", offset, line, column))
    return tuple(tokens)
