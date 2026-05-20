"""
Strategy Manager - Orchestrates Strategy Execution

Responsibilities:
- Load and manage multiple strategies
- Select strategy based on market regime
- Run selected strategy and aggregate signals
- Handle signal filtering and validation
"""

from typing import Dict, List, Optional, TYPE_CHECKING
from dataclasses import dataclass
from types import SimpleNamespace

from ..models import Signal, Candle, MarketRegime
from ..core.regime_manager import RegimeManager, RegimeAwareFilter

if TYPE_CHECKING:
    from ..strategies.base import BaseStrategy


@dataclass
class StrategyManagerConfig:
    """Configuration for strategy manager"""
    regime_manager: RegimeManager
    min_signal_confidence: float = 0.5
    require_regime_agreement: bool = True  # Only trade if regime is clear


class StrategyManager:
    """
    Manages multiple trading strategies and regime-aware selection.
    
    Key features:
    - Load strategies at runtime
    - Select strategy based on market regime
    - Validate signals before trading
    - Aggregate signals from multiple indicators
    """
    
    def __init__(self, config: StrategyManagerConfig):
        self.config = config
        self.regime_manager = config.regime_manager
        self.signal_filter = RegimeAwareFilter(self.regime_manager)
        
        # Active strategies: {strategy_name: BaseStrategy}
        self.strategies: Dict[str, 'BaseStrategy'] = {}
        
        # Strategy registry
        self.strategy_registry: Dict[str, type] = {}
    
    def register_strategy(self, name: str, strategy_class: type) -> None:
        """Register a strategy class for later instantiation"""
        self.strategy_registry[name] = strategy_class

    def load_strategies_from_config(self, strategy_cfg: Optional[dict]) -> None:
        """
        Instantiate and add strategies specified by a strategy config.

        Supported config shapes:
        - {"enabled_strategies": ["ma_strategy", "rsi_strategy"], "params": {"ma_strategy": {"FAST_PERIOD": 10}}}
        - {"name": "MAStrategy"}
        - ["ma_strategy", "rsi_strategy"]

        Strategy matching is tolerant: accepts registry keys, class names, and common name variants.
        """
        if not strategy_cfg:
            return

        # Determine list of strategy names
        names = []
        params = {}
        extra_params = {}
        if isinstance(strategy_cfg, dict):
            if isinstance(strategy_cfg.get("enabled_strategies"), list):
                names = strategy_cfg.get("enabled_strategies", [])
            elif isinstance(strategy_cfg.get("strategies"), list):
                names = strategy_cfg.get("strategies", [])
            elif strategy_cfg.get("name"):
                names = [strategy_cfg.get("name")]
            params = strategy_cfg.get("params") or strategy_cfg.get("configs") or {}
            # Collect other keys as extra params (e.g., fast_ma, slow_ma)
            for k, v in strategy_cfg.items():
                if k not in ("enabled_strategies", "strategies", "params", "configs", "name"):
                    extra_params[k] = v
        elif isinstance(strategy_cfg, list):
            names = strategy_cfg

        for raw_name in names:
            if not raw_name:
                continue
            matched_key = None

            # Direct key match
            if raw_name in self.strategy_registry:
                matched_key = raw_name
            else:
                # tolerant matching against registered keys and class names
                rn = str(raw_name).lower()
                for key, cls in self.strategy_registry.items():
                    if key.lower() == rn:
                        matched_key = key
                        break
                    if key.lower().replace("_", "") == rn.replace("_", ""):
                        matched_key = key
                        break
                    # match class name
                    try:
                        if hasattr(cls, "__name__") and cls.__name__.lower() == rn:
                            matched_key = key
                            break
                        if hasattr(cls, "__name__") and cls.__name__.lower().replace("strategy", "") == rn.replace("strategy", ""):
                            matched_key = key
                            break
                    except Exception:
                        continue

            if not matched_key:
                # could not find a registered strategy for this name
                continue

            strategy_class = self.strategy_registry.get(matched_key)
            if not strategy_class:
                continue

            # Instantiate and apply params if provided
            try:
                inst = strategy_class(matched_key)
            except Exception:
                try:
                    inst = strategy_class()
                except Exception:
                    continue

            # Merge params: explicit params for the strategy + extra top-level params
            strat_params = {}
            if isinstance(params, dict):
                strat_params = dict(params.get(matched_key) or params.get(inst.__class__.__name__) or {})
            # If top-level extra params present, apply them when there's a single strategy or as defaults
            # Merge extra_params into strat_params without overwriting explicit values
            for ek, ev in extra_params.items():
                if ek not in strat_params:
                    strat_params[ek] = ev

            if isinstance(strat_params, dict):
                for k, v in strat_params.items():
                    # allow setting either attribute name or uppercase constant name
                    if hasattr(inst, k):
                        try:
                            setattr(inst, k, v)
                        except Exception:
                            pass
                    elif hasattr(inst, k.upper()):
                        try:
                            setattr(inst, k.upper(), v)
                        except Exception:
                            pass
                    else:
                        if not hasattr(inst, "config") or inst.config is None:
                            inst.config = SimpleNamespace()
                        try:
                            setattr(inst.config, k, v)
                        except Exception:
                            pass

            # Add to active strategies
            self.add_strategy(matched_key, inst)
    
    def add_strategy(self, name: str, strategy: 'BaseStrategy') -> None:
        """Add an instantiated strategy to active strategies"""
        self.strategies[name] = strategy
    
    def remove_strategy(self, name: str) -> None:
        """Remove a strategy from active strategies"""
        if name in self.strategies:
            del self.strategies[name]
    
    def get_active_strategy(self, regime: MarketRegime) -> Optional['BaseStrategy']:
        """
        Get the appropriate strategy for current regime.
        
        Returns:
            Strategy instance for this regime, or None if not configured
        """
        
        # Get recommended strategy for this regime
        strategy_name = self.regime_manager.get_strategy_for_regime(regime)
        
        # Return active strategy if available
        return self.strategies.get(strategy_name)
    
    def analyze_market(
        self,
        candles: List[Candle],
        current_regime: MarketRegime,
        adx_value: float = 0,
        atr_value: float = 0,
        **kwargs
    ) -> Optional[Signal]:
        """
        Analyze market and generate trading signal.
        
        Process:
        1. Check if regime is suitable for trading
        2. Select strategy based on regime
        3. Run strategy analysis
        4. Filter signal based on regime
        5. Return signal if confidence > threshold
        
        Args:
            candles: Recent candlestick data
            current_regime: Current market regime
            adx_value: ADX value (trend strength)
            atr_value: ATR value (volatility)
            **kwargs: Additional indicators
        
        Returns:
            Signal if one is generated and passes filters, else None
        """
        
        # Check if regime is tradable
        if not self.regime_manager.should_trade_regime(current_regime):
            return None
        
        # Get strategy for this regime
        strategy = self.get_active_strategy(current_regime)
        
        if strategy is None or not strategy.config.enabled:
            return None
        
        # Run strategy analysis
        signal = strategy.analyze(
            candles=candles,
            regime=current_regime,
            adx_value=adx_value,
            atr_value=atr_value,
            **kwargs
        )
        
        if signal is None:
            return None
        
        # Filter signal based on regime
        if not self._should_accept_signal(signal, current_regime, adx_value):
            return None
        
        # Check confidence threshold
        if signal.confidence < self.config.min_signal_confidence:
            return None
        
        return signal
    
    def _should_accept_signal(
        self,
        signal: Signal,
        regime: MarketRegime,
        adx_value: float
    ) -> bool:
        """Apply regime-aware filters to signal"""
        
        # In TRENDING regime, require ADX confirmation
        if regime == MarketRegime.TRENDING:
            if adx_value < 25:
                return False
        
        # In RANGING regime, avoid signals against previous trend
        elif regime == MarketRegime.RANGING:
            if adx_value > 20:
                return False
        
        # In VOLATILE regime, require good entry setup
        elif regime == MarketRegime.VOLATILE:
            if signal.confidence < 0.6:  # Require higher confidence
                return False
        
        return True
    
    def run_all_strategies(
        self,
        candles: List[Candle],
        current_regime: MarketRegime,
        **kwargs
    ) -> List[Signal]:
        """
        Run ALL strategies (for analysis/backtesting).
        
        Useful for:
        - Comparing signals from different strategies
        - Backtesting all strategies simultaneously
        - Finding disagreement/consensus signals
        
        Returns:
            List of all signals generated (even if not trading)
        """
        signals = []
        
        for strategy in self.strategies.values():
            if not strategy.config.enabled:
                continue
            
            signal = strategy.analyze(
                candles=candles,
                regime=current_regime,
                **kwargs
            )
            
            if signal and signal.confidence >= self.config.min_signal_confidence:
                signals.append(signal)
        
        return signals
    
    def get_signal_consensus(
        self,
        candles: List[Candle],
        current_regime: MarketRegime,
        **kwargs
    ) -> Optional[Signal]:
        """
        Get consensus signal from multiple strategies.
        
        Useful for more robust trading:
        - Only trade if multiple strategies agree
        - Weight signals by strategy confidence
        - Require majority vote (e.g., 2 out of 3 agree)
        
        Returns:
            Consensus signal if achieved, else None
        """
        
        all_signals = self.run_all_strategies(candles, current_regime, **kwargs)
        
        if not all_signals:
            return None
        
        # Group signals by type
        buy_signals = [s for s in all_signals if s.signal_type.value == 'buy']
        sell_signals = [s for s in all_signals if s.signal_type.value == 'sell']
        
        # Require majority (more than half)
        total = len(all_signals)
        required_votes = (total // 2) + 1
        
        if len(buy_signals) >= required_votes:
            # Return highest confidence buy signal
            best_buy = max(buy_signals, key=lambda s: s.confidence)
            return best_buy
        
        elif len(sell_signals) >= required_votes:
            # Return highest confidence sell signal
            best_sell = max(sell_signals, key=lambda s: s.confidence)
            return best_sell
        
        return None
    
    def get_strategy_status(self) -> Dict[str, dict]:
        """Get status of all active strategies"""
        status = {}
        
        for name, strategy in self.strategies.items():
            status[name] = {
                "enabled": strategy.config.enabled,
                "regime_requirement": self.regime_manager.get_strategy_for_regime(
                    getattr(strategy, '_last_regime', MarketRegime.UNKNOWN)
                ),
            }
        
        return status
    
    def __str__(self) -> str:
        return (
            f"StrategyManager(active_strategies={len(self.strategies)}, "
            f"min_confidence={self.config.min_signal_confidence})"
        )
