"""
Independent Angel One Login Module
Test Angel One authentication without running the full trading system

Usage:
    python -m tradingsystem.broker.login
    
Or directly:
    python tradingsystem/broker/login.py
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pyotp
from tradingsystem.broker.angelone_session import AngelOneSession
from tradingsystem.config.loader import load_config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_login():
    """
    Standalone Angel One login test
    
    Returns:
        SmartConnect client if successful, None otherwise
    """
    try:
        config = load_config()
        broker_config = config["brokers"]["angleone"]
        
        print("\n" + "=" * 60)
        print("🔐 ANGEL ONE LOGIN TEST")
        print("=" * 60)
        print(f"Username: {broker_config['username']}")
        print(f"Exchange: {broker_config.get('exchange', 'NSE')}")
        
        session = AngelOneSession(
            api_key=broker_config["api_key"],
            client_code=broker_config["username"],
            password=broker_config["password"],
            totp_secret=broker_config["factor2"]
        )
        
        client = session.login()
        
        if client:
            print("\n✅ LOGIN SUCCESSFUL")
            print(f"   Client initialized: {client}")
            return client
        else:
            print("\n❌ LOGIN FAILED - Check credentials")
            return None
            
    except Exception as e:
        logger.error(f"❌ Error during login: {e}")
        return None


def main():
    """Entry point for direct execution"""
    client = test_login()
    
    if client:
        # Quick test - fetch account profile
        try:
            profile = client.getProfile()
            if profile and profile.get("status"):
                print(f"\n📊 Account Profile:")
                data = profile.get("data", {})
                print(f"   Name: {data.get('name', 'N/A')}")
                print(f"   Email: {data.get('email', 'N/A')}")
                print(f"   Client Code: {data.get('clientcode', 'N/A')}")
        except Exception as e:
            logger.warning(f"Could not fetch profile: {e}")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
