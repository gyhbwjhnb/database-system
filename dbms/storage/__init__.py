"""Storage, buffer pool and persistent indexes (member A).

Public entry point::

    from dbms.storage import StorageEngine
"""

from .engine import StorageEngine

__all__ = ["StorageEngine"]
