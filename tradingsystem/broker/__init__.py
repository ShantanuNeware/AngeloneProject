"""
Angel One Broker Module
Independent, testable components for broker operations

Each module is independently executable:
- login.py          - Test authentication
- fetcher.py        - Test data fetching
- order_manager.py  - Test order placement
- websocket.py      - Test real-time feeds

Usage in code:
    from tradingsystem.broker import (
        AngelOneSession,
        AngelOneFetcher,
        OrderManager,
        WebSocketHandler
    )

Usage in terminal:
    python -m tradingsystem.broker.login
    python -m tradingsystem.broker.fetcher
    python -m tradingsystem.broker.order_manager
    python -m tradingsystem.broker.websocket
"""

from tradingsystem.broker.angelone_session import AngelOneSession
from tradingsystem.broker.angelone_fetcher import AngelOneFetcher
from tradingsystem.broker.order_manager import OrderManager
from tradingsystem.broker.websocket import WebSocketHandler

__all__ = [
    "AngelOneSession",
    "AngelOneFetcher", 
    "OrderManager",
    "WebSocketHandler",
]
