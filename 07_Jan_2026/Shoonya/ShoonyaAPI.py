from datetime import datetime, timedelta
import time
from config import NIFTY_Index_symbol
from ShoonyaAPI.LoginHelper import api
import pandas as pd
from database.insert import insert_historical


def get_time(time_string):
    return time.mktime(time.strptime(time_string, "%d-%m-%Y %H:%M:%S"))


def event_handler_quote_update(days, interval):
    now_dt = datetime.now()
    start_dt = now_dt - timedelta(days=days)
    now = now_dt.strftime("%d-%m-%Y %H:%M:%S")
    start_time = start_dt.strftime("%d-%m-%Y %H:%M:%S")
    start_secs = get_time(start_time)
    end_secs = get_time(now)

    df = api.get_time_price_series(
        exchange="NFO",
        token=NIFTY_Index_symbol,
        starttime=start_secs,
        endtime=end_secs,
        interval=interval,
    )

    if not df:
        print("⚠️ No data received from API")
        return pd.DataFrame()

    df = pd.DataFrame(df)
    df["time"] = pd.to_datetime(df["time"], dayfirst=True, errors="coerce")
    df = df.sort_values(by="time", ascending=True)
    df = df.dropna(subset=["time"])
    df = df.drop_duplicates(subset=["time"])

    if df.empty:
        print("⚠️ No valid data after processing")
        return pd.DataFrame()

    data_entry = {
        "DateTime": df["time"].dt.strftime("%Y-%m-%d %H:%M:%S"),
        "Date": df["time"].dt.strftime("%Y-%m-%d"),
        "Time": df["time"].dt.strftime("%H:%M:%S"),
        "Symbol": [NIFTY_Index_symbol] * len(df),
        "OPEN": df["into"],
        "HIGH": df["inth"],
        "LOW": df["intl"],
        "CLOSE": df["intc"],
    }
    data = pd.DataFrame(data_entry).sort_values("DateTime")
    insert_historical(data)
    return data
