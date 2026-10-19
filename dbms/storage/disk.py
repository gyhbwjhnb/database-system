"""Raw heap-file I/O (member A).

The disk manager owns the open ``tables/<table>.heap`` file handles and reads
or writes fixed-size pages.  It does not understand records or caching; the
buffer pool sits on top of it.
"""

from __future__ import annotations

import os

from .page import PAGE_SIZE, empty_page


class DiskManager:
    def __init__(self, tables_dir: str):
        self._tables_dir = tables_dir
        os.makedirs(tables_dir, exist_ok=True)
        self._handles: dict[str, "os.PathLike[str]"] = {}

    def heap_path(self, table: str) -> str:
        return os.path.join(self._tables_dir, f"{table}.heap")

    def _open(self, table: str):
        handle = self._handles.get(table)
        if handle is None:
            path = self.heap_path(table)
            # Create the file first if missing, then open in random-access
            # 'r+b' mode: 'a+b' would force every write to the end of file
            # regardless of seek(), corrupting page numbers.
            if not os.path.exists(path):
                open(path, "wb").close()
            handle = open(path, "r+b", buffering=0)
            self._handles[table] = handle
        return handle

    def page_count(self, table: str) -> int:
        path = self.heap_path(table)
        if not os.path.exists(path):
            return 0
        size = os.path.getsize(path)
        if size % PAGE_SIZE != 0:
            raise OSError(
                f"heap file {path} has size {size}, not a multiple of "
                f"{PAGE_SIZE}"
            )
        return size // PAGE_SIZE

    def read_page(self, table: str, page_no: int) -> bytes:
        if page_no < 0:
            raise OSError(f"invalid page number {page_no}")
        handle = self._open(table)
        handle.seek(page_no * PAGE_SIZE)
        data = handle.read(PAGE_SIZE)
        if len(data) < PAGE_SIZE:
            # Reading beyond the end: return a fresh zeroed page.
            return bytes(empty_page())
        return data

    def write_page(self, table: str, page_no: int, data: bytes) -> None:
        if len(data) != PAGE_SIZE:
            raise ValueError("write_page expects exactly one page")
        handle = self._open(table)
        handle.seek(page_no * PAGE_SIZE)
        handle.write(data)
        handle.flush()

    def allocate_page(self, table: str) -> int:
        """Append a new empty page and return its page number."""
        page_no = self.page_count(table)
        self.write_page(table, page_no, bytes(empty_page()))
        return page_no

    def delete_heap(self, table: str) -> None:
        """Close and remove a heap file (used if a table is dropped)."""
        handle = self._handles.pop(table, None)
        if handle is not None:
            handle.close()
        path = self.heap_path(table)
        if os.path.exists(path):
            os.remove(path)

    def close(self) -> None:
        for handle in self._handles.values():
            handle.flush()
            handle.close()
        self._handles.clear()
