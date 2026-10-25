import pandas as pd
import numpy as np

# --- Strict Prop Firm Parameters (Your True Rules) ---
risk_per_trade_pct = 0.0075  # Hard 0.75% Risk
contract_size = 100          # Standard lot contract size for EURJPY
spread = 0.015               # 1.5 pips default spread for EURJPY crossing
fixed_rrr = 1.1              # Hard 1:1.1 Risk-to-Reward Ratio

def calculate_atr(data_slice, window=14):
    """Kept to calculate your exact structural exit distance."""
    high = np.array([bar['high'] for bar in data_slice])
    low = np.array([bar['low'] for bar in data_slice])
    close = np.array([bar['close'] for bar in data_slice])
    tr = np.maximum(high[1:] - low[1:], 
                    np.abs(high[1:] - close[:-1]), 
                    np.abs(low[1:] - close[:-1]))
    atr = pd.Series(tr).rolling(window=window).mean().values
    return atr[-1]

def run_kalman_filter(prices, Q=1e-5, R=1e-3):
    """
    Recursive State-Space Estimation.
    Strips away high-frequency price noise to find the structural fair value.
    """
    x_hat = prices[0]  # Initial state estimate
    P = 1.0            # Initial estimation error covariance
    kalman_filtered = []

    for measurement in prices:
        # Time Update (Predict)
        x_hat_minus = x_hat
        P_minus = P + Q
        
        # Measurement Update (Correct)
        K_gain = P_minus / (P_minus + R)
        x_hat = x_hat_minus + K_gain * (measurement - x_hat_minus)
        P = (1 - K_gain) * P_minus
        
        kalman_filtered.append(x_hat)
        
    return np.array(kalman_filtered)

def backtest_strategy(data, initial_balance=100000):
    balance = initial_balance
    lowest_balance = balance
    position = None
    trades = []
    today_trade_count = 0

    for i in range(250, len(data)):  # 250 bars lookback window
        ts = pd.to_datetime(data[i]['timestamp'])

        # Reset daily trade limit (Adjusted to your HKT structural roll)
        if ts.hour == 1 and ts.minute == 0:
            today_trade_count = 0

        # --- 1. FX Session Variance Filter ---
        # Hard restriction: Ignore Asian Session random ranges.
        # Only scan during high-volume institutional hours (HKT 14:00 - 23:30 equivalent)
        # Assuming history data timestamp is in GMT/UTC (GMT 6 to 15 = HKT 14 to 23)
        # Change these hours if your CSV uses local HKT timestamps directly.
        if ts.hour < 6 or ts.hour > 15: 
            # If we have an active position, we still evaluate its exit during these hours
            pass 
        
        # --- 2. Entry Signal Generation Engine (Kalman Math) ---
        signal = 0
        
        # Extract recent M15 close array up to the previous candle to prevent look-ahead bias
        m15_slice = data[i-150:i] 
        close_m15 = np.array([bar['close'] for bar in m15_slice])
        
        if len(close_m15) >= 100:
            # Run State-Space estimation to isolate the continuous fair value line
            kalman_line = run_kalman_filter(close_m15, Q=1e-5, R=1e-3)
            
            curr_price = data[i]['open'] # Firing at the open of the current execution bar
            fair_value = kalman_line[-1]
            
            # Compute Rolling Residuals (Distance between raw price and Kalman line)
            residuals = close_m15[-40:] - kalman_line[-40:]
            std_residual = np.std(residuals)
            
            if std_residual > 0:
                # Calculate the exact Z-Score (Statistical deviation multiplier)
                z_score = (curr_price - fair_value) / std_residual
                
                # Only execute when price has been stretched past the 99.5% confidence limit
                if ts.hour >= 6 and ts.hour <= 15:  # Session lock applied to entry triggers
                    if z_score < -2.58:
                        signal = 1   # Statistically oversold -> BUY Mean Reversion
                    elif z_score > 2.58:
                        signal = -1  # Statistically overbought -> SELL Mean Reversion

        # --- 3. Exit Management Loop ---
        if position is not None:
            high = data[i]['high']
            low = data[i]['low']
            exit_price = None

            # Cold execution processing of structural SL/TP (SL priority checked first)
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
                pnl = (exit_price - position['entry']) * contract_size * position['lot'] if position['type'] == 'BUY' else (position['entry'] - exit_price) * contract_size * position['lot']
                balance += pnl
                lowest_balance = min(lowest_balance, balance)
                trades.append({'type': position['type'], 'pnl': pnl})
                position = None

        # --- 4. Order Execution Management Engine ---
        if position is None and signal != 0 and today_trade_count < 1:
            curr_open = data[i]['open']
            entry = curr_open + spread if signal == 1 else curr_open - spread
            
            # Pull your structural ATR distance to calculate sizing
            atr_val = calculate_atr(m15_slice, window=14)
            
            if not np.isnan(atr_val):
                # 2x Standard Deviation equivalent lookback added to ATR to safely pad news spikes
                sl_distance = atr_val * 1.5 
                
                # Capital allocation math using your true 0.75% account constraint
                risk_amount = balance * risk_per_trade_pct
                lot = risk_amount / (sl_distance * contract_size)
                
                if signal == 1:
                    sl = entry - sl_distance
                    tp = entry + (sl_distance * fixed_rrr) # Hard target lock 1.1x
                    position = {'type': 'BUY', 'entry': entry, 'sl': sl, 'tp': tp, 'lot': lot}
                elif signal == -1:
                    sl = entry + sl_distance
                    tp = entry - (sl_distance * fixed_rrr) # Hard target lock 1.1x
                    position = {'type': 'SELL', 'entry': entry, 'sl': sl, 'tp': tp, 'lot': lot}
                    
                today_trade_count += 1

    # --- Print Performance Results ---
    if len(trades) > 0:
        win_trades = sum(1 for t in trades if t['pnl'] >= 0)
        lose_trades = sum(1 for t in trades if t['pnl'] < 0)
        print(f"Total Executed Trades: {len(trades)}")
        print(f"Final Equity Balance: ${balance:.2f}")
        print(f"Profitable Trades (Wins): {win_trades}")
        print(f"Unprofitable Trades (Losses): {lose_trades}")
        print(f"Calculated Win Rate: {win_trades / len(trades) * 100:.2f}%")
        print(f"Total Return: {(balance - initial_balance) / initial_balance * 100:.2f}%")
        print(f"Maximum Balance Drawdown Floor: ${lowest_balance:.2f}")
    else:
        print("Backtest complete: Zero trades met the 2.58 Z-Score execution thresholds.")

if __name__ == "__main__":
    # Ensure your target file "history_data.csv" contains columns: timestamp, open, high, low, close
    try:
        df = pd.read_csv("history_data.csv")
        data = df.to_dict('records')
        backtest_strategy(data)
    except FileNotFoundError:
        print("Please place the script in the same directory as 'history_data.csv' to run.")