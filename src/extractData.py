import MetaTrader5 as mt5
import pandas as pd
import random
from datetime import datetime

symbol = "XAUUSD.r"
timeframe = mt5.TIMEFRAME_M15

# 需求設定
bars = 1920*6         # 目標輸出根數
search_total = 50000   # 先抓這麼多最近K棒（需 >= bars）
use_random_start = True
seed = None  # 可填整數以固定隨機結果，例如 42

if seed is not None:
    random.seed(seed)

if not mt5.initialize():
    print("initialize() failed")
    mt5.shutdown()
    raise SystemExit

rates_all = mt5.copy_rates_from_pos(symbol, timeframe, 0, search_total)
if rates_all is None or len(rates_all) == 0:
    print("No data retrieved")
    mt5.shutdown()
    raise SystemExit

total = len(rates_all)
if total < bars:
    print(f"資料不足: 取得 {total} 根 < 需求 {bars}，改用全部資料。")
    selected = rates_all
else:
    if use_random_start:
        max_start = total - bars
        start_index = random.randint(0, max_start)
        end_index = start_index + bars
        selected = rates_all[start_index:end_index]
        print(f"隨機起點索引: {start_index} ~ {end_index-1} (共 {len(selected)} 根)")
    else:
        # 保留原邏輯：取最近 bars 根
        selected = rates_all[-bars:]
        start_index = total - bars
        print(f"使用最近 {bars} 根 (索引約 {start_index} ~ {total-1})")

# 轉 DataFrame
df = pd.DataFrame(selected)
# timestamp 轉 datetime
df['time'] = pd.to_datetime(df['time'], unit='s')
df = df.rename(columns={
    'time': 'timestamp',
    'open': 'open',
    'high': 'high',
    'low': 'low',
    'close': 'close',
    'tick_volume': 'volume'
})

start_time = df['timestamp'].iloc[0]
end_time = df['timestamp'].iloc[-1]
print(f"時間範圍: {start_time} -> {end_time}")

out_file = 'history_data.csv' if use_random_start else 'history_data.csv'
df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].to_csv(out_file, index=False)
print(f"Exported to {out_file}")

mt5.shutdown()