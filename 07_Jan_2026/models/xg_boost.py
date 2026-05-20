import pandas as pd
import numpy as np
import joblib
import logging
import sqlite3
from pathlib import Path
from sklearn.cluster import KMeans

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


# -------------------------
# DATABASE CONNECTION
# -------------------------
def get_db_connection(db_path="database/trading.db"):
    conn = sqlite3.connect(db_path)
    logger.info(f"Connected to database at {db_path}")
    return conn


# -------------------------
# UNSUPERVISED TRAINER WITH CLUSTER LABELS
# -------------------------
def train_unsupervised_clusters(
    df: pd.DataFrame,
    n_clusters: int = 3,
    model_path: str = "models/unsupervised_cluster_model.pkl",
    forward_steps: int = 5,
):
    """
    Train K-Means on indicator features and assign cluster types
    (Bullish / Bearish / Neutral) based on future returns percentiles.
    """

    df = df.copy()
    features = [
        "Open",
        "High",
        "Low",
        "Close",
        "MCG5",
        "MCG14",
        "HMA14",
        "HMA3",
        "ADX",
        "ZLEMA7",
        "ZLEMA14",
        "ZLEMA21",
        "RSI",
        "RSI_SMA",
        "Magic_Trend_New",
        "UT_TrailingStop",
    ]
    features = [f for f in features if f in df.columns]
    if not features:
        logger.error("No features available for clustering.")
        return None

    df[features] = df[features].fillna(0)

    # Compute forward return
    df["Future_Close"] = df["Close"].shift(-forward_steps)
    df["Future_Return"] = (df["Future_Close"] - df["Close"]) / df["Close"]

    # Drop last rows with NaN future return
    df_clust = df.dropna(subset=features + ["Future_Return"]).copy()

    # Fit KMeans
    X = df_clust[features].values
    kmeans = KMeans(n_clusters=n_clusters, random_state=42)
    df_clust.loc[:, "Cluster_Label"] = kmeans.fit_predict(X)

    # Compute average return per cluster
    cluster_returns = df_clust.groupby("Cluster_Label")["Future_Return"].mean()

    # Assign cluster types based on percentiles
    cluster_labels = {}
    perc_33 = np.percentile(cluster_returns, 33)
    perc_66 = np.percentile(cluster_returns, 66)

    for cluster, avg_ret in cluster_returns.items():
        if avg_ret <= perc_33:
            cluster_labels[cluster] = "Bearish"
        elif avg_ret >= perc_66:
            cluster_labels[cluster] = "Bullish"
        else:
            cluster_labels[cluster] = "Neutral"

    df_clust.loc[:, "Cluster_Type"] = df_clust["Cluster_Label"].map(cluster_labels)

    # Save model
    Path(model_path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"model": kmeans, "features": features, "cluster_labels": cluster_labels},
        model_path,
    )
    logger.info(f"Unsupervised cluster model saved at: {model_path}")

    return df_clust[["DateTime", "Cluster_Label", "Cluster_Type"]]


# -------------------------
# PREDICTION FUNCTION
# -------------------------
def predict_cluster(
    df: pd.DataFrame, model_path="models/unsupervised_cluster_model.pkl"
):
    """
    Assign cluster labels to new data using trained KMeans model.
    """

    df = df.copy()
    model_data = joblib.load(model_path)

    # Detect missing model
    if not isinstance(model_data, dict) or "model" not in model_data:
        logger.warning("No trained clustering model found.")
        df["Cluster_Label"] = None
        df["Cluster_Type"] = None
        return df

    kmeans = model_data["model"]
    features = model_data["features"]
    cluster_labels_map = model_data["cluster_labels"]

    available_features = [f for f in features if f in df.columns]
    df[available_features] = df[available_features].fillna(0)

    X = df[available_features].values
    df.loc[:, "Cluster_Label"] = kmeans.predict(X)
    df.loc[:, "Cluster_Type"] = df["Cluster_Label"].map(cluster_labels_map)

    return df[["DateTime", "Cluster_Label", "Cluster_Type"]]


# -------------------------
# MAIN
# -------------------------
def main():
    db_path = "database/trading.db"
    query = "SELECT * FROM strategy_results"

    try:
        conn = get_db_connection(db_path)
        df = pd.read_sql_query(query, conn)
        conn.close()

        if "DateTime" in df.columns:
            df["DateTime"] = pd.to_datetime(df["DateTime"], errors="coerce")

        cluster_df = train_unsupervised_clusters(df, n_clusters=6)

        if cluster_df is not None and not cluster_df.empty:
            logger.info("Training complete and model saved successfully.")
        else:
            logger.warning("Training returned no clusters.")

    except Exception as e:
        logger.exception(f"Error during unsupervised training: {e}")


if __name__ == "__main__":
    main()
