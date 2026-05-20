import sqlite3
import logging
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, accuracy_score, mean_absolute_error
import joblib
import os

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ---------------------------
# Config
# ---------------------------
FEATURE_COLUMNS = [
    "MCG5",
    "MCG14",
    "HMA14",
    "HMA7",
    "ZLEMA7",
    "ZLEMA14",
    "ZLEMA21",
    "RSI",
    "RSI_SMA",
]

CROSS_PAIRS = [
    ("MCG5", "MCG14"),
    ("HMA7", "HMA14"),
    ("ZLEMA7", "ZLEMA21"),
    ("RSI", "RSI_SMA"),
]
MODEL_DIR = "models"
os.makedirs(MODEL_DIR, exist_ok=True)


# ---------------------------
# Crossover Feature
# ---------------------------
def detect_crossovers(df, fast_col, slow_col):
    """Returns 1 if fast crosses above slow, -1 if fast crosses below, 0 otherwise."""
    prev_fast = df[fast_col].shift(1)
    prev_slow = df[slow_col].shift(1)

    cross_up = (prev_fast <= prev_slow) & (df[fast_col] > df[slow_col])
    cross_down = (prev_fast >= prev_slow) & (df[fast_col] < df[slow_col])

    signal = pd.Series(0, index=df.index)
    signal[cross_up] = 1
    signal[cross_down] = -1
    return signal


def add_crossover_features(df):
    """Add crossover columns for each defined pair."""
    for fast, slow in CROSS_PAIRS:
        col_name = f"{fast}_{slow}_CROSS"
        df[col_name] = detect_crossovers(df, fast, slow)
    return df


# ---------------------------
# Train & Save Models
# ---------------------------
def train_crossover_models(df: pd.DataFrame, save_models: bool = True):
    """Train RF models for each crossover pair, using crossover signal as target."""
    df = add_crossover_features(df)
    trained_models = {}
    scalers = {}

    for fast, slow in CROSS_PAIRS:
        model_name = f"{fast}_{slow}"
        cross_col = f"{fast}_{slow}_CROSS"
        feature_cols = FEATURE_COLUMNS + [cross_col]

        df_clean = df.dropna(subset=feature_cols).copy()
        df_clean["CROSS_TARGET"] = df_clean[cross_col].map({1: "CALL", -1: "PUT"})
        df_clean = df_clean.dropna(subset=["CROSS_TARGET"])

        X = df_clean[FEATURE_COLUMNS]
        y = df_clean["CROSS_TARGET"]

        if y.value_counts().min() < 2:
            logger.warning(f"Skipping {model_name} due to insufficient class samples")
            continue

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        model = RandomForestClassifier(
            n_estimators=200, max_depth=10, random_state=42, n_jobs=-1
        )
        model.fit(X_train_scaled, y_train)

        y_pred = model.predict(X_test_scaled)
        print(f"\n--- {model_name} ---")
        print("Accuracy:", accuracy_score(y_test, y_pred))
        print(classification_report(y_test, y_pred, zero_division=0))

        if save_models:
            joblib.dump(model, os.path.join(MODEL_DIR, f"{model_name}_rf.pkl"))
            joblib.dump(scaler, os.path.join(MODEL_DIR, f"{model_name}_scaler.pkl"))

        trained_models[model_name] = model
        scalers[model_name] = scaler

    return trained_models, scalers


# ---------------------------
# Predict
# ---------------------------
def predict_new_crossover(df_new: pd.DataFrame):
    """Predict separately for each crossover pair."""
    df_new = add_crossover_features(df_new)
    predictions = {}

    for fast, slow in CROSS_PAIRS:
        model_name = f"{fast}_{slow}"
        model_path = os.path.join(MODEL_DIR, f"{model_name}_rf.pkl")
        scaler_path = os.path.join(MODEL_DIR, f"{model_name}_scaler.pkl")

        if not os.path.exists(model_path) or not os.path.exists(scaler_path):
            logger.warning(f"Skipping {model_name}: model/scaler not found.")
            continue

        model = joblib.load(model_path)
        scaler = joblib.load(scaler_path)

        feature_cols = FEATURE_COLUMNS + [f"{fast}_{slow}_CROSS"]
        X_new = df_new[feature_cols].copy()
        X_new = X_new[FEATURE_COLUMNS]  # use same columns as during training

        if X_new.empty:
            logger.warning(f"No valid input rows for {model_name}")
            continue

        X_scaled = scaler.transform(X_new)
        predictions[model_name] = model.predict(X_scaled)

    return predictions


# ---------------------------
# DB Utilities
# ---------------------------
def get_db_connection(db_path="database/trading.db"):
    conn = sqlite3.connect(db_path)
    logger.info(f"Connected to database at {db_path}")
    return conn


# ---------------------------
# MAIN SCRIPT
# ---------------------------
def main():
    db_path = "database/trading.db"
    query = "SELECT * FROM strategy_results"
    conn = get_db_connection(db_path)
    df = pd.read_sql_query(query, conn)

    if "DateTime" in df.columns:
        df["DateTime"] = pd.to_datetime(df["DateTime"], errors="coerce")

    # Train crossover models
    models, scalers = train_crossover_models(df)

    # Predict on latest row
    df_new = df.tail(1).copy()
    predictions = predict_new_crossover(df_new)
    print("\nPredicted Trade Actions:")
    for pair, pred in predictions.items():
        print(f"{pair}: {pred[0]}")

    # ---------------------------
    # Forecasting: Next Close Price
    # ---------------------------
    def train_forecasting_model(df: pd.DataFrame):
        df = df.copy()
        df["TARGET_NEXT_CLOSE"] = df["Close"].shift(-1)
        df = df.dropna(subset=FEATURE_COLUMNS + ["TARGET_NEXT_CLOSE"])

        X = df[FEATURE_COLUMNS]
        y = df["TARGET_NEXT_CLOSE"]

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        model = RandomForestRegressor(
            n_estimators=200, max_depth=10, random_state=42, n_jobs=-1
        )
        model.fit(X_train_scaled, y_train)
        y_pred = model.predict(X_test_scaled)
        print("\nForecasting Model MAE:", mean_absolute_error(y_test, y_pred))

        joblib.dump(model, os.path.join(MODEL_DIR, "forecast_rf.pkl"))
        joblib.dump(scaler, os.path.join(MODEL_DIR, "forecast_scaler.pkl"))

    # Train model
    train_forecasting_model(df)

    # Predict next close price
    df_latest = df.tail(1).copy()
    X_latest = df_latest[FEATURE_COLUMNS]

    if X_latest.empty:
        print("⚠️ Skipping forecasting — no valid rows available for prediction.")
        return

    scaler_path = os.path.join(MODEL_DIR, "forecast_scaler.pkl")
    model_path = os.path.join(MODEL_DIR, "forecast_rf.pkl")

    if os.path.exists(scaler_path) and os.path.exists(model_path):
        scaler = joblib.load(scaler_path)
        model = joblib.load(model_path)

        X_latest = pd.DataFrame(X_latest, columns=FEATURE_COLUMNS)
        X_latest_scaled = scaler.transform(X_latest)
        predicted_close_price = model.predict(X_latest_scaled)
        print("\nPredicted Next Close Price:", predicted_close_price[0])
    else:
        print("Forecasting model or scaler not found!")


if __name__ == "__main__":
    main()
