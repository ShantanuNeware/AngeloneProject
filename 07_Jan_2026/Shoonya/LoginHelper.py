from Shoonya.api_helper import ShoonyaApiPy
import pyotp
from config import USER_ID, PASSWORD, VC, APP_KEY, IMEI, factor2

# This now becomes the single, shared instance for the main application.
# Global API object
api = ShoonyaApiPy()


def login():
    """Login and set session for Shoonya API."""
    try:
        otp = pyotp.TOTP(factor2).now()
        resp = api.login(
            userid=USER_ID,
            password=PASSWORD,
            twoFA=otp,
            vendor_code=VC,
            api_secret=APP_KEY,
            imei=IMEI,
        )
        if resp and resp.get("stat") == "Ok":
            token = resp.get("susertoken")
            api.set_session(userid=USER_ID, password=PASSWORD, usertoken=token)
            print("Login successful.")
            return True
        else:
            print("Login failed:", resp)
            return False
    except Exception as e:
        print(f"Login exception: {e}")
        return False
