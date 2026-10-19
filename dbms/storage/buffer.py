"""LRU buffer-pool manager (member A).

Caches heap pages keyed by ``(table, page_no)``.  The most recently used page
is kept at the end of the ordered dictionary; the least recently used page is
evicted first.  Dirty pages are written back before eviction and on
``flush``.  The counters ``hits``, ``misses``, ``evictions`` and
``dirty_flushes`` back the observable ``BufferStats``.
"""

from __future__ import annotations

from collections import OrderedDict

from . import page as page_mod
from .disk import DiskManager


class Frame:
    """One buffered page."""

    __slots__ = ("data", "dirty")

    def __init__(self, data: bytearray, dirty: bool = False):
        self.data = data
        self.dirty = dirty


class BufferPool:
    def __init__(self, disk: DiskManager, capacity: int = 64):
        if capacity < 1:
            raise ValueError("buffer capacity must be at least 1 page")
        self._disk = disk
        self._capacity = capacity
        self._frames: "OrderedDict[tuple[str, int], Frame]" = OrderedDict()
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.dirty_flushes = 0

    # -- internal helpers -------------------------------------------------

    def _evict_lru(self) -> None:
        (table, page_no), frame = self._frames.popitem(last=False)
        if frame.dirty:
            self._disk.write_page(table, page_no, bytes(frame.data))
            frame.dirty = False
            self.dirty_flushes += 1
        self.evictions += 1

    def _make_room(self) -> None:
        while len(self._frames) >= self._capacity:
            self._evict_lru()

    # -- public API -------------------------------------------------------

    def fetch_page(self, table: str, page_no: int) -> Frame:
        """Return the frame for a page, loading it from disk on a miss."""
        key = (table, page_no)
        frame = self._frames.get(key)
        if frame is not None:
            self._frames.move_to_end(key)
            self.hits += 1
            return frame

        self.misses += 1
        self._make_room()
        data = bytearray(self._disk.read_page(table, page_no))
        frame = Frame(data, dirty=False)
        self._frames[key] = frame
        return frame

    def new_page(self, table: str) -> tuple[int, Frame]:
        """Allocate a new empty page on disk and buffer it."""
        self._make_room()
        page_no = self._disk.allocate_page(table)
        frame = Frame(bytearray(page_mod.empty_page()), dirty=False)
        self._frames[(table, page_no)] = frame
        return page_no, frame

    def mark_dirty(self, table: str, page_no: int) -> None:
        frame = self._frames.get((table, page_no))
        if frame is not None:
            frame.dirty = True

    def flush_table(self, table: str) -> None:
        """Write back all dirty pages of one table."""
        for (tbl, page_no), frame in self._frames.items():
            if tbl == table and frame.dirty:
                self._disk.write_page(tbl, page_no, bytes(frame.data))
                frame.dirty = False
                self.dirty_flushes += 1

    def flush_all(self) -> None:
        """Write back every dirty page."""
        for (table, page_no), frame in self._frames.items():
            if frame.dirty:
                self._disk.write_page(table, page_no, bytes(frame.data))
                frame.dirty = False
                self.dirty_flushes += 1

    def stats(self) -> tuple[int, int, int, int]:
        return (self.hits, self.misses, self.evictions, self.dirty_flushes)

    def cached_pages(self) -> int:
        return len(self._frames)
