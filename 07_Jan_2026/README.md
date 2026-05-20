# NIFTY Options Trading System

## Overview

An automated algorithmic trading system for NIFTY index options that combines technical analysis, gamma wall detection, and real-time market data to execute profitable option trades.

## System Architecture

### Core Components

1. **StrategyData** (`strategydata.py`)
   - Primary signal generator
   - Monitors NIFTY 50 index with 3-minute candles
   - Generates CALL/PUT entry and exit signals
   - Controls overall market direction

2. **OptionMonitorRunner** (`OptionMonitorRunner.py`)
   - Execution engine for option trades
   - Manages individual option positions
   - Implements entry/exit logic with advanced filters (PCR, Gamma)
   - Operates within signal_type constraints

3. **OptionMonitor** (`OptionMonitor.py`)
   - Technical indicator calculations for specific Option Contracts
   - Signal generation (technical + gamma)
   - Enforces directional constraints

4. **OptionChainFetcher** (`optionchainfetcher.py`)
   - Real-time option chain data
   - Gamma wall detection
   - PCR (Put-Call Ratio) analysis
   - Strike selection logic

5. **Database Layer** (`database/`)
   - Centralized SQLite storage (`trading.db`) with WAL mode
   - Thread-safe access via `db_writer` and locking mechanism
   - Historical data, signals, and performance logging

## Signal Flow Architecture

```mermaid
graph TD
    A[StrategyData (NIFTY Index)] -->|Analyzes 3-min Candles| B{Signal Detected?}
    B -->|CALL| C[Start OptionMonitorRunner 'CALL']
    B -->|PUT| D[Start OptionMonitorRunner 'PUT']
    
    subgraph Execution_Engine [OptionMonitorRunner]
    C --> E[Select Strike & Validate PCR]
    D --> F[Select Strike & Validate PCR]
    E --> G[Loop: Monitor Option Price & Indicators]
    F --> H[Loop: Monitor Option Price & Indicators]
    
    G --> I{Generate Signal?}
    I -->|Technical + Gamma| J[Place Order]
    J --> K[Monitor Exit Conditions]
    K -->|Target/SL/Reversal| L[Exit Trade]
    L --> G
    
    end
    
    A -->|Global Exit Signal| M[Force Stop Monitors]
```

## Key Features

### 1. Directional Constraint System
**Problem Solved**: Prevents conflicting signals from different analysis methods.
**Implementation**:
- Monitors operate exclusively in assigned direction (CALL or PUT).
- Mismatched gamma signals are logged and ignored.

### 2. Gamma Wall Detection
**Purpose**: Identify market maker hedging zones.
**Mechanism**:
- Analyzes CE/PE gamma exposure.
- High confidence (>0.8) overrides technicals; Medium (0.6-0.8) confirms.

### 3. Reality Check Filter
**Purpose**: Prevent stale entries.
**Logic**:
- Reject if `LTP < Signal_Price * 0.998` (Price rejected/dropped).
- Skip if `LTP > Signal_Price * 1.005` (Price ran away).

### 4. PCR (Put-Call Ratio) Validation
**Logic (as implemented)**:
- **CALL Monitor**: Requires `PCR < 0.98`. (High PCR is treated as potentially overbought/bearish or distinct market regime).
- **PUT Monitor**: Requires `PCR > 1.02`. (Low PCR treated as bullish/oversold).
*(Note: This logic enforces trading against the crowd or specific regime detection)*.

## Technical Indicators Used

### Entry Signals
1. **HMA**: HMA7 > HMA14 (Fast > Slow = Bullish)
2. **ZLEMA**: ZLEMA7 > ZLEMA14
3. **UT Bot**: Signal == "BUY"
4. **McGinley**: Slope > 0 and ZLEMA7 > MCG14

### Exit Signals
1. **McGinley Reversal**: Significant drop in MCG5
2. **UT Bot**: Trailing stop breach or "SELL" signal
3. **Zone**: "SELL ZONE" or "NEUTRAL"

## Architecture Review & Health Check

### Strengths
1.  **Event-Driven Design**: `StrategyRunner` processes candles efficiently without blocking.
2.  **Thread Safety**: Explicit use of `threading.Lock` and `threading.Event` for clean concurrency and shutdown.
3.  **Database Concurrency**: SQLite in WAL mode with a dedicated writer queue (`db_writer`) minimizes lock contention.
4.  **Resilience**: Historical state checks allow the system to resume trades after a restart.

### Areas for Improvement
1.  **Logic Duplication**: `Strategy_Indicators` exists in both `Strategy.py` (Index) and `OptionMonitor.py` (Option). While intentional (different assets), logic updates must be synchronized manually, creating a maintenance risk.
2.  **Coupling**: `OptionMonitorRunner` has direct dependencies on massive `database` objects. Dependency injection could improve testability.
3.  **Config Management**: Hardcoded values (e.g., PCR thresholds 0.98/1.02) in `OptionMonitorRunner.py` should be moved to `config.py`.

## Installation & Setup

1.  **Prerequisites**: Python 3.9+, SQLite3, Shoonya API Credentials.
2.  **Install**: `pip install pandas numpy talib pushbullet.py`
3.  **Config**: Update `config.py` with credentials.
4.  **Run**: `python main.py`

## License
Proprietary - All rights reserved.
