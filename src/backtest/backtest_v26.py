import pandas as pd
import numpy as np

pd.set_option('future.no_silent_downcasting', True)

class NYOverlapCorrectedEngine:
    def __init__(self, data_path="history_data.csv"):
        self.data_path = data_path
        
        # Risk & Portfolio Parameters
        self.risk_pct = 0.0075      # 0.75% risk per trade
        self.contract_size = 100
        
        # 2.5-pip maximum slippage filter applied as fixed frictional cost
        self.total_cost_pips = 2.5 
        
        # Asymmetric Target 
        self.target_rr = 1.1        

    def load_and_prepare(self):
        try:
            df = pd.read_csv(self.data_path)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.sort_values('timestamp', inplace=True)
            df.reset_index(drop=True, inplace=True)
            return df
        except FileNotFoundError:
            print(f"File {self.data_path} not found. Returning dummy structure.")
            return pd.DataFrame()

    def engineer_features(self, df):
        # 1. 2 Standard Deviation for Dynamic Stop Loss
        df['std_20'] = df['close'].rolling(window=20).std()
        df['stop_distance'] = df['std_20'] * 2.0

        # 2. Exact H4 Session Trend Direction (16:00 to 20:00 HKT block)
        # At the 19:45 evaluation candle, shift(15) exactly targets the 16:00 candle open.
        df['h4_open'] = df['open'].shift(15)
        df['h4_trend_up'] = df['close'] > df['h4_open']
        df['h4_trend_down'] = df['close'] < df['h4_open']

        df['date_str'] = df['timestamp'].dt.strftime('%Y-%m-%d')
        df['hour'] = df['timestamp'].dt.hour
        df['minute'] = df['timestamp'].dt.minute
        
        # 3. Precision Execution: Evaluate exactly at 19:45 HKT to execute at 20:00 HKT
        time_trigger = (df['hour'] == 19) & (df['minute'] == 45)

        buy_cond = time_trigger & df['h4_trend_up']
        sell_cond = time_trigger & df['h4_trend_down']
        
        # Shift signals to strictly execute on the 20:00 HKT open
        df['signal_buy'] = buy_cond.shift(1).fillna(False).astype(bool)
        df['signal_sell'] = sell_cond.shift(1).fillna(False).astype(bool)
        
        # Pass stop distance forward
        df['ref_sl_dist'] = df['stop_distance'].shift(1)
        
        return df.dropna()

    def run_period(self, df_period, initial_balance=100000):
        balance = initial_balance
        peak_balance = balance
        max_dd = 0
        trades = []
        last_traded_date = None
        position = None

        for row in df_period.itertuples():
            ts = row.timestamp
            current_date = row.date_str
            
            # --- Trade Management ---
            if position is not None:
                high = row.high
                low = row.low
                exit_price = None

                if position['type'] == 'BUY':
                    if low <= position['sl']: exit_price = position['sl']
                    elif high >= position['tp']: exit_price = position['tp']

                elif position['type'] == 'SELL':
                    if high >= position['sl']: exit_price = position['sl']
                    elif low <= position['tp']: exit_price = position['tp']

                if exit_price is not None:
                    pnl_pips = (exit_price - position['entry']) if position['type'] == 'BUY' else (position['entry'] - exit_price)
                    pnl_pips = (pnl_pips * 100) - self.total_cost_pips 
                    
                    pnl_cash = (pnl_pips / 100) * self.contract_size * position['lot']
                    balance += pnl_cash
                    
                    if balance > peak_balance: peak_balance = balance
                    dd = (peak_balance - balance) / peak_balance
                    if dd > max_dd: max_dd = dd
                    
                    trades.append({
                        'entry_time': position['time'], 'exit_time': ts,
                        'pnl': pnl_cash, 'r_multiple': pnl_cash / (initial_balance * self.risk_pct),
                        'sl_pips': position['sl_dist'] * 100
                    })
                    position = None

            # --- Entry Logic (Strictly 1 Trade Per Day) ---
            if position is None and last_traded_date != current_date:
                sl_distance = row.ref_sl_dist if row.ref_sl_dist > 0 else 0.20
                
                # Minimum SL protection to ensure viability against friction
                if (sl_distance * 100) <= self.total_cost_pips:
                    continue
                
                lot = (balance * self.risk_pct) / (sl_distance * self.contract_size)
                
                if row.signal_buy:
                    entry = row.open 
                    position = {
                        'type': 'BUY', 'entry': entry, 
                        'sl': entry - sl_distance, 'tp': entry + (sl_distance * self.target_rr), 
                        'lot': lot, 'time': ts, 'sl_dist': sl_distance
                    }
                    last_traded_date = current_date
                    
                elif row.signal_sell:
                    entry = row.open
                    position = {
                        'type': 'SELL', 'entry': entry, 
                        'sl': entry + sl_distance, 'tp': entry - (sl_distance * self.target_rr), 
                        'lot': lot, 'time': ts, 'sl_dist': sl_distance
                    }
                    last_traded_date = current_date

        return trades, balance, max_dd

    def calculate_metrics(self, trades, initial_balance, final_balance, max_dd, period_name):
        if not trades:
            print(f"\n[{period_name}] NO VALID EDGE FOUND - 0 trades executed.")
            return

        df_t = pd.DataFrame(trades)
        wins = df_t[df_t['pnl'] > 0]
        losses = df_t[df_t['pnl'] <= 0]
        
        win_rate = len(wins) / len(trades) if len(trades) > 0 else 0
        pf = abs(wins['pnl'].sum() / losses['pnl'].sum()) if len(losses) > 0 and losses['pnl'].sum() != 0 else float('inf')
        total_r = df_t['r_multiple'].sum()
        roi = (final_balance - initial_balance) / initial_balance
        
        print(f"\n================ {period_name} RESULTS ================")
        print(f"Trades: {len(trades)} | Win Rate: {win_rate*100:.2f}%")
        print(f"Total ROI: {roi*100:.2f}% | Max Drawdown: {max_dd*100:.2f}%")
        print(f"Profit Factor: {pf:.2f} | Total R: {total_r:.2f}R | Expectancy: {total_r/len(trades):.2f}R")
        print(f"Average Winner: {wins['r_multiple'].mean() if not wins.empty else 0:.2f}R | Average Loser: {losses['r_multiple'].mean() if not losses.empty else 0:.2f}R")
        
        if total_r <= 0 or pf < 1.0:
            print("STATUS: NO VALID EDGE FOUND in this sample. (Negative Expectancy or PF < 1)")
        elif len(trades) < 30:
            print("STATUS: EDGE SURVIVED, but sample size is too small for statistical significance.")
        else:
            print("STATUS: Edge survived sample validation with statistical significance.")

    def run_split_validation(self):
        df = self.load_and_prepare()
        if df.empty: return
        df = self.engineer_features(df)
        
        print("Starting Corrected NY Overlap Validation (80/20 Chronological Split)")
        
        split_idx = int(len(df) * 0.8)
        train_df = df.iloc[:split_idx]
        test_df = df.iloc[split_idx:]
        
        t_trades, t_bal, t_dd = self.run_period(train_df)
        self.calculate_metrics(t_trades, 100000, t_bal, t_dd, "TRAIN (80% Chronological)")
        
        ts_trades, ts_bal, ts_dd = self.run_period(test_df)
        self.calculate_metrics(ts_trades, 100000, ts_bal, ts_dd, "BLIND TEST (20% Chronological)")

if __name__ == "__main__":
    runner = NYOverlapCorrectedEngine()
    runner.run_split_validation()