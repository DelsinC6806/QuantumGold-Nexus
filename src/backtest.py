import pandas as pd
import numpy as np

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
    slow=15, 
    atr_mult_sl=1.0, 
    atr_mult_tp=4.0,
    contract_size=100,
    daily_max_loss=500
):
    close_prices = [bar['close'] for bar in data]
    ema_fast = calculate_ema(close_prices, fast)
    ema_slow = calculate_ema(close_prices, slow)
    atr = calculate_atr(data, 14)
    balance = initial_balance
    position = None
    results = []
    day_pnl = 0
    current_day = None
    day_stop = False
    day_loss_count = 0
    daily_max_profit_dynamic = balance * 0.05

    for i in range(max(slow, 15), len(data)):
        bar_day = pd.to_datetime(data[i]['timestamp']).date()
        # 新的一天，重置 day_pnl、day_stop、day_loss_count，並動態計算 max profit
        if current_day != bar_day:
            day_pnl = 0
            current_day = bar_day
            day_stop = False
            day_loss_count = 0
            daily_max_profit_dynamic = balance * 0.05  # 動態最大獲利

        # 若已達到當日最大獲利/最大虧損/連續2筆虧損，停止當天交易
        if day_stop:
            continue
        if day_pnl >= daily_max_profit_dynamic or day_pnl <= -daily_max_loss or day_loss_count >= 2:
            day_stop = True
            continue

        # Volatility filter
        if np.isnan(atr[i]) or atr[i] < np.nanmedian(atr[max(0, i-100):i]):
            continue

        # Entry signals
        if position is None:
            # 動態計算每單最大風險（不超過 daily_max_loss，也可自訂比例）
            if ema_fast[i-1] < ema_slow[i-1] and ema_fast[i] > ema_slow[i]:
                entry_price = close_prices[i]
                sl = entry_price - atr_mult_sl * atr[i]
                tp = entry_price + atr_mult_tp * atr[i]
                sl_distance = abs(entry_price - sl)
                risk_per_trade = min(balance * 0.01, daily_max_loss)  # 1% 或 daily_max_loss
                lot_size = risk_per_trade / (sl_distance * contract_size) if sl_distance > 0 else 0.01
                position = {'type': 'BUY', 'entry': entry_price, 'sl': sl, 'tp': tp, 'lot': lot_size, 'entry_idx': i}
            elif ema_fast[i-1] > ema_slow[i-1] and ema_fast[i] < ema_slow[i]:
                entry_price = close_prices[i]
                sl = entry_price + atr_mult_sl * atr[i]
                tp = entry_price - atr_mult_tp * atr[i]
                sl_distance = abs(sl - entry_price)
                risk_per_trade = min(balance * 0.01, daily_max_loss)
                lot_size = risk_per_trade / (sl_distance * contract_size) if sl_distance > 0 else 0.01
                position = {'type': 'SELL', 'entry': entry_price, 'sl': sl, 'tp': tp, 'lot': lot_size, 'entry_idx': i}
        else:
            high = data[i]['high']
            low = data[i]['low']
            exit_price = None
            pnl = 0
            # 檢查浮動獲利是否達到當日最大獲利
            if position['type'] == 'BUY':
                floating_profit = (high - position['entry']) * position['lot'] * contract_size
                if floating_profit >= daily_max_profit_dynamic:
                    exit_price = position['entry'] + daily_max_profit_dynamic / (position['lot'] * contract_size)
                    day_stop = True
                elif low <= position['sl']:
                    exit_price = position['sl']
                elif high >= position['tp']:
                    exit_price = position['tp']
                elif ema_fast[i-1] > ema_slow[i-1] and ema_fast[i] < ema_slow[i]:
                    exit_price = close_prices[i]
                if exit_price is not None:
                    pnl = (exit_price - position['entry']) * position['lot'] * contract_size
            elif position['type'] == 'SELL':
                floating_profit = (position['entry'] - low) * position['lot'] * contract_size
                if floating_profit >= daily_max_profit_dynamic:
                    exit_price = position['entry'] - daily_max_profit_dynamic / (position['lot'] * contract_size)
                    day_stop = True
                elif high >= position['sl']:
                    exit_price = position['sl']
                elif low <= position['tp']:
                    exit_price = position['tp']
                elif ema_fast[i-1] < ema_slow[i-1] and ema_fast[i] > ema_slow[i]:
                    exit_price = close_prices[i]
                if exit_price is not None:
                    pnl = (position['entry'] - exit_price) * position['lot'] * contract_size
            if exit_price is not None:
                balance += pnl
                day_pnl += pnl
                if pnl < 0:
                    day_loss_count += 1
                if pnl >= daily_max_profit_dynamic:
                    day_stop = True
                results.append({
                    'entry_time': data[position['entry_idx']]['timestamp'],
                    'exit_time': data[i]['timestamp'],
                    'type': position['type'],
                    'entry': position['entry'],
                    'exit': exit_price,
                    'lot': position['lot'],
                    'pnl': pnl,
                    'balance': balance,
                    'day_pnl': day_pnl,
                    'day_loss_count': day_loss_count
                })
                position = None
    df = pd.DataFrame(results)
    df.to_csv("backtest_trades.csv", index=False)
    print(df)
    print(f"Final balance: {balance:.2f} | Return: {((balance-initial_balance)/initial_balance)*100:.2f}%")
    return df

if __name__ == "__main__":
    data = pd.read_csv("history_data.csv")
    data = data.to_dict('records')
    backtest_dual_ema_atr(
        data,
        initial_balance=10000,
        fast=5,
        slow=15,
        atr_mult_sl=0.5,
        atr_mult_tp=3.0,
        contract_size=100,
        daily_max_loss=500
    )