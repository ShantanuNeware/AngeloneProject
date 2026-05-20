"""
Refactored Trading System - Continuous Live Trading Entry Point

Features:
✓ Continuous trading loop (real-time market analysis)
✓ Periodic data fetching (every N seconds)
✓ Event-driven signal generation
✓ Type-safe models with risk-reward validation
✓ Graceful shutdown (Ctrl+C)
✓ Support for stock AND option trading

Usage:
  python tradingsystem/main_refactored.py
  
Press Ctrl+C to stop trading gracefully
"""

import sys
from pathlib import Path

# Add project root to sys.path to allow absolute imports of the 'tradingsystem' package
project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import json
import time
import signal
from datetime import datetime, timedelta
import argparse
import os
from typing import List, Optional
import threading

# Models
from tradingsystem.models import (
    Candle, Signal, SignalType, MarketRegime
)
from tradingsystem.models.option import OptionChain

# Core components
from tradingsystem.core import (
    RegimeManager, StrategyManager, StrategyManagerConfig, SyncEventBus, ExecutionManager, SignalGeneratedEvent
)

# Strategies
from tradingsystem.strategies import (
    MAStrategy, RSIStrategy, BBStrategy, OptionSellStrategy,
)

# Broker & Data
from tradingsystem.broker.angelone_session import AngelOneSession
from tradingsystem.broker.order_manager import OrderManager
from tradingsystem.broker.angelone_fetcher import AngelOneFetcher
from tradingsystem.data.db import MarketDB
from tradingsystem.config.loader import load_config
from tradingsystem.broker.websocket import WebSocketHandler
from tradingsystem.utils.realtime_aggregator import RealtimeAggregator
from tradingsystem.data.db_writer import DBWriter
from tradingsystem.strategies.Strategy import StrategyRunner
from tradingsystem.analytics.option_chain import (
    detect_gamma_burst,
    detect_liquidity_pools,
    select_best_option,
)


# =====================================================================
# TRADING ENGINE - CONTINUOUS EXECUTION
# =====================================================================

class TradingEngine:
    """Main trading engine with continuous execution"""

    def __init__(self, config: dict, agent_mode: str = "monitor", confirm_file: Optional[str] = None, agent_approve: bool = False):
        self.config = config
        self.agent_mode = agent_mode
        self.confirm_file = confirm_file
        self.agent_approve = agent_approve
        self.is_running = True
        self.cycle_count = 0
        self.last_fetch_time = None
        self.fetch_interval = config.get("poll_interval_seconds", 60)

        # Core components
        self.event_bus = SyncEventBus()
        self.regime_manager = RegimeManager(
            trend_threshold=25.0,
            range_threshold=20.0,
            volatility_threshold=2.5
        )
        self.strategy_manager = None
        self.db = None
        self.fetcher = None
        self.client = None
        self.order_manager = None
        self.execution_manager = None
        self.ws = None
        self.db_writer = None
        self.strategy_runner = None
        self.realtime_aggregator = None
        self._option_updater_thread = None
        self._realtime_strategy_lock = threading.Lock()
        self._last_realtime_signal_key = None

        # Candle history (cache)
        self.candles: List[Candle] = []
        self.current_option_chain: Optional[OptionChain] = None
        self.open_positions: dict = {}
        
    def setup(self) -> bool:
        """Initialize all components"""
        print("\n" + "=" * 70)
        print("🚀 REFACTORED TRADING SYSTEM - CONTINUOUS LIVE TRADING")
        print("=" * 70)
        
        try:
            # 1. Initialize components
            print("\n[SETUP] Initializing core components...")
            
            self.strategy_manager = StrategyManager(
                config=StrategyManagerConfig(
                    regime_manager=self.regime_manager
                )
            )
            print("  ✓ Strategy Manager initialized")
            
            # 2. Configure strategies (register available classes and load from config)
            print("\n[SETUP] Configuring strategies...")

            # Register strategy classes (registry used to instantiate from config)
            self.strategy_manager.register_strategy("ma_strategy", MAStrategy)
            self.strategy_manager.register_strategy("rsi_strategy", RSIStrategy)
            self.strategy_manager.register_strategy("bb_strategy", BBStrategy)
            self.strategy_manager.register_strategy("option_sell_strategy", OptionSellStrategy)

            # Load active strategies from config (tolerant shapes)
            try:
                strategy_cfg = self.config.get("strategy", {})
                self.strategy_manager.load_strategies_from_config(strategy_cfg)
                active = list(self.strategy_manager.strategies.keys())
                if active:
                    print(f"  ✓ Loaded strategies: {', '.join(active)}")
                else:
                    # Fallback: register defaults
                    self.strategy_manager.add_strategy("ma_strategy", MAStrategy("ma_strategy"))
                    print("  ✓ Fallback MA Crossover Strategy (TRENDING)")
            except Exception:
                # On error, register default strategy
                self.strategy_manager.add_strategy("ma_strategy", MAStrategy("ma_strategy"))
                print("  ✓ Fallback MA Crossover Strategy (TRENDING)")
            
            # Get broker config
            broker_config = self.config["brokers"]["angleone"]
            
            # 3. Authenticate with broker
            print("\n[SETUP] Authenticating with broker...")
            
            session = AngelOneSession(
                api_key=broker_config["api_key"],
                client_code=broker_config["username"],
                password=broker_config["password"],
                totp_secret=broker_config["factor2"]
            )
            
            self.client = session.login()
            if not self.client:
                print("  ✗ Login failed")
                return False
            
            print("  ✓ Login successful")
            
            # 4. Initialize database & fetcher
            print("\n[SETUP] Initializing database & data fetcher...")
            
            self.db = MarketDB(config=self.config)
            self.fetcher = AngelOneFetcher(self.client)
            self.strategy_runner = StrategyRunner(self.strategy_manager, self.db, self.db_writer)
            # Background DB writer and realtime aggregator
            try:
                self.db_writer = DBWriter()
                self.db_writer.start()
                self.strategy_runner.db_writer = self.db_writer
                self.realtime_aggregator = RealtimeAggregator(
                    self.db,
                    timeframe_minutes=int(self.config.get("strategy", {}).get("timeframe_minutes", 1)),
                )
                self.realtime_aggregator.add_candle_callback(self._on_realtime_candle_update)

                # Websocket handler for real-time ticks
                self.ws = WebSocketHandler(self.client, debug=False)
                # Register aggregator to receive ticks
                self.ws.add_tick_callback(self.realtime_aggregator.on_tick)
                tokens = [broker_config.get("NIFTY_token", "99926000")]
                try:
                    self.ws.subscribe_tokens(tokens, exchange=broker_config.get("exchange", "NSE"))
                except Exception:
                    pass
            except Exception:
                # Non-fatal: continue without background writer or websocket
                pass
            
            # 5. Initialize Execution
            dry_run_flag = (self.agent_mode == 'dry-run')
            self.order_manager = OrderManager(self.client, dry_run=dry_run_flag)
            self.execution_manager = ExecutionManager(self.event_bus, self.order_manager, self.config)
            print("  ✓ Execution Manager initialized")
            
            print("  ✓ Database initialized")
            print("  ✓ Data fetcher initialized")
            
            # 5. Initial data load
            print("\n[SETUP] Loading initial market data...")
            if not self._fetch_and_process_data():
                print("  ✗ Failed to load initial data")
                return False
            
            print("  ✓ Initial data loaded")
            
            print("\n" + "=" * 70)
            print("✓ SETUP COMPLETE - Starting continuous trading loop")
            print("=" * 70)
            print(f"\nTrading Parameters:")
            print(f"  Fetch Interval: {self.fetch_interval} seconds")
            print(f"  Active Strategies: {len(self.strategy_manager.strategies)}")
            print(f"  Timeframe: {self.config['strategy'].get('timeframe', '1m')}")
            print(f"\nPress Ctrl+C to stop trading\n")
            
            return True
            
        except Exception as e:
            print(f"  ✗ Setup error: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _on_realtime_candle_update(self, token: str, candle_row: dict, is_closed: bool) -> None:
        """Run strategy from candles table after every websocket candle update."""
        if not self.strategy_runner:
            return

        if not self._realtime_strategy_lock.acquire(blocking=False):
            return

        try:
            strategy_cfg = self.config.get("strategy", {})
            result = self.strategy_runner.run_live_from_db(
                token=token,
                limit=int(strategy_cfg.get("live_candle_limit", 500)),
                symbol=strategy_cfg.get("symbol", "NIFTY"),
                timeframe=strategy_cfg.get("timeframe", "1m"),
                persist_indicators=True,
            )

            self.candles = result.get("candles", self.candles)[-500:]
            self.update_heartbeat("running")

            signal_obj = result.get("signal")
            if not signal_obj:
                return

            signal_key = (
                candle_row.get("timestamp"),
                getattr(getattr(signal_obj, "signal_type", None), "value", None),
                getattr(signal_obj, "strategy_name", None),
            )
            if signal_key == self._last_realtime_signal_key:
                return

            self._last_realtime_signal_key = signal_key
            print(
                f"  LIVE SIGNAL {signal_obj.signal_type.value.upper()} "
                f"@ {signal_obj.price:.2f} ({result.get('regime')}, "
                f"ADX {result.get('adx', 0):.2f}, ATR {result.get('atr', 0):.4f})"
            )
            self.event_bus.publish(SignalGeneratedEvent(signal=signal_obj))

        except Exception as e:
            print(f"  Realtime strategy error: {e}")
        finally:
            self._realtime_strategy_lock.release()
    
    def _fetch_and_process_data(self) -> bool:
        """Fetch latest candles and process"""
        try:
            broker_config = self.config["brokers"]["angleone"]
            strategy_config = self.config["strategy"]
            
            end = datetime.now()
            # Determine fetch window: prefer 'data_fetch_days' if provided,
            # otherwise use 'data_fetch_minutes' (default 60 minutes)
            data_fetch_days = strategy_config.get('data_fetch_days')
            if data_fetch_days is not None:
                try:
                    start = end - timedelta(days=int(data_fetch_days))
                except Exception:
                    start = end - timedelta(days=30)
            else:
                minutes = strategy_config.get('data_fetch_minutes', 60)
                try:
                    start = end - timedelta(minutes=int(minutes))
                except Exception:
                    start = end - timedelta(minutes=60)
            
            token = broker_config.get("NIFTY_token", "99926000")
            timeframe = strategy_config.get("timeframe", "1m")
            
            print(f"    Attempting to fetch: Token={token}, Timeframe={timeframe}, From={start.isoformat()} To={end.isoformat()}")
            
            # Fetch raw candle data
            candles_data = self.fetcher.fetch(
                token=token,
                exchange="NSE",
                interval="1m",
                start=end - timedelta(days=30),  # Fetch last 30 days of data for initial load
                end=end
            )
            print(f"    Raw data fetch complete, processing results...")    
            
            if not candles_data:
                print(f"    ⚠️  No data returned from broker")
                return False
            
            print(f"    ✓ Got {len(candles_data)} raw candles from broker")
            
            # Convert to typed models
            new_candles: List[Candle] = []
            for i, candle_data in enumerate(candles_data):
                try:
                    candle = Candle(
                        symbol="NIFTY",
                        timeframe=timeframe,
                        timestamp=datetime.fromisoformat(candle_data[0].replace('Z', '+00:00')),
                        open=float(candle_data[1]),
                        high=float(candle_data[2]),
                        low=float(candle_data[3]),
                        close=float(candle_data[4]),
                        volume=int(candle_data[5]) if len(candle_data) > 5 else 0
                    )
                    new_candles.append(candle)
                except (ValueError, IndexError) as e:
                    if i == 0:
                        print(f"    Warning parsing candle {i}: {e}, sample: {candle_data}")
                    continue
            
            if not new_candles:
                print(f"    ⚠️  Could not parse any candles from data")
                return False
            
            print(f"    ✓ Converted {len(new_candles)} candles to models")
            
            # Update cache (keep last 500 candles)
            self.candles = new_candles[-500:]
            
            # Store in database
            if self.cycle_count == 0:
                self.db.delete_candles()
            self.db.insert_candles(candles_data, token)
            
            self.last_fetch_time = datetime.now()
            self.update_heartbeat("running")
            
            # Fetch Option Chain if using OptionSellStrategy
            if self.config["strategy"].get("name") == "OptionSellStrategy":
                print(f"    📥 Fetching Option Chain for {token}...")
                expiry = self.config["strategy"].get("option_expiry", "")
                underlying_price = self.candles[-1].close if self.candles else 0.0
                
                self.current_option_chain = self.fetcher.get_parsed_option_chain(
                    symbol="NIFTY", 
                    expiry_date=expiry,
                    underlying_price=underlying_price
                )
                if self.current_option_chain:
                    print(f"    ✓ Loaded option chain with {len(self.current_option_chain.call_contracts)} calls")

            # Start background option chain updater thread
            try:
                def _option_updater():
                    interval = int(self.config.get("strategy", {}).get("option_chain_update_seconds", 300))
                    while self.is_running:
                        try:
                            expiry = self.config["strategy"].get("option_expiry", "")
                            if expiry:
                                oc = self.fetcher.get_parsed_option_chain("NIFTY", expiry, underlying_price=(self.candles[-1].close if self.candles else 0.0))
                                if oc and self.db_writer:
                                    table = f"option_{oc.underlying_symbol}_{oc.expiry_date.replace('-', '')}"
                                    try:
                                        self.db.create_option_table(table)
                                    except Exception:
                                        pass
                                    # enqueue option rows
                                    for c in oc.call_contracts + oc.put_contracts:
                                        row = {
                                            "timestamp": c.timestamp.isoformat() if hasattr(c.timestamp, "isoformat") else str(c.timestamp),
                                            "token": c.token,
                                            "strike": c.strike_price,
                                            "option_type": c.option_type.value if hasattr(c.option_type, "value") else str(c.option_type),
                                            "bid": c.bid,
                                            "ask": c.ask,
                                            "ltp": c.last_traded_price,
                                            "volume": c.volume,
                                            "oi": c.open_interest,
                                            "iv": c.iv,
                                            "delta": c.delta,
                                            "gamma": c.gamma,
                                            "theta": c.theta,
                                            "vega": c.vega,
                                        }
                                        try:
                                            self.db_writer.enqueue(self.db.insert_option_tick, table, row)
                                        except Exception:
                                            pass

                                # Optional analytics (non-blocking)
                                try:
                                    if oc:
                                        _ = detect_gamma_burst(oc)
                                        _ = detect_liquidity_pools(oc)
                                        _ = select_best_option(oc, side="call")
                                except Exception:
                                    pass

                        except Exception:
                            pass
                        finally:
                            time.sleep(interval)

                self._option_updater_thread = threading.Thread(target=_option_updater, daemon=True)
                self._option_updater_thread.start()
            except Exception:
                pass
            
            return True
            
        except Exception as e:
            print(f"  ✗ Data fetch error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def update_heartbeat(self, status: str):
        """Update heartbeat file to signal the system is running"""
        heartbeat_path = "heartbeat.json"
        data = {
            "status": status,
            "last_heartbeat": datetime.now().isoformat(),
            "cycle_count": self.cycle_count,
            "active_positions": len(self.open_positions),
            "last_price": self.candles[-1].close if self.candles else None,
            "agent_mode": self.agent_mode,
            "agent_confirmed": self.is_agent_confirmed()
        }
        try:
            with open(heartbeat_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"  ⚠️  Heartbeat update failed: {e}")

    def is_agent_confirmed(self) -> bool:
        """Return True if live confirmation is present (sentinel file, env, or approve flag)"""
        # Explicit approval flag
        if getattr(self, 'agent_approve', False):
            return True

        # Sentinel file check
        if getattr(self, 'confirm_file', None):
            try:
                return Path(self.confirm_file).exists()
            except Exception:
                return False

        # Environment variable
        env_val = os.environ.get('CONFIRM_ORDERS', '')
        if str(env_val).lower() in ('1', 'true', 'yes'):
            return True

        return False

    def run_analysis_cycle(self):
        """Run one complete analysis cycle"""
        try:
            if not self.candles or len(self.candles) < 14:
                return None
            
            # Calculate indicators
            recent_closes = [c.close for c in self.candles[-14:]]
            atr_values = [c.true_range for c in self.candles[-14:]]
            
            adx = 30 if recent_closes[-1] > sum(recent_closes) / len(recent_closes) else 15
            atr = sum(atr_values) / len(atr_values)
            close_price = self.candles[-1].close
            
            # Detect regime
            regime = self.regime_manager.detect_regime(
                candles=self.candles,
                adx_value=adx,
                atr_value=atr,
                close_price=close_price
            )
            
            # Analyze market
            signal = self.strategy_manager.analyze_market(
                candles=self.candles[-100:],
                current_regime=regime,
                adx_value=adx,
                atr_value=atr
            )
            
            return {
                "timestamp": datetime.now(),
                "price": close_price,
                "regime": regime.value,
                "adx": adx,
                "atr": atr,
                "signal": signal,
            }
            
        except Exception as e:
            print(f"  ✗ Analysis error: {e}")
            return None
    
    def run_continuous(self):
        """Main continuous trading loop"""
        
        try:
            while self.is_running:
                self.cycle_count += 1
                current_time = datetime.now()
                
                # Fetch data at specified intervals
                if (self.last_fetch_time is None or 
                    (current_time - self.last_fetch_time).seconds >= self.fetch_interval):
                    
                    print(f"\n[CYCLE {self.cycle_count}] {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    print("-" * 70)
                    print(f"  📥 Fetching data (interval: {self.fetch_interval}s)...")
                    
                    if not self._fetch_and_process_data():
                        print("  ⚠️  Data fetch failed, skipping this cycle")
                        time.sleep(5)
                        continue
                    
                    print(f"  ✓ Fetched {len(self.candles)} candles")
                    
                    # Run analysis
                    print("  🧠 Running strategy analysis...")
                    result = self.run_analysis_cycle()
                    
                    if result:
                        latest_candle = self.candles[-1]
                        self.db.save_strategy_state({
                            "timestamp": latest_candle.timestamp,
                            "Symbol": latest_candle.symbol,
                            "Open": latest_candle.open,
                            "High": latest_candle.high,
                            "Low": latest_candle.low,
                            "Close": latest_candle.close,
                            "Volume": latest_candle.volume,
                            "ADX": result["adx"],
                            "ATR": result["atr"],
                            "Strategy_State": result["regime"],
                            "Trade_Action": (
                                result["signal"].signal_type.value
                                if result["signal"]
                                else "hold"
                            ),
                            **(result["signal"].indicator_values if result["signal"] else {}),
                        })

                        print(f"    Price: {result['price']:.2f}")
                        print(f"    Regime: {result['regime'].upper()}")
                        print(f"    ADX: {result['adx']:.2f} | ATR: {result['atr']:.4f}")
                        
                        if result["signal"]:
                            sig = result["signal"]
                            print(f"\n  🎯 SIGNAL GENERATED!")
                            print(f"     Strategy: {sig.strategy_name}")
                            print(f"     Type: {sig.signal_type.value.upper()}")
                            print(f"     Price: {sig.price:.2f}")
                            print(f"     Confidence: {sig.confidence:.1%}")
                            print(f"     Regime: {sig.regime}")
                            print(f"     Reason: {sig.reason}")

                            self.db.save_signal(sig)
                            
                            # Publish event for ExecutionManager to handle
                            self.event_bus.publish(SignalGeneratedEvent(signal=sig))
                        else:
                            print("  ℹ️  No signal generated this cycle")
                
                # Wait before next check (avoid busy waiting)
                time.sleep(1)
        
        except KeyboardInterrupt:
            print("\n\n⏸️  Received interrupt signal, shutting down gracefully...")
        except Exception as e:
            print(f"\n❌ Fatal error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Clean shutdown"""
        print("\n[CLEANUP] Shutting down...")
        
        try:
            if getattr(self, "ws", None):
                try:
                    self.ws.disconnect()
                except Exception:
                    pass

            if getattr(self, "realtime_aggregator", None):
                try:
                    self.realtime_aggregator.flush_all()
                except Exception:
                    pass

            if getattr(self, "db_writer", None):
                try:
                    self.db_writer.stop()
                except Exception:
                    pass

            if self.db:
                self.db.close()
                print("  ✓ Database closed")
            
            self.update_heartbeat("stopped")
            
            print(f"\n📊 Trading Summary:")
            print(f"  Cycles completed: {self.cycle_count}")
            print(f"  Positions: {len(self.open_positions)}")
            
            print("\n✓ Trading system stopped gracefully\n")
            
        except Exception as e:
            print(f"  ✗ Cleanup error: {e}")


# =====================================================================
# ENTRY POINT
# =====================================================================

def main():
    """Main entry point for continuous trading"""
    parser = argparse.ArgumentParser(description="Run trading engine with agent modes (monitor/dry-run/live)")
    parser.add_argument("--agent-mode", choices=["monitor", "dry-run", "live"], default="monitor", help="Agent operation mode")
    parser.add_argument("--confirm-file", default=None, help="Path to sentinel file to confirm live trading (e.g., ./GO_LIVE)")
    parser.add_argument("--agent-approve", action="store_true", help="One-time CLI approval to enable live orders")
    parser.add_argument("--config", default=None, help="Optional path to config JSON file")
    args = parser.parse_args()

    # Load configuration (use default if none provided)
    config = load_config(args.config)

    # Determine if live confirmation exists
    confirm_ok = False
    if args.agent_approve:
        confirm_ok = True
    elif args.confirm_file and Path(args.confirm_file).exists():
        confirm_ok = True
    elif os.environ.get('CONFIRM_ORDERS', '').lower() in ('1', 'true', 'yes'):
        confirm_ok = True

    requested_mode = args.agent_mode
    if requested_mode == 'live' and not confirm_ok:
        print("⚠️  Live mode requested but no confirmation found; starting in 'dry-run' to be safe.")
        agent_mode = 'dry-run'
    else:
        agent_mode = requested_mode

    # Create and run engine with agent settings
    engine = TradingEngine(config, agent_mode=agent_mode, confirm_file=args.confirm_file, agent_approve=args.agent_approve)

    # Setup signal handlers for graceful shutdown
    def signal_handler(sig, frame):
        engine.is_running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run setup
    if not engine.setup():
        print("\n✗ Setup failed, exiting")
        return

    # Run continuous trading
    engine.run_continuous()


if __name__ == "__main__":
    main()
