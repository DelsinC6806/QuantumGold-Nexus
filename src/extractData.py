import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
symbol = "XAUUSD"
timeframe = mt5.TIMEFRAME_M15  # 15-minute candles
bars = 10000  # Number of candles to extract

# Initialize MT5
if not mt5.initialize():
    print("initialize() failed")
    mt5.shutdown()
    exit()

# Download history
rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
if rates is None:
    print("No data retrieved")
    mt5.shutdown()
    exit()

# Convert to DataFrame
df = pd.DataFrame(rates)
df['time'] = pd.to_datetime(df['time'], unit='s')
df = df.rename(columns={'time': 'timestamp', 'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close', 'tick_volume': 'volume'})

# Save to CSV
df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].to_csv('history_data.csv', index=False)
print("Exported to history_data.csv")

mt5.shutdown()