"""state/db.py — Thread-local SQLite connections with WAL and retry."""
import sqlite3
import threading
import time
import random
import os

_local = threading.local()
_db_path: str | None = None


def set_db_path(path: str):
    """Set the database path for this process."""
    global _db_path
    _db_path = path


def get_db_path() -> str:
    """Get the configured database path."""
    global _db_path
    if _db_path is None:
        _db_path = os.environ.get("DB_PATH", "razor402.db")
    return _db_path


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """
    Get a thread-local connection. Each thread gets its own connection.
    No module-level shared connection anywhere in the repo.
    """
    path = db_path or get_db_path()
    key = f"conn_{path}"

    conn = getattr(_local, key, None)
    if conn is not None:
        return conn

    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")

    setattr(_local, key, conn)
    return conn


def close_connection(db_path: str | None = None):
    """Close the thread-local connection if it exists."""
    path = db_path or get_db_path()
    key = f"conn_{path}"
    conn = getattr(_local, key, None)
    if conn is not None:
        conn.close()
        delattr(_local, key)


def with_txn(fn, db_path: str | None = None, retries: int = 5):
    """
    Execute fn(conn) inside BEGIN IMMEDIATE / COMMIT with retry on locked.
    Returns the result of fn.
    """
    conn = get_connection(db_path)
    last_err = None
    for attempt in range(retries):
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = fn(conn)
                conn.execute("COMMIT")
                return result
            except Exception:
                conn.execute("ROLLBACK")
                raise
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                last_err = e
                wait = (0.01 * (2 ** attempt)) + random.uniform(0, 0.01)
                time.sleep(wait)
                continue
            raise
    raise last_err  # type: ignore
