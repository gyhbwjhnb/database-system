"""Fixed-size slotted pages and row/value encoding (member A).

Disk layout of one 4096-byte heap page::

    [ page header                                       ]
    [ slot directory (grows towards the end)            ]
    [ free space                                        ]
    [ records (grow backwards from the end of the page)  ]

Page header (4 bytes):
    uint16 slot_count      number of slot-directory entries
    uint16 free_boundary   start offset of the record area (moves backwards)

Slot-directory entry (5 bytes), one per slot:
    uint16 record_offset   offset of the record inside the page
    uint16 record_length   space originally allocated to the record
    uint8  flags           0 = alive, 1 = deleted

A record starts with a ``uint16`` total-length prefix followed by the
concatenation of self-describing field encodings in schema order.  INT fields
are ``tag 'I' + int64 big-endian``; TEXT fields are ``tag 'T' + uint16 byte
length + UTF-8 bytes``.  The tags make the field encoding unambiguous, and
the length prefix lets a record shrink (or grow, within its allocated slot)
without trailing garbage being read: decoding always trusts the prefix, not
the slot's physical length.
"""

from __future__ import annotations

import struct

PAGE_SIZE = 4096

# Page header.
_HEADER_SIZE = 4
_SLOT_COUNT_OFF = 0
_FREE_BOUNDARY_OFF = 2

# Slot-directory entry.
_SLOT_ENTRY_SIZE = 5
_SLOT_OFFSET_OFF = 0
_SLOT_LENGTH_OFF = 2
_SLOT_FLAGS_OFF = 4

FLAG_ALIVE = 0
FLAG_DEAD = 1

_TAG_INT = ord("I")
_TAG_TEXT = ord("T")

_MAX_TEXT_BYTES = 255


class PageError(Exception):
    """Raised for a structurally invalid page (internal use)."""


def encode_int(value: int) -> bytes:
    """Encode a signed 64-bit integer as a self-describing field."""
    return bytes([_TAG_INT]) + struct.pack(">q", value)


def encode_text(value: str) -> bytes:
    """Encode a text value as a self-describing field."""
    raw = value.encode("utf-8")
    return bytes([_TAG_TEXT]) + struct.pack(">H", len(raw)) + raw


def encode_value(value: object, col_type: str) -> bytes:
    """Encode one value according to the declared column type."""
    if col_type == "INT":
        return encode_int(value)  # type: ignore[arg-type]
    if col_type == "TEXT":
        return encode_text(value)  # type: ignore[arg-type]
    raise PageError(f"unknown column type: {col_type!r}")


def encode_row(values: tuple[object, ...], columns: tuple) -> bytes:
    """Serialize a full row in schema column order (with length prefix)."""
    body = b"".join(
        encode_value(value, column.type)
        for value, column in zip(values, columns)
    )
    return struct.pack(">H", len(body) + 2) + body


def _decode_field(buf: bytes, pos: int) -> tuple[object, int]:
    tag = buf[pos]
    pos += 1
    if tag == _TAG_INT:
        (value,) = struct.unpack_from(">q", buf, pos)
        return value, pos + 8
    if tag == _TAG_TEXT:
        (length,) = struct.unpack_from(">H", buf, pos)
        pos += 2
        raw = buf[pos : pos + length]
        return raw.decode("utf-8"), pos + length
    raise PageError(f"invalid field tag 0x{tag:02x} at offset {pos - 1}")


def decode_row(data: bytes, column_count: int) -> tuple[object, ...]:
    """Decode a record into ``column_count`` values.

    The slot may be physically larger than the current record (after an
    in-place shrink); the record's length prefix determines the valid range.
    """
    (total,) = struct.unpack_from(">H", data, 0)
    values: list[object] = []
    pos = 2
    for _ in range(column_count):
        value, pos = _decode_field(data, pos)
        values.append(value)
    if pos != total:
        raise PageError(
            f"record length prefix says {total} but {column_count} fields "
            f"decode to {pos} bytes"
        )
    return tuple(values)


def empty_page() -> bytearray:
    """Return a zeroed, initialized empty page."""
    page = bytearray(PAGE_SIZE)
    struct.pack_into("<H", page, _SLOT_COUNT_OFF, 0)
    struct.pack_into("<H", page, _FREE_BOUNDARY_OFF, PAGE_SIZE)
    return page


def slot_count(page: bytes) -> int:
    return struct.unpack_from("<H", page, _SLOT_COUNT_OFF)[0]


def _free_boundary(page: bytes) -> int:
    return struct.unpack_from("<H", page, _FREE_BOUNDARY_OFF)[0]


def free_space(page: bytes) -> int:
    """Bytes available between the slot directory and the record area."""
    used_by_directory = _HEADER_SIZE + slot_count(page) * _SLOT_ENTRY_SIZE
    return _free_boundary(page) - used_by_directory


def can_insert(page: bytes, record_length: int) -> bool:
    """Whether a new record plus its slot entry fit on this page."""
    return free_space(page) >= record_length + _SLOT_ENTRY_SIZE


def _slot_entry_pos(slot_no: int) -> int:
    return _HEADER_SIZE + slot_no * _SLOT_ENTRY_SIZE


def _read_slot(page: bytes, slot_no: int) -> tuple[int, int, int]:
    if slot_no < 0 or slot_no >= slot_count(page):
        raise PageError(f"slot {slot_no} out of range")
    pos = _slot_entry_pos(slot_no)
    offset = struct.unpack_from("<H", page, pos + _SLOT_OFFSET_OFF)[0]
    length = struct.unpack_from("<H", page, pos + _SLOT_LENGTH_OFF)[0]
    flags = page[pos + _SLOT_FLAGS_OFF]
    return offset, length, flags


def insert_record(page: bytearray, record: bytes) -> int:
    """Insert a record, returning its slot number."""
    record_length = len(record)
    if not can_insert(page, record_length):
        raise PageError("not enough free space on page")

    boundary = _free_boundary(page)
    new_boundary = boundary - record_length
    page[new_boundary:boundary] = record

    count = slot_count(page)
    entry_pos = _slot_entry_pos(count)
    struct.pack_into("<H", page, entry_pos + _SLOT_OFFSET_OFF, new_boundary)
    struct.pack_into("<H", page, entry_pos + _SLOT_LENGTH_OFF, record_length)
    page[entry_pos + _SLOT_FLAGS_OFF] = FLAG_ALIVE

    struct.pack_into("<H", page, _SLOT_COUNT_OFF, count + 1)
    struct.pack_into("<H", page, _FREE_BOUNDARY_OFF, new_boundary)
    return count


def get_record(page: bytes, slot_no: int) -> bytes:
    """Return the bytes currently stored in a slot (allocated length)."""
    offset, length, _ = _read_slot(page, slot_no)
    return bytes(page[offset : offset + length])


def slot_allocated_length(page: bytes, slot_no: int) -> int:
    _, length, _ = _read_slot(page, slot_no)
    return length


def is_dead(page: bytes, slot_no: int) -> bool:
    _, _, flags = _read_slot(page, slot_no)
    return flags == FLAG_DEAD


def mark_dead(page: bytearray, slot_no: int) -> None:
    """Mark a slot deleted. The slot/RID is kept stable."""
    _read_slot(page, slot_no)  # validates the slot
    pos = _slot_entry_pos(slot_no)
    page[pos + _SLOT_FLAGS_OFF] = FLAG_DEAD


def overwrite_record(page: bytearray, slot_no: int, record: bytes) -> None:
    """Overwrite a record in place.

    The new encoding must not exceed the space originally allocated to the
    slot, keeping the RID stable.
    """
    offset, length, _ = _read_slot(page, slot_no)
    if len(record) > length:
        raise PageError(
            f"updated record is {len(record)} bytes, slot only holds {length}"
        )
    page[offset : offset + len(record)] = record


def iter_alive_records(page: bytes):
    """Yield ``(slot_no, record_bytes)`` for every non-deleted slot."""
    for slot_no in range(slot_count(page)):
        offset, length, flags = _read_slot(page, slot_no)
        if flags == FLAG_ALIVE:
            yield slot_no, bytes(page[offset : offset + length])
