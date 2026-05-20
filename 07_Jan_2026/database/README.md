# Database Architecture

This document outlines the architecture of the database module, which is designed for robust, thread-safe, and non-blocking data persistence in a multi-threaded environment.

## Overview

The database system is built around two core principles:

1.  **Centralized Schema Management**: A single `TradingDB` class manages the SQLite database connection and schema, ensuring consistency across the application.
2.  **Asynchronous Writing**: To prevent slow database I/O from blocking time-sensitive operations (like strategy execution or tick processing), all write operations are offloaded to a dedicated background thread via a thread-safe queue.

## Core Components

### 1. `database.py` (The Database Manager)

-   **`TradingDB` Class**: This singleton class acts as the central point of interaction with the `trading.db` SQLite file.
-   **Responsibilities**:
    -   Manages a single, shared database connection (`check_same_thread=False`).
    -   Defines the schema for all application tables in the `TABLE_SCHEMAS` dictionary.
    -   Handles automatic schema creation and migration on startup, ensuring tables and columns are always up-to-date.
    -   Provides high-level, thread-safe methods for data access (e.g., `get_option_historical`, `update_option_monitor_results`).

### 2. `db_writer.py` (The Asynchronous Writer)

-   **Role**: Provides a non-blocking mechanism for writing data to the database.
-   **`enqueue(event)` function**: This is the public interface for all other modules. Any part of the application that needs to write data calls this function with a payload.
-   **Worker Thread**: A dedicated background thread (`_worker_loop`) continuously pulls data from a `queue.Queue`. It processes events in batches, writing them to the database efficiently.
-   **Benefit**: This decouples the trading logic from the database I/O. A strategy can enqueue a result in microseconds and continue its work, while the `db_writer` handles the slower process of committing it to disk.

### 3. `concurrent_fetch.py`
-   A utility module that provides a `parallel_map` function. It is used by `optionchainfetcher.py` to make multiple simultaneous API requests, speeding up the collection of option chain data that is later enqueued for database storage.

## Schema Overview

The `TradingDB` class manages the following key tables:

-   **`historical`**: Stores the main OHLCV data for the underlying index (e.g., NIFTY). This is loaded on startup.
-   **`option_historical`**: Stores historical OHLCV data for *individual option contracts*. Each `OptionMonitor` loads and maintains data here for its specific symbol.
-   **`option_monitor_results`**: A crucial log table that records the entire lifecycle of every `OptionMonitor` instance. It stores entry signals, exit signals, PnL, and status updates like "Monitor Started" or "Monitor Stopped".
-   **`pcr_data`**: Stores periodic snapshots of the Put-Call Ratio and its market prediction.
-   **`strategy_results`**: Stores the complete output DataFrame from the primary `StrategyRunner`, including all calculated indicators for the NIFTY index.
-   **`trades`**: A log of all trade orders placed by the system, including the symbol, price, quantity, and broker response.

## Data Flow

1.  **Initialization**: `main.py` initializes the `TradingDB` instance and calls `start_db_writer()` to launch the writer thread.
2.  **Data Enqueueing**:
    -   `StrategyRunner` enqueues its full indicator DataFrame by sending a `{"type": "strategy_results", ...}` payload.
    -   `OptionMonitor` enqueues its entry/exit/PnL data by sending a `{"type": "option_monitor_results", ...}` payload.
    -   `OptionChainRunner` enqueues PCR data by sending a `{"type": "pcr", ...}` payload.
    -   The `place_order` utility enqueues trade records by sending a `{"type": "trade", ...}` payload.
3.  **Data Writing**: The `db_writer` thread receives these payloads and uses the appropriate `TradingDB` methods to write the data to the correct tables.
4.  **Data Reading**: Components like `OptionMonitor` can directly call `db.get_option_historical()` to read data, as read operations are generally fast and do not need to be queued.