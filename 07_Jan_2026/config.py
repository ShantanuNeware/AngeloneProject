# API Credentials
USER_ID = "FA420765"
PASSWORD = "Monkey@123#"
VC = "FA420765_U"
factor2 = "3F5UJR32AF7R4DJ236TGA544Z6Z4524U"
APP_KEY = "c762904cf27fd3d83bf5b79e4a6bc4b5"
IMEI = "abc1234"

NIFTY_Index_symbol = "49229"  # Nifty index symbol

exchange = "NFO"
Month = "JAN"
Year = "26"
tradingsymbol = "NIFTY"
Nearest50_100 = 50

CACHE_TTL = 30.0  # seconds

# Start_Time_Date = "12-05-2025 09:15:00"
historical_data_interval = 1
OptionChain_data_interval = 1

# Trade Settings
RISK_PER_TRADE = 1000  # Amount you risk per trade
QUANTITY = 75  # Default trade quantity
STOP_LOSS_PERCENT = 2  # Stop-loss percentage
TRAILING_STOP_PERCENT = 1  # Trailing stop percentage
# Add this to your existing config.py
TRAILING_STOP_STEP = 5  # Points to move trailing stop loss

HISTORICAL_DATA_EXCEL_FILE_PATH = "ExcelFiles/HISTORICAL.xlsx"
HISTORICAL_DATA_SHEET_NAME = "HISTORICAL"

INDICATORS_DATA_EXCEL_FILE_PATH = "ExcelFiles/INDICATORS.xlsx"
INDICATORS_DATA_SHEET_NAME = "INDICATORS"

# Analysis Config
PCR_THRESHOLD_CALL = 0.98
PCR_THRESHOLD_PUT = 1.02
GAMMA_CONFIDENCE_HIGH = 0.8
GAMMA_CONFIDENCE_MEDIUM = 0.6
REALITY_CHECK_DROP_PCT = 0.998
REALITY_CHECK_RISE_PCT = 1.005
