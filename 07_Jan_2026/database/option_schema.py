# option_schema.py
# Defines schema creation for per-option tables in the database
import sqlite3
import logging

def create_option_table(conn, option_symbol):
    """
    Create a table for a specific option symbol if it does not exist.
    Table name will be sanitized to avoid SQL injection.
    """
    # Sanitize table name: only allow alphanumeric and underscores
    table_name = f"option_{''.join(c if c.isalnum() else '_' for c in option_symbol)}"
    create_sql = f'''
    CREATE TABLE IF NOT EXISTS {table_name} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume INTEGER,
        source TEXT
    );
    '''
    try:
        conn.execute(create_sql)
        conn.commit()
        logging.info(f"Table created or exists: {table_name}")
    except Exception as e:
        logging.error(f"Failed to create table {table_name}: {e}")
    return table_name
