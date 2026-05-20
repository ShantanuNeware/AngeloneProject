import pandas as pd
import numpy as np
from indicators import get_trading_zones

# Create sample data with obvious trends
dates = pd.date_range(start="2023-01-01", periods=100, freq="min")
data = {
    "Open": [],
    "High": [],
    "Low": [],
    "Close": [],
}

price = 100
trend = 1

for _ in range(100):
    change = np.random.normal(0, 0.5) + (0.2 * trend) # Drift up or down
    price += change
    
    high = price + abs(np.random.normal(0, 0.5))
    low = price - abs(np.random.normal(0, 0.5))
    
    data["Open"].append(price - change/2)
    data["High"].append(high)
    data["Low"].append(low)
    data["Close"].append(price)
    
    # Flip trend halfway
    if price > 115: trend = -1
    if price < 85: trend = 1

df = pd.DataFrame(data, index=dates)

# Run Zones
df_zones = get_trading_zones(df)

print("--- Data Sample with Zones ---")
print(df_zones[["Close", "UT_Signal", "TM_Direction", "KC_Basis", "Zone"]].tail(20))

# Check if we got any hits
zone_counts = df_zones["Zone"].value_counts()
print("\n--- Zone Counts ---")
print(zone_counts)
