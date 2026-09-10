import pandas as pd
import numpy as np
import math

# --- Core Strategy Constants ---
contract_size = 100
spread = 0.00015
RISK_PER_TRADE_PCT = 0.0075
COMMISSION_PER_LOT = 0.00

# --- Position sizing control ---
USE_MAX_LOT_CAP = True
MAX_LOT_ALLOWED = 4.00

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

def backtest_time_based_single(data, initial_balance=50000):
    balance = initial_balance
    lowest_balance = balance
    peak_balance = balance
    max_drawdown = 0
    position = None
    trades = []
    capped_trades = 0

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

            if position['type'] == 'BUY':
                if low <= position['sl']:
                    exit_price = position['sl']
                    exit_reason = "LOSS"
                elif high >= position['tp']:
                    exit_price = position['tp']
                    exit_reason = "WIN"
            else:  # SELL
                if high >= position['sl']:
                    exit_price = position['sl']
                    exit_reason = "LOSS"
                elif low <= position['tp']:
                    exit_price = position['tp']
                    exit_reason = "WIN"

            if exit_price is not None:
                if position['type'] == 'BUY':
                    gross_pnl = (exit_price - position['entry']) * contract_size * position['lot']
                else:
                    gross_pnl = (position['entry'] - exit_price) * contract_size * position['lot']

                commission_cost = position['lot'] * COMMISSION_PER_LOT
                pnl = gross_pnl - commission_cost

                balance += pnl
                lowest_balance = min(lowest_balance, balance)
                peak_balance = max(peak_balance, balance)
                max_drawdown = max(max_drawdown, peak_balance - balance)

                exit_ts = ts
                duration = exit_ts - position['entry_ts']

                trades.append({
                    'type': position['type'],
                    'entry': position['entry'],
                    'exit': exit_price,
                    'pnl': pnl,
                    'lot': position['lot'],
                    'raw_lot': position['raw_lot'],
                    'lot_capped': position['lot_capped'],
                    'reason': exit_reason,
                    'entry_ts': position['entry_ts'],
                    'exit_ts': exit_ts,
                    'duration': duration,
                    'sl_dist': position['sl_dist']
                })
                position = None

        # === Entry Logic at 20:00 ===
        if current_ts_is_time(ts, hour=20, minute=0) and position is None:
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
            raw_lot = max(0.01, math.floor(lot_raw * 100) / 100)

            lot = raw_lot
            lot_capped = False

            if USE_MAX_LOT_CAP and lot > MAX_LOT_ALLOWED:
                lot = MAX_LOT_ALLOWED
                lot_capped = True
                capped_trades += 1

            current_price = curr_candle['open']

            if signal == 1:  # BUY
                entry = current_price + spread
                position = {
                    'type': 'BUY',
                    'entry': entry,
                    'sl': entry - sl_dist,
                    'tp': entry + tp_dist,
                    'lot': lot,
                    'raw_lot': raw_lot,
                    'lot_capped': lot_capped,
                    'sl_dist': sl_dist,
                    'entry_ts': ts
                }
            else:  # SELL
                entry = current_price - spread
                position = {
                    'type': 'SELL',
                    'entry': entry,
                    'sl': entry + sl_dist,
                    'tp': entry - tp_dist,
                    'lot': lot,
                    'raw_lot': raw_lot,
                    'lot_capped': lot_capped,
                    'sl_dist': sl_dist,
                    'entry_ts': ts
                }

    # === Final Performance Report ===
    if len(trades) == 0:
        print("No trades.")
        return

    wins = [t for t in trades if t['reason'] == 'WIN']
    losses = [t for t in trades if t['reason'] == 'LOSS']

    capped = [t for t in trades if t['lot_capped']]
    uncapped = [t for t in trades if not t['lot_capped']]

    total_trades = len(trades)
    win_trades = len(wins)
    lose_trades = len(losses)

    total_pnl = sum(t['pnl'] for t in trades)
    avg_win = sum(t['pnl'] for t in wins) / win_trades if wins else 0
    avg_loss = abs(sum(t['pnl'] for t in losses) / lose_trades) if losses else 0
    actual_rr = avg_win / avg_loss if avg_loss > 0 else 0
    avg_duration = sum((t['duration'] for t in trades), pd.Timedelta(0)) / len(trades)

    capped_wins = sum(1 for t in capped if t['reason'] == 'WIN')
    capped_win_rate = (capped_wins / len(capped) * 100) if capped else 0

    uncapped_wins = sum(1 for t in uncapped if t['reason'] == 'WIN')
    uncapped_win_rate = (uncapped_wins / len(uncapped) * 100) if uncapped else 0

    print("\n================ TIME-BASED SINGLE ASSET PERFORMANCE ================")
    print(f"Total Transactions:       {total_trades}")
    print(f"Winning Trades:           {win_trades} ({(win_trades / total_trades) * 100:.1f}%)")
    print(f"Losing Trades:            {lose_trades} ({(lose_trades / total_trades) * 100:.1f}%)")
    print(f"Avg Win:                  ${avg_win:,.2f}")
    print(f"Avg Loss:                 -${avg_loss:,.2f}")
    print(f"Actual Risk:Reward:       1 : {actual_rr:.2f}")
    print(f"Final Balance:            ${balance:,.2f}")
    print(f"Net Return:               {((balance - initial_balance) / initial_balance) * 100:,.2f}%")
    print(f"Maximum Drawdown:         ${max_drawdown:,.2f}")
    print(f"Total Net P&L:            ${total_pnl:,.2f}")
    print(f"Average Trade Duration:   {avg_duration}")

    print("\n---------------- Lot Cap Analysis ----------------")
    print(f"Max Lot Allowed:          {MAX_LOT_ALLOWED:.2f}")
    print(f"Capped Trades Count:      {len(capped)}")
    print(f"Capped Trades Win Rate:   {capped_win_rate:.1f}%")
    print(f"Uncapped Trades Count:    {len(uncapped)}")
    print(f"Uncapped Trades Win Rate: {uncapped_win_rate:.1f}%")
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