"""
Angel One Session Management
Handles authentication and client initialization
"""
from SmartApi import SmartConnect
import pyotp
import logging

logger = logging.getLogger(__name__)


class AngelOneSession:
    """Manages Angel One broker authentication"""

    def __init__(self, api_key, client_code, password, totp_secret):
        self.api_key = api_key
        self.client_code = client_code
        self.password = password
        self.totp_secret = totp_secret
        self.client = None

    def login(self):
        """Authenticate with Angel One broker and return client"""
        try:
            self.client = SmartConnect(api_key=self.api_key)
            otp = pyotp.TOTP(self.totp_secret).now()

            response = self.client.generateSession(
                self.client_code,
                self.password,
                otp
            )

            if not response.get("status"):
                raise Exception(response)

            logger.info("✅ Angel One Login Successful")
            return self.client

        except Exception as e:
            logger.exception("❌ Login failed: %s", e)
            return None
