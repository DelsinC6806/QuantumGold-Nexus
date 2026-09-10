import pandas as pd

CONTRACT_SIZE = 100000
SPREAD = 0.002
RISK_PER_TRADE_PCT = 0.0075
TP_MULTIPLIER = 1.1

def backtest_pure_h4(data, initial_balance=100000):
    balance = initial_balance
    lowest_balance = balance
    position = None
    trades = []
    
    df = pd.DataFrame(data)
    timestamps = pd.to_datetime(df['timestamp'])
    
    df['h4_open'] = df['open'].shift(16)
    df['h4_close'] = df['close'].shift(1)
    df['std20'] = df['close'].rolling(20).std()

    print(f"Running Pure H4 Bias Backtest on EURJPY M15...\n")

    for i in range(100, len(data)):
        ts = timestamps.iloc[i]
        curr = data[i]

        # Close position
        if position is not None:
            high = curr['high']
            low = curr['low']
            exit_price = None
            reason = None

            if position['type'] == 'BUY':
                if low <= position['sl']:
                    exit_price = position['sl']
                    reason = "LOSS"
                elif high >= position['tp']:
                    exit_price = position['tp']
                    reason = "WIN"
            else:
                if high >= position['sl']:
                    exit_price = position['sl']
                    reason = "LOSS"
                elif low <= position['tp']:
                    exit_price = position['tp']
                    reason = "WIN"

            if exit_price is not None:
                pnl = (exit_price - position['entry']) * CONTRACT_SIZE * position['lot'] if position['type'] == 'BUY' else \
                      (position['entry'] - exit_price) * CONTRACT_SIZE * position['lot']
                balance += pnl
                lowest_balance = min(lowest_balance, balance)
                trades.append({'reason': reason})
                position = None

        # Entry at 20:00 - Pure H4 direction
        if ts.hour == 20 and ts.minute == 0 and position is None:
            h4_open = df['h4_open'].iloc[i-1]
            h4_close = df['h4_close'].iloc[i-1]
            std_val = df['std20'].iloc[i-1]

            if pd.isna(h4_open) or pd.isna(std_val):
                continue

            signal = 1 if h4_close > h4_open else -1
            sl_dist = std_val * 2.0                    # Your 2 SD
            tp_dist = sl_dist * TP_MULTIPLIER

            risk_cash = balance * RISK_PER_TRADE_PCT
            lot = max(0.01, round(risk_cash / (sl_dist * CONTRACT_SIZE), 2))

            price = curr['open']

            if signal == 1:
                entry = price + SPREAD
                position = {'type':'BUY', 'entry':entry, 'sl':entry-sl_dist, 'tp':entry+tp_dist, 'lot':lot}
            else:
                entry = price - SPREAD
                position = {'type':'SELL', 'entry':entry, 'sl':entry+sl_dist, 'tp':entry-tp_dist, 'lot':lot}

    # Results
    total = len(trades)
    wins = len([t for t in trades if t['reason'] == 'WIN'])
    win_rate = wins / total * 100 if total > 0 else 0

    print(f"\n=== PURE H4 BIAS RESULTS ===")
    print(f"Total Trades : {total}")
    print(f"Win Rate     : {win_rate:.1f}%")
    print(f"Final Balance: ${balance:,.2f} ({((balance - initial_balance)/initial_balance)*100:+.2f}%)")
    print(f"Max Drawdown : ${initial_balance - lowest_balance:,.2f}")

if __name__ == "__main__":
    df = pd.read_csv("history_data.csv")
    data = df.to_dict('records')
    backtest_pure_h4(data)