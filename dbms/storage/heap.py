"""Record-level heap operations (member A).

Turns page-level buffer access into operations on encoded records: insert,
scan, fetch by RID, in-place update and delete.  All record bytes are already
encoded by the caller; the heap only deals with slots and RIDs.
"""

from __future__ import annotations

from ..types import StorageError
from . import page as page_mod
from .buffer import BufferPool
from .disk import DiskManager


class HeapTable:
    def __init__(self, disk: DiskManager, buffer_pool: BufferPool):
        self._disk = disk
        self._buffer = buffer_pool

    def _alive_frame(self, table: str, page_no: int, slot_no: int):
        frame = self._buffer.fetch_page(table, page_no)
        try:
            if page_mod.is_dead(frame.data, slot_no):
                raise StorageError(
                    f"RID (page={page_no}, slot={slot_no}) is deleted"
                )
        except page_mod.PageError as exc:
            raise StorageError(
                f"RID (page={page_no}, slot={slot_no}) does not exist"
            ) from exc
        return frame

    def insert_record(
        self, table: str, record: bytes
    ) -> tuple[int, int]:
        """Insert an encoded record, returning ``(page_no, slot_no)``."""
        count = self._disk.page_count(table)
        # Search from the last page backwards; use the first page that fits.
        for page_no in range(count - 1, -1, -1):
            frame = self._buffer.fetch_page(table, page_no)
            if page_mod.can_insert(frame.data, len(record)):
                slot_no = page_mod.insert_record(frame.data, record)
                self._buffer.mark_dirty(table, page_no)
                return page_no, slot_no

        # No existing page fits: allocate a new one.
        page_no, frame = self._buffer.new_page(table)
        slot_no = page_mod.insert_record(frame.data, record)
        self._buffer.mark_dirty(table, page_no)
        return page_no, slot_no

    def scan_records(self, table: str, column_count: int):
        """Yield ``(page_no, slot_no, values)`` for every alive record."""
        count = self._disk.page_count(table)
        for page_no in range(count):
            frame = self._buffer.fetch_page(table, page_no)
            # Materialize this page's rows before yielding, so the frame can
            # be evicted while the iterator is suspended.
            page_rows = list(page_mod.iter_alive_records(frame.data))
            for slot_no, record in page_rows:
                values = page_mod.decode_row(record, column_count)
                yield page_no, slot_no, values

    def get_record(
        self, table: str, page_no: int, slot_no: int, column_count: int
    ) -> tuple[object, ...]:
        frame = self._alive_frame(table, page_no, slot_no)
        record = page_mod.get_record(frame.data, slot_no)
        return page_mod.decode_row(record, column_count)

    def update_record(
        self, table: str, page_no: int, slot_no: int, record: bytes
    ) -> None:
        frame = self._alive_frame(table, page_no, slot_no)
        try:
            page_mod.overwrite_record(frame.data, slot_no, record)
        except page_mod.PageError as exc:
            raise StorageError(str(exc)) from exc
        self._buffer.mark_dirty(table, page_no)

    def delete_record(self, table: str, page_no: int, slot_no: int) -> None:
        frame = self._alive_frame(table, page_no, slot_no)
        page_mod.mark_dead(frame.data, slot_no)
        self._buffer.mark_dirty(table, page_no)
