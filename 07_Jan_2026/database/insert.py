# db/insert.py
import pandas as pd
from datetime import datetime
from .connection import DBConnection

import logging

logger = logging.getLogger(__name__)
conn = DBConnection.get_connection()


def insert_historical(df: pd.DataFrame):
    if df.empty:
        logger.warning("⚠️ Empty DataFrame passed to insert_historical()")
        return

    # --- Normalize column names ---
    df = df.rename(
        columns={
            "DateTime": "datetime",
            "Date": "date",
            "Time": "time",
            "Symbol": "symbol",
            "Open": "Open",
            "High": "High",
            "Low": "Low",
            "Close": "Close",
        }
    )

    # --- Ensure datetime is timezone-naive (no +05:30) ---
    df["datetime"] = pd.to_datetime(df["datetime"], utc=False)
    if pd.api.types.is_datetime64tz_dtype(df["datetime"]):
        df["datetime"] = df["datetime"].dt.tz_localize(None)

    # --- Drop duplicates before inserting ---
    before = len(df)
    df = df.drop_duplicates(subset=["datetime", "symbol"], keep="last")
    dropped = before - len(df)
    if dropped > 0:
        logger.info(f"🧹 Dropped {dropped} duplicate rows before insert")

    inserted_count = 0
    skipped_count = 0

    # --- Insert into database ---
    with conn:
        for _, row in df.iterrows():
            try:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO historical 
                    (datetime, date, time, symbol, Open, High, Low, Close)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["datetime"].strftime("%Y-%m-%d %H:%M:%S"),  # no +05:30
                        row["date"],
                        row["time"],
                        row["symbol"],
                        row["Open"],
                        row["High"],
                        row["Low"],
                        row["Close"],
                    ),
                )

                if cur.rowcount == 0:
                    skipped_count += 1
                    logger.info(
                        f"⚠️ Skipped duplicate candle for {row['symbol']} at {row['datetime']}"
                    )
                else:
                    inserted_count += 1
                    logger.info(
                        f"✅ Inserted new candle for {row['symbol']} at {row['datetime']} | "
                        f"O:{row['Open']} H:{row['High']} L:{row['Low']} C:{row['Close']}"
                    )

            except Exception as e:
                logger.error(
                    f"❌ Failed to insert row for {row.get('symbol', 'unknown')}: {e}"
                )

    logger.info(
        f"📊 Historical insert summary → Inserted: {inserted_count}, Skipped: {skipped_count}, "
        f"Total processed: {len(df)}"
    )


def insert_realtime(data: dict):
    if data["close"] == 0:
        logger.debug("Ignoring zero LTP tick")
        return

    # Normalize key names: callers may provide 'timestamp' or 'datetime'
    ts = data.get("timestamp") or data.get("datetime")

    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO realtime (timestamp, symbol, open, high, low, close)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (
                ts,
                data["symbol"],
                data["open"],
                data["high"],
                data["low"],
                data["close"],
            ),
        )


def insert_signal(signal: dict):
    with conn:
        conn.execute(
            """
            INSERT INTO signals (timestamp, symbol, action, price, notes)
            VALUES (?, ?, ?, ?, ?)
        """,
            (
                signal.get("timestamp", datetime.now().isoformat()),
                signal["symbol"],
                signal["action"],
                signal["price"],
                signal.get("notes", ""),
            ),
        )


def insert_trades(trade):
    with conn:
        conn.execute(
            """
            INSERT INTO mock_trades (timestamp, symbol, action, price, qty, mode, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.get("timestamp"),
                trade.get("symbol"),
                trade.get("action"),
                trade.get("price"),
                trade.get("qty", None),  # None if not provided
                trade.get("mode", "TEST"),  # Default to TEST mode
                trade.get("notes", ""),
            ),
        )


def insert_pcr(pcr: float, prediction: str, timestamp: str, rows: list):
    import pandas as pd
    from datetime import datetime

    def scalar(x):
        return x.values[0] if isinstance(x, pd.Series) else x

    if timestamp is None:
        timestamp = datetime.now().isoformat()

    with conn:
        for row in rows:
            strike_val = scalar(row["strike"])

            conn.execute(
                """
                INSERT INTO pcr_data (
                    timestamp, strike,
                    symbol_CE, ltp_CE, oi_CE, vol_CE, delta_CE, gamma_CE, theta_CE, vega_CE, signal_CE,
                    symbol_PE, ltp_PE, oi_PE, vol_PE, delta_PE, gamma_PE, theta_PE, vega_PE, signal_PE,
                    pcr, prediction
                ) VALUES (?,?,?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    strike_val,
                    scalar(row["symbol_CE"]),
                    float(scalar(row["ltp_CE"])),
                    int(scalar(row["oi_CE"])),
                    int(scalar(row["vol_CE"])),
                    float(scalar(row["delta_CE"])),
                    float(scalar(row["gamma_CE"])),
                    float(scalar(row["theta_CE"])),
                    float(scalar(row["vega_CE"])),
                    scalar(row["signal_CE"]),
                    scalar(row["symbol_PE"]),
                    float(scalar(row["ltp_PE"])),
                    int(scalar(row["oi_PE"])),
                    int(scalar(row["vol_PE"])),
                    float(scalar(row["delta_PE"])),
                    float(scalar(row["gamma_PE"])),
                    float(scalar(row["theta_PE"])),
                    float(scalar(row["vega_PE"])),
                    scalar(row["signal_PE"]),
                    float(pcr),
                    prediction,
                ),
            )


def insert_trade(symbol, price, timestamp):
    with conn:
        conn.execute(
            """
            INSERT INTO trade_data (timestamp, symbol, price)
            VALUES (?, ?, ?)
            """,
            (
                timestamp,
                symbol,
                price,
            ),
        )


def insert_signal(symbol, signal_time, side):
    with conn:
        conn.execute(
            """
            INSERT INTO signals (timestamp, symbol, action)
            VALUES (?, ?, ?)
            """,
            (
                signal_time,
                symbol,
                side,
            ),
        )
