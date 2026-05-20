# db/manager.py
from .connection import DBConnection
from .schema import TABLE_SCHEMAS
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)
conn = DBConnection.get_connection()


def clear_all_tables():
    with conn:
        for table in TABLE_SCHEMAS:
            conn.execute(f"DELETE FROM {table}")
            logger.info(f"🧹 Cleared table: {table}")


def cleanup_old_data():
    logger.info("🗑️ Cleaning up old data...")
    for table, meta in TABLE_SCHEMAS.items():
        days = meta.get("retention_days", 7)
        time_col = "datetime" if table == "historical" else "timestamp"
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with conn:
            conn.execute(f"DELETE FROM {table} WHERE {time_col} < ?", (cutoff,))
            logger.info(f"🧹 Purged old rows from {table}")
