# db/signals.py
import pandas as pd
from .connection import DBConnection

conn = DBConnection.get_connection()


def get_signals(hours: int = 24) -> pd.DataFrame:
    return pd.read_sql(
        f"""
        SELECT * FROM signals
        WHERE timestamp > datetime('now', '-{hours} hours')
        ORDER BY timestamp DESC
    """,
        conn,
    )
