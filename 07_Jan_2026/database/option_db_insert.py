# option_db_insert.py
# Handles insertion of data into per-option tables
import sqlite3
import logging
from option_schema import create_option_table

def insert_option_tick(conn, option_symbol, tick_data):
    """
    Insert a tick (or OHLCV bar) into the option's table.
    tick_data: dict with keys: timestamp, open, high, low, close, volume, source
    """
    table_name = create_option_table(conn, option_symbol)
    insert_sql = f'''
    INSERT INTO {table_name} (timestamp, open, high, low, close, volume, source)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    '''
    try:
        conn.execute(insert_sql, (
            tick_data["timestamp"],
            tick_data.get("open"),
            tick_data.get("high"),
            tick_data.get("low"),
            tick_data.get("close"),
            tick_data.get("volume"),
            tick_data.get("source", "realtime")
        ))
        conn.commit()
        logging.info(f"Inserted tick for {option_symbol} into {table_name}")
    except Exception as e:
        logging.error(f"Failed to insert tick for {option_symbol}: {e}")
