"""Persistent equality hash index (member A).

One index covers a single column of a single table and maps a stable,
type-tagged key to the list of RIDs holding that key (duplicate keys are
allowed).  The whole index is held in memory and serialized as JSON to
``indexes/<table>__<column>.idx``.

Key encoding is stable and type-aware:
    integer 42 -> ``"I:42"``
    text    "42" -> ``"T:42"``
so two equal-looking values of different types never collide.  No Python
runtime/random hash is ever written to disk.
"""

from __future__ import annotations

import json
import os
import tempfile

RIDPair = tuple[int, int]


def encode_key(value: object) -> str:
    if isinstance(value, bool):  # bool is not a valid INT
        raise TypeError("boolean is not a valid index key")
    if isinstance(value, int):
        return f"I:{value}"
    if isinstance(value, str):
        return f"T:{value}"
    raise TypeError(f"unsupported index key type: {type(value).__name__}")


class HashIndex:
    def __init__(self, index_dir: str, table: str, column: str):
        self.table = table
        self.column = column
        self._path = os.path.join(index_dir, f"{table}__{column}.idx")
        # key -> list of [page_no, slot_no]
        self._entries: dict[str, list[list[int]]] = {}

    @property
    def path(self) -> str:
        return self._path

    def add(self, value: object, page_no: int, slot_no: int) -> None:
        key = encode_key(value)
        rids = self._entries.setdefault(key, [])
        pair = [page_no, slot_no]
        if pair not in rids:  # never duplicate an existing RID
            rids.append(pair)

    def remove(self, value: object, page_no: int, slot_no: int) -> bool:
        key = encode_key(value)
        rids = self._entries.get(key)
        if not rids:
            return False
        pair = [page_no, slot_no]
        if pair in rids:
            rids.remove(pair)
            if not rids:
                del self._entries[key]
            return True
        return False

    def lookup(self, value: object) -> list[RIDPair]:
        key = encode_key(value)
        rids = self._entries.get(key, [])
        return [(page, slot) for page, slot in rids]

    def save(self) -> None:
        """Atomically write the index to disk."""
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        payload = {
            "table": self.table,
            "column": self.column,
            "entries": self._entries,
        }
        fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(self._path), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def load(self) -> None:
        """Load the index from disk if the file exists."""
        if not os.path.exists(self._path):
            self._entries = {}
            return
        with open(self._path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        entries = payload.get("entries", {})
        # Normalize RID pairs to [int, int].
        normalized: dict[str, list[list[int]]] = {}
        for key, rids in entries.items():
            normalized[key] = [[int(p), int(s)] for p, s in rids]
        self._entries = normalized

    def delete_file(self) -> None:
        if os.path.exists(self._path):
            os.remove(self._path)
        self._entries = {}
