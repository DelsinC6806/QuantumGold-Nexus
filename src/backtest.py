import pandas as pd
import numpy as np

# 策略參數
move_sl_to_be = False
def calculate_ema(prices, window):
    return pd.Series(prices).ewm(span=window, adjust=False).mean().values

def calculate_atr(data, window=14):
    high = np.array([bar['high'] for bar in data])
    low = np.array([bar['low'] for bar in data])
    close = np.array([bar['close'] for bar in data])
    tr = np.maximum(high[1:] - low[1:], np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1]))
    atr = pd.Series(tr).rolling(window=window).mean().values
    return np.concatenate([np.full(window, np.nan), atr])

def backtest_dual_ema_atr(
    data, 
    initial_balance=10000, 
    fast=5, 
    slow=20, 
    atr_mult_sl=1.0, 
    atr_mult_tp=3.5,
    contract_size=100
):
    balance = initial_balance
    lowest_balance = balance
    position = None
    trades = []
    today_trade_count = 0
    close_prices = [bar['close'] for bar in data]
    
    for i in range(max(slow, 14), len(data)):
        # 只用到第i根的資料計算指標
        if('01:00:00' in data[i]['timestamp']):
           today_trade_count = 0
        ema_fast = calculate_ema(close_prices[:i+1], fast)
        ema_slow = calculate_ema(close_prices[:i+1], slow)
        atr = calculate_atr(data[:i+1], 14)
        price = close_prices[i]
        signal = 0

        # Volatility filter
        if np.isnan(atr[i]) or atr[i] < np.nanmedian(atr[max(0, i-250):i]):
            continue

        if today_trade_count >= 1:
            continue

        # 產生訊號
        if ema_fast[-2] < ema_slow[-2] and ema_fast[-1] > ema_slow[-1]:
            signal = 1  # 多
        elif ema_fast[-2] > ema_slow[-2] and ema_fast[-1] < ema_slow[-1]:
            signal = -1 # 空

        # 平倉邏輯
        if position is not None:
            entry = position['entry']
            high = data[i]['high']
            low = data[i]['low']
            exit_price = None
            if position['type'] == 'BUY':
                if('23:45:00' in data[i]['timestamp']): #
                    exit_price = price
                if low <= position['sl']:
                    exit_price = position['sl']
                elif high >= position['tp']:
                    exit_price = position['tp']
            elif position['type'] == 'SELL':
                if('23:45:00' in data[i]['timestamp']): #
                    exit_price = price
                if high >= position['sl']:
                    exit_price = position['sl']
                elif low <= position['tp']:
                    exit_price = position['tp']
            if exit_price is not None:
                if position['type'] == 'BUY':
                    pnl = (exit_price - position['entry']) * contract_size * position['lot']
                else:
                    pnl = (position['entry'] - exit_price) * contract_size * position['lot']
                balance += pnl
                if balance < lowest_balance:
                    lowest_balance = balance
                trades.append({'type': position['type'], 'entry': position['entry'], 'exit': f"{exit_price:.2f}", 'pnl': f"{pnl:.2f}", 'lot': position['lot']})
                position = None

        # 開倉邏輯（只允許單一持倉）
        if position is None and signal != 0 and not np.isnan(atr[-1]):
            entry = price
            if signal == 1:
                sl = entry - atr_mult_sl * atr[-1]
                tp = entry + atr_mult_tp * atr[-1]
                sl_distance = abs(entry - sl)
                risk_per_trade = balance * 0.005
                lot = risk_per_trade / (sl_distance * contract_size) if sl_distance > 0 else 0.01
                position = {'type': 'BUY', 'entry': entry, 'sl': sl, 'tp': tp, 'lot': lot}
                today_trade_count += 1
            elif signal == -1:
                sl = entry + atr_mult_sl * atr[-1]
                tp = entry - atr_mult_tp * atr[-1]
                sl_distance = abs(sl - entry)
                risk_per_trade = balance * 0.005
                lot = risk_per_trade / (sl_distance * contract_size) if sl_distance > 0 else 0.01
                position = {'type': 'SELL', 'entry': entry, 'sl': sl, 'tp': tp, 'lot': lot}
                today_trade_count += 1


    win_trades = 0
    lose_trades = 0
    for t in trades:
        print(t)
        if float(t['pnl']) >= 0:
            win_trades += 1
        elif float(t['pnl']) < 0:
            lose_trades += 1
    print(f"總交易次數: {len(trades)}")
    print(f"最終資金: {balance:.2f}")
    print(f"獲利交易次數: {win_trades}")
    print(f"虧損交易次數: {lose_trades}")
    print(f"獲勝率: {win_trades / len(trades) * 100:.2f}%")
    print(f"獲利率: {(balance - initial_balance) / initial_balance * 100:.2f}%")
    print(f"最低資金: {lowest_balance:.2f}")

if __name__ == "__main__":
    data = pd.read_csv("history_data.csv")
    data = data.to_dict('records')
    backtest_dual_ema_atr(
        data,
    )