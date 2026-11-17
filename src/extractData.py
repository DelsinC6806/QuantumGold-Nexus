from datetime import datetime
import random
import zoneinfo
import MetaTrader5 as mt5
import pandas as pd

<<<<<<< HEAD
symbol = "NAS100"
timeframe = mt5.TIMEFRAME_M15

# 設定你 Broker 的伺服器時區（多數經紀商為 UTC+2/UTC+3，即 Europe/Athens 或 EET）
# 如果你的 Broker 是 OANDA/IC Markets/Pepperstone，請使用 "Europe/Athens"（會自動處理冬夏令時間）
BROKER_TIMEZONE = zoneinfo.ZoneInfo("Europe/Athens")
TARGET_TIMEZONE = zoneinfo.ZoneInfo("Asia/Hong_Kong")

bars = 1920 * 12  # 目標輸出根數
search_total = 80000  # 先抓最近 K 棒
use_random_start = False  # 建議先抓最新資料，確保時間轉換正確
seed = None
=======
symbol = "USTEC.x"
timeframe = mt5.TIMEFRAME_M15

# 需求設定
bars = 1920*36     # 目標輸出根數
search_total = 60000   # 先抓這麼多最近K棒（需 >= bars）
use_random_start = True
seed = None  # 可填整數以固定隨機結果，例如 42
>>>>>>> 1cf10d021c960f17721554d2fc2770fd809f6a5c

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
        print(f"隨機起點索引: {start_index} ~ {end_index-1}")
    else:
        selected = rates_all[-bars:]
        start_index = total - bars
        print(f"使用最近 {bars} 根 (索引約 {start_index} ~ {total-1})")

df = pd.DataFrame(selected)

# 1. 先將原始 timestamp 轉為 UTC 時間的 datetime
df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)

# 2. 標註為 Broker 伺服器時區 (例如 Europe/Athens)，再轉換為 Asia/Hong_Kong (HKT)
df["timestamp"] = (
    df["time"]
    .dt.tz_convert(BROKER_TIMEZONE)
    .dt.tz_convert(TARGET_TIMEZONE)
    .dt.tz_localize(None)  # 移除 tz 標籤，保留乾淨的 HKT 本地時間字串
)

df = df.rename(columns={"tick_volume": "volume"})

start_time = df["timestamp"].iloc[0]
end_time = df["timestamp"].iloc[-1]
print(f"修正後 (HKT) 時間範圍: {start_time} -> {end_time}")

out_file = "history_data.csv"
df[["timestamp", "open", "high", "low", "close", "volume"]].to_csv(
    out_file, index=False
)
print(f"{symbol} data has Exported to {out_file} (All timestamps mapped to HKT)")

mt5.shutdown()