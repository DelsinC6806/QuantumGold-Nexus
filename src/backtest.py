import pandas as pd
import numpy as np

# --- Strategy parameters ---
move_sl_to_be = False
risk_per_trade_pct = 0.01
contract_size = 100
spread = 0.6  # example spread in price units (adjust to your broker)

def calculate_ema(prices, window):
    return pd.Series(prices).ewm(span=window, adjust=False).mean().values

def calculate_atr(data, window=14):
    high = np.array([bar['high'] for bar in data])
    low = np.array([bar['low'] for bar in data])
    close = np.array([bar['close'] for bar in data])
    tr = np.maximum(high[1:] - low[1:], 
                    np.abs(high[1:] - close[:-1]), 
                    np.abs(low[1:] - close[:-1]))
    atr = pd.Series(tr).rolling(window=window).mean().values
    return np.concatenate([np.full(window, np.nan), atr])

def calculate_rsi(prices, window=14):
    delta = np.diff(prices)
    up = np.where(delta > 0, delta, 0)
    down = np.where(delta < 0, -delta, 0)
    roll_up = pd.Series(up).rolling(window).mean()
    roll_down = pd.Series(down).rolling(window).mean()
    rs = roll_up / roll_down
    rsi = 100 - (100 / (1 + rs))
    return np.concatenate([[50], rsi])  # pad first value

def backtest_strategy(data, initial_balance=100000):
    balance = initial_balance
    lowest_balance = balance
    position = None
    trades = []
    today_trade_count = 0

    close_prices = [bar['close'] for bar in data]

    for i in range(1000, len(data)):  # need enough bars for H1 EMA200
        ts = pd.to_datetime(data[i]['timestamp'])

        # reset daily trade count at 01:00
        if ts.hour == 1 and ts.minute == 0:
            today_trade_count = 0

        if ts.hour < 8 or ts.hour > 20: continue

        # --- H1 trend filter using M15 data ---
        h1_close = [bar['close'] for bar in data[i-800:i-1]]  # avoid look-ahead
        h1_ema50 = calculate_ema(h1_close, 200)[-1]   # 200 M15 = 50 H1
        h1_ema200 = calculate_ema(h1_close, 800)[-1]  # 800 M15 = 200 H1
        is_h1_bullish = h1_ema50 > h1_ema200
        is_h1_bearish = h1_ema50 < h1_ema200

        # --- M15 data ---
        m15_slice = data[i-250:i-1]  # avoid look-ahead
        close_m15 = [bar['close'] for bar in m15_slice]
        low_m15 = [bar['low'] for bar in m15_slice]
        high_m15 = [bar['high'] for bar in m15_slice]

        m15_ema50 = calculate_ema(close_m15, 50)
        m15_ema200 = calculate_ema(close_m15, 200)
        rsi = calculate_rsi(close_m15, 14)
        rsi_slope = rsi[-1] - rsi[-2]

        curr_low = low_m15[-1]
        curr_high = high_m15[-1]
        curr_close = close_m15[-1]
        curr_ema50 = m15_ema50[-1]
        curr_rsi = rsi[-1]

        atr14_series = calculate_atr(m15_slice, 14)
        atr250_series = calculate_atr(m15_slice, 250)
        atr14_slope = atr14_series[-1] - atr14_series[-2]
        is_volatility_rising = atr14_slope > 0

        signal = 0
        # --- Entry logic ---
        if is_h1_bullish and (m15_ema50[-1] > m15_ema200[-1]):
            if curr_low <= curr_ema50 and curr_close > curr_ema50:
                if (45 < curr_rsi < 60) :
                    signal = 1
        elif is_h1_bearish and (m15_ema50[-1] < m15_ema200[-1]):
            if curr_high >= curr_ema50 and curr_close < curr_ema50:
                if (40 < curr_rsi < 55) :
                    signal = -1

        # --- Exit logic ---
        if position is not None:
            entry = position['entry']
            high = data[i]['high']
            low = data[i]['low']
            exit_price = None

            # Breakeven SL refinement
            one_r = abs(entry - position['sl'])
            if move_sl_to_be:
                    one_r = abs(entry - position['sl_initial']) if 'sl_initial' in position else abs(entry - position['sl'])
                    if position['type'] == 'BUY':
                        # 1.5R 移至保本
                        if high >= entry + 1.8 * one_r and position['sl'] < entry:
                            position['sl'] = entry
                        # 2.0R 鎖定 0.5R 利潤
                        elif high >= entry + 2.8 * one_r and position['sl'] < entry + 1 * one_r:
                            position['sl'] = entry + 1 * one_r
                    elif position['type'] == 'SELL':
                        if low <= entry - 1.8 * one_r and position['sl'] > entry:
                            position['sl'] = entry
                        elif low <= entry - 2.8 * one_r and position['sl'] > entry - 1 * one_r:
                            position['sl'] = entry - 1 * one_r

            # SL/TP priority (SL first)
            if position['type'] == 'BUY':
                if low <= position['sl']:
                    exit_price = position['sl']
                elif high >= position['tp']:
                    exit_price = position['tp']
            elif position['type'] == 'SELL':
                if high >= position['sl']:
                    exit_price = position['sl']
                elif low <= position['tp']:
                    exit_price = position['tp']

            if exit_price is not None:
                pnl = (exit_price - entry) * contract_size * position['lot'] if position['type'] == 'BUY' else (entry - exit_price) * contract_size * position['lot']
                balance += pnl
                lowest_balance = min(lowest_balance, balance)
                trades.append({'type': position['type'], 'entry': entry, 'exit': exit_price, 'pnl': pnl, 'lot': position['lot']})
                position = None

        # --- Entry conditions ---
        if position is None and signal != 0 and today_trade_count < 1 and not np.isnan(atr14_series[-1]):
            entry = curr_close + spread if signal == 1 else curr_close - spread
            atr_val = atr14_series[-1]
            if signal == 1:
                sl = entry - atr_val * 1
                tp = entry + atr_val * 3
                sl_distance = abs(entry - sl)
                risk_amount = balance * risk_per_trade_pct
                lot = risk_amount / (sl_distance * contract_size)
                position = {
                    'type': 'BUY', 
                    'entry': entry, 
                    'sl': sl, 
                    'sl_initial': sl,  # <--- 必須加上這一行
                    'tp': tp, 
                    'lot': lot
                }
            elif signal == -1:
                sl = entry + atr_val * 1
                tp = entry - atr_val * 3
                sl_distance = abs(sl - entry)
                risk_amount = balance * risk_per_trade_pct
                lot = risk_amount / (sl_distance * contract_size)
                position = {
                    'type': 'BUY', 
                    'entry': entry, 
                    'sl': sl, 
                    'sl_initial': sl,  # <--- 必須加上這一行
                    'tp': tp, 
                    'lot': lot
                }
            today_trade_count += 1

    # --- Results ---
    win_trades = sum(1 for t in trades if t['pnl'] >= 0)
    lose_trades = sum(1 for t in trades if t['pnl'] < 0)
    print(f"總交易次數: {len(trades)}")
    print(f"最終資金: {balance:.2f}")
    print(f"獲利交易次數: {win_trades}")
    print(f"虧損交易次數: {lose_trades}")
    print(f"獲勝率: {win_trades / len(trades) * 100:.2f}%")
    print(f"獲利率: {(balance - initial_balance) / initial_balance * 100:.2f}%")
    print(f"最低資金: {lowest_balance:.2f}")

if __name__ == "__main__":
    df = pd.read_csv("history_data.csv")
    data = df.to_dict('records')
    backtest_strategy(data)