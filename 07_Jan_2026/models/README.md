# Machine Learning Models Architecture

This document describes the machine learning models used in the trading system. The `models/` directory contains the logic for training, saving, and predicting with Scikit-learn models. The system primarily uses Random Forest models for both classification and regression tasks.

## Core Components

### 1. `sklearn_model.py` (Classification & Forecasting)

-   **Role**: This module is responsible for training and using models that classify market conditions and forecast future price movements.
-   **Features**:
    -   **Crossover Classification**: It trains `RandomForestClassifier` models to predict trade direction (`CALL`/`PUT`) based on indicator crossovers.
        -   `CROSS_PAIRS`: Defines pairs of indicators (e.g., `("ZLEMA7", "ZLEMA21")`) to use for generating crossover signals.
        -   `train_crossover_models()`: Iterates through `CROSS_PAIRS`, trains a dedicated model for each, and saves the model (`.pkl`) and its associated `StandardScaler` to the `models/` directory.
    -   **Price Forecasting**: It trains a `RandomForestRegressor` model to predict the next candle's closing price.
        -   `train_forecasting_model()`: Uses the indicator `FEATURE_COLUMNS` to predict `Close` price of the next period. The trained model is saved as `forecast_rf.pkl`.

### 2. `xg_boost.py` (Unsupervised Clustering)

-   **Role**: This module uses unsupervised learning (K-Means) to group market conditions into distinct clusters.
-   **Features**:
    -   `train_unsupervised_clusters()`:
        1.  Trains a `KMeans` model on a wide set of indicator features.
        2.  Calculates the average future return for all data points within each generated cluster.
        3.  Assigns a qualitative label (`Bullish`, `Bearish`, `Neutral`) to each cluster based on its historical performance (e.g., clusters with the highest average future returns are labeled "Bullish").
        4.  Saves the trained `KMeans` model and the cluster labels to `unsupervised_cluster_model.pkl`.
    -   `predict_cluster()`: Loads the trained model and assigns a cluster label and type to new, unseen data.

## Model Training and Usage Flow

1.  **Data Source**: The models are trained using data from the `strategy_results` table in the database, which contains a rich history of indicator values.

2.  **Training Execution**:
    -   The `main()` function within `sklearn_model.py` and `xg_boost.py` can be run as standalone scripts to train (or retrain) the models.
    -   When run, they connect to the database, fetch the historical strategy data, train the respective models, and save the serialized `.pkl` files into the `models/` directory.

3.  **Prediction in Live Trading**:
    -   **`Strategy.py` / `option_monitor.py`**: These modules are the primary consumers of the trained models.
    -   **Loading**: On initialization, `OptionMonitor` calls `load_models_for_pairs()` to load all the classification models and scalers into memory.
    -   **Prediction**:
        -   During the `generate_trade_signals` process, the indicator data for the current candle is scaled and passed to the loaded models.
        -   The predictions from all crossover models are aggregated (using a `mode()` of the predictions) to produce a final `ML_Trade_Action`.
        -   This ML-driven signal is combined with technical rules to make the final trading decision.
        -   The forecasting model is used to predict the next closing price, which is logged for analysis but not directly used in the trading logic.
        -   The clustering model provides a "Cluster Type" (e.g., "Bullish") as an additional piece of context for the current market state.

## Saved Models

The `models/` directory will contain the following files after training:

-   `MCG5_MCG14_rf.pkl`, `MCG5_MCG14_scaler.pkl`
-   `HMA7_HMA14_rf.pkl`, `HMA7_HMA14_scaler.pkl`
-   `ZLEMA7_ZLEMA21_rf.pkl`, `ZLEMA7_ZLEMA21_scaler.pkl`
-   `RSI_RSI_SMA_rf.pkl`, `RSI_RSI_SMA_scaler.pkl`
-   `forecast_rf.pkl`, `forecast_scaler.pkl`
-   `unsupervised_cluster_model.pkl`