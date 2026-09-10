import pandas as pd
import numpy as np
import math

# --- Core Strategy Constants ---
contract_size = 100
spread = 0.00015
RISK_PER_TRADE_PCT = 0.0075
COMMISSION_PER_LOT = 0.00

# --- New filter: only trade strong H4 candles ---
USE_H4_BODY_FILTER = True
MIN_H4_BODY_RATIO = 0.55   # test: 0.50 / 0.55 / 0.60

def calculate_atr(highs, lows, closes, window=14):
    tr = np.zeros(len(closes))
    tr1 = highs - lows
    tr2 = np.zeros(len(closes))
    tr3 = np.zeros(len(closes))
    tr2[1:] = np.abs(highs[1:] - closes[:-1])
    tr3[1:] = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    atr = pd.Series(tr).rolling(window=window).mean().values
    return atr

def current_ts_is_time(ts, hour, minute):
    return ts.hour == hour and ts.minute == minute

def get_h4_signal_with_body_filter(data, i, min_body_ratio=0.55):
    """
    Build the previous completed H4 candle from the last 16 M15 candles.
    Returns:
        1  = bullish valid candle
       -1  = bearish valid candle
        0  = invalid / too weak / cannot determine
    """
    h4_bars = data[i-16:i]
    if len(h4_bars) < 16:
        return 0

    h4_open = h4_bars[0]['open']
    h4_close = h4_bars[-1]['close']
    h4_high = max(bar['high'] for bar in h4_bars)
    h4_low = min(bar['low'] for bar in h4_bars)

    h4_range = h4_high - h4_low
    h4_body = abs(h4_close - h4_open)

    if h4_range <= 0:
        return 0

    body_ratio = h4_body / h4_range

    if body_ratio < min_body_ratio:
        return 0

    if h4_close > h4_open:
        return 1
    elif h4_close < h4_open:
        return -1
    else:
        return 0

def backtest_time_based_single(data, initial_balance=50000):
    balance = initial_balance
    lowest_balance = balance
    position = None
    trades = []

    timestamps = [pd.to_datetime(bar['timestamp']) for bar in data]

    df_temp = pd.DataFrame(data)
    df_temp['atr'] = calculate_atr(
        df_temp['high'].values,
        df_temp['low'].values,
        df_temp['close'].values,
        window=14
    )
    df_temp['sigma'] = df_temp['close'].rolling(window=20).std()

    atrs = df_temp['atr'].values
    sigmas = df_temp['sigma'].values

    print(f"Initiating Time-Based Single Asset Backtest over {len(data)} periods...")

    for i in range(50, len(data)):
        ts = timestamps[i]
        curr_candle = data[i]

        # === Manage Open Position ===
        if position is not None:
            high = curr_candle['high']
            low = curr_candle['low']
            exit_price = None
            exit_reason = None

            be_trigger_dist = position['sl_dist'] * 100000

            if position['type'] == 'BUY':
                if not position.get('be_triggered', False) and high >= position['entry'] + be_trigger_dist:
                    position['sl'] = position['entry'] + spread
                    position['be_triggered'] = True

                if low <= position['sl']:
                    exit_price = position['sl']
                    exit_reason = "SCRATCH" if position.get('be_triggered', False) else "LOSS"
                elif high >= position['tp']:
                    exit_price = position['tp']
                    exit_reason = "WIN"

            else:  # SELL
                if not position.get('be_triggered', False) and low <= position['entry'] - be_trigger_dist:
                    position['sl'] = position['entry'] - spread
                    position['be_triggered'] = True

                if high >= position['sl']:
                    exit_price = position['sl']
                    exit_reason = "SCRATCH" if position.get('be_triggered', False) else "LOSS"
                elif low <= position['tp']:
                    exit_price = position['tp']
                    exit_reason = "WIN"

            if exit_price is not None:
                if position['type'] == 'BUY':
                    gross_pnl = (exit_price - position['entry']) * contract_size * position['lot']
                else:
                    gross_pnl = (position['entry'] - exit_price) * contract_size * position['lot']

                commission_cost = position['lot'] * COMMISSION_PER_LOT
                pnl = gross_pnl - commission_cost if exit_reason in ["WIN", "LOSS"] else -commission_cost

                balance += pnl
                lowest_balance = min(lowest_balance, balance)

                exit_ts = ts
                duration = exit_ts - position['entry_ts']

                trades.append({
                    'type': position['type'],
                    'entry': position['entry'],
                    'exit': exit_price,
                    'pnl': pnl,
                    'lot': position['lot'],
                    'reason': exit_reason,
                    'entry_ts': position['entry_ts'],
                    'exit_ts': exit_ts,
                    'duration': duration
                })
                position = None

        # === Entry Logic at 20:00 ===
        if current_ts_is_time(ts, hour=20, minute=0) and position is None:
            if USE_H4_BODY_FILTER:
                signal = get_h4_signal_with_body_filter(data, i, MIN_H4_BODY_RATIO)
            else:
                h4_open = data[i-16]['open']
                h4_close = data[i-1]['close']
                if h4_close > h4_open:
                    signal = 1
                elif h4_close < h4_open:
                    signal = -1
                else:
                    signal = 0

            if signal == 0:
                continue

            atr_val = atrs[i-1]
            sigma_val = sigmas[i-1]
            if np.isnan(atr_val) or np.isnan(sigma_val):
                continue

            atr_sl = atr_val
            sd_sl = sigma_val * 2
            sl_dist = max(atr_sl, sd_sl)
            tp_dist = sl_dist * 1.1

            risk_cash = balance * RISK_PER_TRADE_PCT
            lot_raw = risk_cash / (sl_dist * contract_size)
            lot = max(0.01, math.floor(lot_raw * 100) / 100)

            current_price = curr_candle['open']

            if signal == 1:  # BUY
                entry = current_price + spread
                position = {
                    'type': 'BUY',
                    'entry': entry,
                    'sl': entry - sl_dist + spread,
                    'tp': entry + tp_dist,
                    'lot': lot,
                    'sl_dist': sl_dist,
                    'be_triggered': False,
                    'entry_ts': ts
                }

            else:  # SELL
                entry = current_price - spread
                position = {
                    'type': 'SELL',
                    'entry': entry,
                    'sl': entry + sl_dist - spread,
                    'tp': entry - tp_dist,
                    'lot': lot,
                    'sl_dist': sl_dist,
                    'be_triggered': False,
                    'entry_ts': ts
                }

    # === Final Performance Report ===
    if len(trades) == 0:
        print("No trades.")
        return

    wins = [t for t in trades if t['reason'] == 'WIN']
    losses = [t for t in trades if t['reason'] == 'LOSS']
    scratches = [t for t in trades if t['reason'] == 'SCRATCH']

    win_trades = len(wins)
    lose_trades = len(losses)
    scratch_trades = len(scratches)
    total_trades = len(trades)

    total_pnl = sum(t['pnl'] for t in trades)
    avg_win = sum(t['pnl'] for t in wins) / win_trades if wins else 0
    avg_loss = abs(sum(t['pnl'] for t in losses) / lose_trades) if losses else 0
    actual_rr = avg_win / avg_loss if avg_loss > 0 else 0

    avg_duration = sum((t['duration'] for t in trades), pd.Timedelta(0)) / len(trades)

    print("\n================ TIME-BASED SINGLE ASSET PERFORMANCE ================")
    print(f"Total Transactions:       {total_trades}")
    print(f"Winning Trades:           {win_trades} ({(win_trades / total_trades) * 100:.1f}%)")
    print(f"Losing Trades:            {lose_trades} ({(lose_trades / total_trades) * 100:.1f}%)")
    print(f"Break-Even (Scratches):   {scratch_trades} ({(scratch_trades / total_trades) * 100:.1f}%)")
    print(f"Avg Win:                  ${avg_win:,.2f}")
    print(f"Avg Loss:                 -${avg_loss:,.2f}")
    print(f"Actual Risk:Reward:       1 : {actual_rr:.2f}")
    print(f"Final Balance:            ${balance:,.2f}")
    print(f"Net Return:               {((balance - initial_balance) / initial_balance) * 100:,.2f}%")
    print(f"Maximum Drawdown:         ${initial_balance - lowest_balance:,.2f}")
    print(f"Total Net P&L:            ${total_pnl:,.2f}")
    print(f"Average Trade Duration:   {avg_duration}")
    print("===============================================================================")

if __name__ == "__main__":
    try:
        df = pd.read_csv("history_data.csv")
        data = df.to_dict('records')
        backtest_time_based_single(data)
    except FileNotFoundError:
        print("Error: 'history_data.csv' not found in current directory.")
    except Exception as e:
        print(f"Error during backtest: {e}")