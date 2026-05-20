# db/connection.py
import sqlite3
import threading


class DBConnection:
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_connection(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = sqlite3.connect(
                        "database/trading.db", check_same_thread=False, timeout=30
                    )
                    cls._instance.execute("PRAGMA journal_mode=WAL")
                    cls._instance.execute("PRAGMA cache_size=-10000")
        return cls._instance
