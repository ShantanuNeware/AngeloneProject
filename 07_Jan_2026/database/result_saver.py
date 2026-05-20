def save_results_to_db(df, table="strategy_results", db_path="database/trading.db"):
    import sqlite3
    import pandas as pd

    df = df.copy()
    # Convert all datetime columns and any pandas Timestamp objects in object columns to string for SQLite compatibility
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].astype(str)
        elif df[col].dtype == "object":
            # Convert any pandas Timestamp objects in object columns to string
            df[col] = df[col].apply(
                lambda x: (
                    x.isoformat()
                    if hasattr(x, "isoformat")
                    else str(x) if isinstance(x, (pd.Timestamp,)) else x
                )
            )
    with sqlite3.connect(db_path) as conn:
        df.to_sql(table, conn, if_exists="replace", index=False)
