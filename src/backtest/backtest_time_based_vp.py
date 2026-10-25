import pandas as pd
import numpy as np
import math

# ==============================================================================
#                 OPTIMAL CONFIG + KALMAN FILTER INTEGRATION
# ==============================================================================
RISK_PER_TRADE_PCT = 0.05
TARGET_RR_MULTIPLIER = 1.5
VP_LOOKBACK_BARS = 96
VP_TARGET_VOL_PCT = 0.68
VP_NUM_BINS = 50
SD_MULTIPLIER = .7
USE_VOLUME_PROFILE = True

# --- Kalman Filter Parameters ---
KALMAN_PROCESS_NOISE = 1e-5     # Q: Low Q = smoother trend; High Q = tracks price tighter
KALMAN_MEASURE_NOISE = 1e-3     # R: High R = filters out M15 spread/wick noise
# ==============================================================================

CONTRACT_SIZE = 100
SPREAD = 0.00015 
COMMISSION_PER_LOT = 0.00    
move_sl_to_be = False  # Enable breakeven stop-loss refinement

def run_kalman_filter_2D(closes_slice, process_noise=1e-5, measurement_noise=1e-3):
    """
    Tuned 2-State Kalman Filter:
    - Higher Q/R ratio (10.0) reduces phase lag and captures immediate H4 momentum.
    - Extended slice allows full convergence of Covariance Matrix P before evaluating index i-1.
    """
    F = np.array([[1.0, 1.0],
                  [0.0, 1.0]])
    H = np.array([[1.0, 0.0]])
    
    Q = np.eye(2) * process_noise
    R = np.array([[measurement_noise]])
    
    # Initialize at start of lookback
    x = np.array([[closes_slice[0]], 
                  [0.0]])
    P = np.eye(2) * 1.0
    
    for z in closes_slice:
        # Predict
        x = F @ x
        P = F @ P @ F.T + Q
        
        # Update
        y = z - (H @ x)[0, 0]
        S = H @ P @ H.T + R
        K = P @ H.T / S[0, 0]
        
        x = x + K * y
        P = (np.eye(2) - K @ H) @ P
        
    estimated_drift = x[1, 0]
    return estimated_drift

def calculate_atr(highs, lows, closes, window=14):
    tr1 = highs - lows
    tr2 = np.zeros(len(closes))
    tr3 = np.zeros(len(closes))
    tr2[1:] = np.abs(highs[1:] - closes[:-1])
    tr3[1:] = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    return pd.Series(tr).rolling(window=window).mean().values

def calculate_volume_profile(window_df, num_bins=VP_NUM_BINS):
    price_min = window_df['low'].min()
    price_max = window_df['high'].max()
    
    if price_max == price_min:
        last_close = window_df['close'].iloc[-1]
        return last_close, last_close, last_close
    
    vol_col = 'tick_volume' if 'tick_volume' in window_df.columns else ('volume' if 'volume' in window_df.columns else None)
    volumes = window_df[vol_col].values if vol_col else np.ones(len(window_df))
    
    bins = np.linspace(price_min, price_max, num_bins + 1)
    closes = window_df['close'].values
    
    bin_indices = np.clip(np.digitize(closes, bins) - 1, 0, num_bins - 1)
    
    bin_volumes = np.zeros(num_bins)
    for idx, vol in zip(bin_indices, volumes):
        bin_volumes[idx] += vol
        
    poc_idx = np.argmax(bin_volumes)
    poc = (bins[poc_idx] + bins[poc_idx + 1]) / 2.0
    
    total_vol = np.sum(bin_volumes)
    target_vol = total_vol * VP_TARGET_VOL_PCT  
    
    sorted_bin_indices = np.argsort(bin_volumes)[::-1]
    cum_vol = 0
    selected_bins = []
    
    for idx in sorted_bin_indices:
        cum_vol += bin_volumes[idx]
        selected_bins.append(idx)
        if cum_vol >= target_vol:
            break
            
    val = bins[min(selected_bins)]
    vah = bins[max(selected_bins) + 1]
    
    return vah, val, poc


def print_entry_slot_win_summary(trades):
    trades_df = pd.DataFrame(trades)
    if trades_df.empty:
        print("No closed trades to analyze by entry slot.")
        return

    trades_df['entry_slot'] = pd.to_datetime(trades_df['entry_ts']).dt.strftime('%H:%M')
    slot_summary = (
        trades_df.groupby('entry_slot')
        .agg(
            total_trades=('reason', 'size'),
            winning_trades=('reason', lambda x: (x == 'WIN').sum()),
            losing_trades=('reason', lambda x: (x == 'LOSS').sum()),
        )
        .reset_index()
    )

    slot_summary['win_rate_pct'] = (slot_summary['winning_trades'] / slot_summary['total_trades']) * 100
    ranked = slot_summary.sort_values(
        by=['winning_trades', 'win_rate_pct', 'total_trades'],
        ascending=[False, False, False],
    )

    best_slot = ranked.iloc[0]
    print("\n================ ENTRY SLOT WIN ANALYSIS (15M) ================")
    print(
        f"Best winning slot: {best_slot['entry_slot']} | "
        f"Wins: {int(best_slot['winning_trades'])} / {int(best_slot['total_trades'])} "
        f"({best_slot['win_rate_pct']:.1f}%)"
    )

    for _, row in ranked.iterrows():
        print(
            f"{row['entry_slot']} -> Wins: {int(row['winning_trades'])}, "
            f"Losses: {int(row['losing_trades'])}, "
            f"Total: {int(row['total_trades'])}, "
            f"WinRate: {row['win_rate_pct']:.1f}%"
        )
    print("================================================================")

def backtest_kalman_single(data, initial_balance=100000):
    balance = initial_balance
    lowest_balance = balance
    position = None
    trades = []
    skipped_trades = 0
    
    df_temp = pd.DataFrame(data)
    df_temp['atr'] = calculate_atr(df_temp['high'].values, 
                                   df_temp['low'].values, 
                                   df_temp['close'].values, 
                                   window=14)
    df_temp['sigma'] = df_temp['close'].rolling(window=20).std()
    
    timestamps = [pd.to_datetime(bar['timestamp']) for bar in data]
    atrs = df_temp['atr'].values
    sigmas = df_temp['sigma'].values
    closes = df_temp['close'].values
    
    print(f"Initiating Kalman-Filtered Single Asset Backtest over {len(data)} periods...")

    start_index = VP_LOOKBACK_BARS if USE_VOLUME_PROFILE else 16
    for i in range(start_index, len(data)):
        ts = timestamps[i]
        curr_candle = data[i]
        
        # === Manage Open Position ===
        if position is not None:
            high = curr_candle['high']
            low = curr_candle['low']
            exit_price = None
            exit_reason = None

            # Breakeven SL refinement
            one_r = abs(entry - position['sl'])
            if move_sl_to_be:
                    one_r = abs(entry - position['sl_initial']) if 'sl_initial' in position else abs(entry - position['sl'])
                    if position['type'] == 'BUY':
                        #  0.5R 移至保本
                        if high >= entry +  one_r and position['sl'] < entry:
                            position['sl'] = entry
                    elif position['type'] == 'SELL':
                        if low <= entry -  one_r and position['sl'] > entry:
                            position['sl'] = entry


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
                gross_pnl = (exit_price - position['entry']) * CONTRACT_SIZE * position['lot'] if position['type'] == 'BUY' else (position['entry'] - exit_price) * CONTRACT_SIZE * position['lot']
                pnl = gross_pnl - (position['lot'] * COMMISSION_PER_LOT)
                
                balance += pnl
                lowest_balance = min(lowest_balance, balance)
                
                trades.append({
                    'type': position['type'],
                    'entry': position['entry'],
                    'exit': exit_price,
                    'pnl': pnl,
                    'lot': position['lot'],
                    'reason': exit_reason,
                    'entry_ts': position['entry_ts'],
                    'exit_ts': ts,
                    'duration': ts - position['entry_ts']
                })
                position = None

        # === Kalman-Filtered Entry Logic: scan every 15 minutes from 20:00 to 23:00 HKT ===
        if current_ts_is_scan_time(ts, start_hour=20, end_hour=23, interval_minutes=15) and position is None:
            current_price = curr_candle['open']
            kalman_lookback = closes[max(0, i - 48):i]
            kalman_lookback_log = np.log(kalman_lookback)
            drift = run_kalman_filter_2D(
                kalman_lookback_log,
                process_noise=KALMAN_PROCESS_NOISE,
                measurement_noise=KALMAN_MEASURE_NOISE
            )
            signal = 1 if drift > 0 else -1
            
            atr_val = atrs[i-1]
            sigma_val = sigmas[i-1]
            if np.isnan(atr_val) or np.isnan(sigma_val):
                continue
            
            if USE_VOLUME_PROFILE:
                lookback_window = df_temp.iloc[i-VP_LOOKBACK_BARS:i]
                vah, val, _ = calculate_volume_profile(lookback_window, num_bins=VP_NUM_BINS)

                if signal == 1 and current_price <= vah:
                    skipped_trades += 1
                    continue
                elif signal == -1 and current_price >= val:
                    skipped_trades += 1
                    continue
            
            sl_dist = max(atr_val, sigma_val * SD_MULTIPLIER)
            tp_dist = sl_dist * TARGET_RR_MULTIPLIER
            
            risk_cash = balance * RISK_PER_TRADE_PCT
            lot_raw = risk_cash / (sl_dist * CONTRACT_SIZE)
            lot = max(0.01, math.floor(lot_raw * 100) / 100)  
            
            if signal == 1:  # BUY
                entry = current_price + SPREAD
                position = {
                    'type': 'BUY',
                    'entry': entry,
                    'sl': entry - sl_dist + SPREAD,
                    'tp': entry + tp_dist, 
                    'lot': lot,
                    'sl_dist': sl_dist,
                    'entry_ts': ts
                }
            elif signal == -1:  # SELL
                entry = current_price - SPREAD
                position = {
                    'type': 'SELL',
                    'entry': entry,
                    'sl': entry + sl_dist - SPREAD,
                    'tp': entry - tp_dist, 
                    'lot': lot,
                    'sl_dist': sl_dist,
                    'entry_ts': ts
                }

    # === Performance Report ===
    if not trades:
        print("No trades taken.")
        return

    wins = [t for t in trades if t['reason'] == 'WIN']
    losses = [t for t in trades if t['reason'] == 'LOSS']
    
    win_trades = len(wins)
    lose_trades = len(losses)
    total_trades = len(trades)
    
    total_pnl = sum(t['pnl'] for t in trades)
    avg_win = sum(t['pnl'] for t in wins) / win_trades if wins else 0
    avg_loss = abs(sum(t['pnl'] for t in losses) / lose_trades) if losses else 0
    actual_rr = avg_win / avg_loss if avg_loss > 0 else 0
    avg_duration = sum((t['duration'] for t in trades), pd.Timedelta(0)) / len(trades)
    
    print("\n================ KALMAN-FILTERED PERFORMANCE ================")
    print(f"Total Transactions Executed: {total_trades}")
    print(f"Trades Skipped by VP Filter:  {skipped_trades}")
    print(f"Winning Trades:               {win_trades} ({(win_trades / total_trades) * 100:.1f}%)")
    print(f"Losing Trades:                {lose_trades} ({(lose_trades / total_trades) * 100:.1f}%)")
    print(f"Avg Win:                      ${avg_win:,.2f}")
    print(f"Avg Loss:                     -${avg_loss:,.2f}")
    print(f"Actual Risk:Reward:           1 : {actual_rr:.2f}")
    print(f"Final Balance:                ${balance:,.2f}")
    print(f"Net Return:                   {((balance - initial_balance) / initial_balance) * 100:,.2f}%")
    print(f"Maximum Drawdown:             ${initial_balance - lowest_balance:,.2f}")
    print(f"Total Net P&L:                ${total_pnl:,.2f}")
    print(f"Average Trade Duration:       {avg_duration}")
    print("===============================================================================")
    print_entry_slot_win_summary(trades)

def current_ts_is_scan_time(ts, start_hour=20, end_hour=23, interval_minutes=15):
    if ts.hour < start_hour or ts.hour > end_hour:
        return False

    if ts.hour == end_hour and ts.minute > 0:
        return False

    total_minutes = (ts.hour - start_hour) * 60 + ts.minute
    return total_minutes % interval_minutes == 0


def current_ts_is_time(ts, hour, minute):
    return ts.hour == hour and ts.minute == minute

if __name__ == "__main__":
    try:
        df = pd.read_csv("history_data.csv")
        data = df.to_dict('records')
        backtest_kalman_single(data)
    except FileNotFoundError:
        print("Error: 'history_data.csv' not found in current directory.")
    except Exception as e:
        print(f"Error during backtest: {e}")