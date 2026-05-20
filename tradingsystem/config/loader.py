"""
Configuration Loader
Loads and validates configuration with broker factory
"""

import json
import logging
import sys
from copy import deepcopy
from typing import Dict, Optional
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(next(parent for parent in Path(__file__).resolve().parents if (parent / "trading_system").exists())))


logger = logging.getLogger(__name__)
DEFAULT_CONFIG_PATH = Path(__file__).with_name("default.json")


class ConfigLoader:
    """
    Load and manage configuration
    Handles broker selection and validation
    """

    def __init__(self):
        self.config = None
        self.broker_instance = None

    def load(self, config_path: str) -> Dict:
        """
        Load configuration from JSON file
        
        Args:
            config_path: Path to config JSON file
            
        Returns:
            Configuration dict
            
        Example:
            {
                "system": {
                    "broker": "shoonya",
                    "log_level": "INFO",
                    "log_file": "logs/trading.log"
                },
                "brokers": {
                    "shoonya": {
                        "userid": "ABC123",
                        "password": "****",
                        "twoFA": "Y",
                        "vendor_code": "****",
                        "api_secret": "****",
                        "imei": "****"
                    },
                    "angleone": {
                        "username": "USER123",
                        "password": "****",
                        "factor2": "****",
                        "api_key": "****"
                    }
                },
                "strategy": {
                    "name": "MAStrategy",
                    "symbol": "SBIN-EQ",
                    "exchange": "NSE",
                    "fast_ma": 9,
                    "slow_ma": 21
                },
                "risk": {
                    "max_position_size": 100000,
                    "max_positions": 10,
                    "max_daily_loss": 50000
                }
            }
        """
        try:
            config_file = Path(config_path)
            
            if not config_file.exists():
                raise FileNotFoundError(f"Config file not found: {config_path}")
            
            with open(config_file, 'r') as f:
                self.config = json.load(f)
            
            logger.info(f"Configuration loaded from {config_path}")
            self._validate_config()
            return self.config
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file: {e}")
            raise
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            raise

    def _validate_config(self):
        """Validate configuration structure"""
        required_keys = ['system', 'brokers', 'strategy', 'risk']
        
        for key in required_keys:
            if key not in self.config:
                raise ValueError(f"Missing required config section: {key}")
        
        # Validate broker selection
        broker = self.config['system'].get('broker', 'shoonya')
        if broker not in self.config['brokers']:
            raise ValueError(f"Broker '{broker}' not configured in brokers section")
        
        logger.info(f"Configuration validated. Broker: {broker}")

    def get_broker(self):
        """
        Get broker instance based on configuration
        
        Returns:
            BrokerInterface implementation (ShoonyaBroker or AngelOneBroker)
        """
        if self.broker_instance is None:
            if self.config is None:
                raise RuntimeError("Configuration not loaded. Call load() first.")
            
            self.broker_instance = get_broker(self.config, 
                                            self.config['system']['broker'])
            logger.info(f"Broker instance created: {type(self.broker_instance).__name__}")
        
        return self.broker_instance

    def get(self, section: str, key: Optional[str] = None, default=None):
        """
        Get configuration value
        
        Args:
            section: Section name (system, broker, strategy, risk)
            key: Key within section (None to get entire section)
            default: Default value if not found
            
        Returns:
            Configuration value
        """
        if self.config is None:
            return default
        
        section_data = self.config.get(section, {})
        
        if key is None:
            return section_data
        
        return section_data.get(key, default)

    def get_broker_config(self) -> Dict:
        """Get configuration for current broker"""
        if self.config is None:
            raise RuntimeError("Configuration not loaded")
        
        broker = self.config['system']['broker']
        return self.config['brokers'].get(broker, {})

    def get_strategy_config(self) -> Dict:
        """Get strategy configuration"""
        return self.get('strategy', default={})

    def get_risk_config(self) -> Dict:
        """Get risk management configuration"""
        return self.get('risk', default={})

    def switch_broker(self, broker_name: str):
        """
        Switch to different broker at runtime
        
        Args:
            broker_name: 'shoonya' or 'angleone'
        """
        if self.config is None:
            raise RuntimeError("Configuration not loaded")
        
        if broker_name not in self.config['brokers']:
            raise ValueError(f"Broker '{broker_name}' not configured")
        
        logger.info(f"Switching broker from {self.config['system']['broker']} to {broker_name}")
        self.config['system']['broker'] = broker_name
        self.broker_instance = None  # Reset broker instance
        
        # Return new broker instance
        return self.get_broker()

    def to_dict(self) -> Dict:
        """Get entire configuration as dict"""
        return self.config.copy() if self.config else {}

    @staticmethod
    def create_sample_config(output_path: str, broker: str = 'shoonya'):
        """
        Create a sample configuration file
        
        Args:
            output_path: Where to save the sample config
            broker: Default broker ('shoonya' or 'angleone')
        """
        sample_config = {
            "system": {
                "broker": broker,
                "log_level": "INFO",
                "log_file": "logs/trading.log"
            },
            "brokers": {
                "shoonya": {
                    "userid": "YOUR_USERID",
                    "password": "YOUR_PASSWORD",
                    "twoFA": "Y",
                    "vendor_code": "YOUR_VENDOR_CODE",
                    "api_secret": "YOUR_API_SECRET",
                    "imei": "YOUR_IMEI"
                },
                "angleone": {
                    "username": "YOUR_USERNAME",
                    "password": "YOUR_PASSWORD",
                    "factor2": "YOUR_2FA",
                    "api_key": "YOUR_API_KEY"
                }
            },
            "strategy": {
                "name": "MAStrategy",
                "symbol": "SBIN-EQ",
                "exchange": "NSE",
                "token": "3045",
                "timeframe": "1h",
                "fast_ma": 9,
                "slow_ma": 21,
                "min_volume": 1000
            },
            "risk": {
                "max_position_size": 100000,
                "max_positions": 10,
                "max_loss_per_trade": 5000,
                "max_daily_loss": 50000,
                "max_drawdown_percent": 10,
                "stop_loss_percent": 2,
                "take_profit_percent": 5
            }
        }
        
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output, 'w') as f:
            json.dump(sample_config, f, indent=2)
        
        logger.info(f"Sample config created: {output_path}")


def _merge_dicts(base: Dict, override: Optional[Dict]) -> Dict:
    """Recursively merge two dictionaries without mutating the inputs."""
    merged = deepcopy(base or {})

    if not override:
        return merged

    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = deepcopy(value)

    return merged


def _normalize_runtime_config(config: Dict) -> Dict:
    """
    Normalize legacy/shared config into the refactored runtime shape.

    The entrypoint expects strategy-specific sections (`ma_strategy`,
    `rsi_strategy`, `bb_strategy`) and `risk_manager`, while the packaged
    default config still keeps shared values under `strategy` and `risk`.
    """
    normalized = deepcopy(config)

    shared_strategy = normalized.get('strategy', {})
    shared_risk = normalized.get('risk', {})
    system_config = normalized.setdefault('system', {})

    if 'poll_interval_seconds' not in system_config and 'poll_interval_seconds' in shared_strategy:
        system_config['poll_interval_seconds'] = shared_strategy['poll_interval_seconds']

    strategy_defaults = {
        'ma_strategy': {
            'name': 'MAStrategyImproved',
            'fast_ma': 9,
            'slow_ma': 21,
            'min_adx': 20,
            'pullback_percent': 1.0,
            'min_rr_ratio': 2.0,
        },
        'rsi_strategy': {
            'name': 'RSIStrategyImproved',
            'rsi_period': 14,
            'oversold_level': 30,
            'overbought_level': 70,
            'max_adx': 25,
            'min_rr_ratio': 2.0,
        },
        'bb_strategy': {
            'name': 'BBStrategyImproved',
            'bb_period': 20,
            'bb_stddev': 2.0,
            'require_volume_confirmation': True,
            'min_rr_ratio': 1.5,
        },
    }

    for section, defaults in strategy_defaults.items():
        normalized[section] = _merge_dicts(
            _merge_dicts(shared_strategy, defaults),
            normalized.get(section, {}),
        )

    normalized['risk_manager'] = _merge_dicts(shared_risk, normalized.get('risk_manager', {}))
    normalized.setdefault('regime_manager', {})

    return normalized


def load_config(config_path: Optional[str] = None) -> Dict:
    """
    Convenience loader used by the main entrypoint.

    Args:
        config_path: Optional explicit path to a config JSON file.

    Returns:
        Normalized runtime configuration dictionary.
    """
    resolved_path = str(Path(config_path) if config_path else DEFAULT_CONFIG_PATH)
    loader = ConfigLoader()
    return _normalize_runtime_config(loader.load(resolved_path))


def _build_config_summary(config: Dict) -> Dict:
    """Build a safe, compact config summary for standalone runs."""
    strategy = config.get("strategy", {})
    risk = config.get("risk_manager", config.get("risk", {}))
    return {
        "broker": config.get("system", {}).get("broker"),
        "configured_brokers": sorted(config.get("brokers", {}).keys()),
        "strategy": {
            "name": strategy.get("name"),
            "symbol": strategy.get("symbol"),
            "exchange": strategy.get("exchange"),
            "timeframe": strategy.get("timeframe"),
        },
        "risk_limits": {
            "max_positions": risk.get("max_positions"),
            "max_position_size": risk.get("max_position_size"),
            "max_daily_loss": risk.get("max_daily_loss"),
        },
        "sections": sorted(config.keys()),
    }


def main():
    """Run the config loader directly."""
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Standalone config loader")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config JSON file")
    parser.add_argument("--broker", choices=["shoonya", "angleone"], help="Override broker for the smoke test")
    parser.add_argument("--connect", action="store_true", help="Try a live broker connection using the loaded config")
    parser.add_argument("--create-sample", help="Write a sample config JSON to this path and exit")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if args.create_sample:
        ConfigLoader.create_sample_config(args.create_sample, broker=args.broker or "shoonya")
        print(json.dumps({"sample_config_created": args.create_sample}, indent=2))
        return

    config = load_config(args.config)
    summary = _build_config_summary(config)
    summary["config_path"] = str(Path(args.config).resolve())

    if args.connect:
        broker_name = args.broker or summary["broker"]
        broker = get_broker(config, broker_name)

        async def _smoke_test():
            connected = await broker.connect()
            result = {"broker": broker_name, "connected": connected}
            if connected:
                result["positions_count"] = len(await broker.get_positions())
                await broker.disconnect()
            return result

        summary["connection_test"] = asyncio.run(_smoke_test())

    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()

