import math
import numpy as np
import pandas as pd

# --- Core Strategy Constants ---
fast = 5
slow = 20
contract_size = 100  # Adjust for broker specs (e.g., 100 for XAUUSD)
spread = 0.00015
RISK_PER_TRADE_PCT = 0.0075
COMMISSION_PER_LOT = 0.00


def calculate_atr(highs, lows, closes, window=14):
    tr1 = highs - lows
    tr2 = np.zeros(len(closes))
    tr3 = np.zeros(len(closes))
    tr2[1:] = np.abs(highs[1:] - closes[:-1])
    tr3[1:] = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    return pd.Series(tr).rolling(window=window).mean().values


def current_ts_is_time(ts, hour, minute):
    return ts.hour == hour and ts.minute == minute


def backtest_dual_filtered(data, initial_balance=50000):
    balance = initial_balance
    lowest_balance = balance
    position = None
    trades = []

    timestamps = [pd.to_datetime(bar["timestamp"]) for bar in data]
    df_temp = pd.DataFrame(data)

    # Indicator Calculations
    df_temp["atr"] = calculate_atr(
        df_temp["high"].values,
        df_temp["low"].values,
        df_temp["close"].values,
        window=14,
    )
    df_temp["sigma"] = df_temp["close"].rolling(window=20).std()

    # Rolling 24-Hour High & Low (96 M15 bars = 24 hours)
    df_temp["24h_high"] = df_temp["high"].rolling(window=96).max()
    df_temp["24h_low"] = df_temp["low"].rolling(window=96).min()

    atrs = df_temp["atr"].values
    sigmas = df_temp["sigma"].values
    highs_24h = df_temp["24h_high"].values
    lows_24h = df_temp["24h_low"].values

    print(
        f"Initiating Dual-Filtered Backtest over {len(data)} periods..."
    )

    for i in range(96, len(data)):  # Warm-up index for rolling calculations
        ts = timestamps[i]
        curr_candle = data[i]

        # === Manage Open Position ===
        if position is not None:
            high = curr_candle["high"]
            low = curr_candle["low"]
            exit_price = None
            exit_reason = None

            if position["type"] == "BUY":
                if low <= position["sl"]:
                    exit_price = position["sl"]
                    exit_reason = "LOSS"
                elif high >= position["tp"]:
                    exit_price = position["tp"]
                    exit_reason = "WIN"

            else:  # SELL
                if high >= position["sl"]:
                    exit_price = position["sl"]
                    exit_reason = "LOSS"
                elif low <= position["tp"]:
                    exit_price = position["tp"]
                    exit_reason = "WIN"

            if exit_price is not None:
                if position["type"] == "BUY":
                    gross_pnl = (
                        (exit_price - position["entry"])
                        * contract_size
                        * position["lot"]
                    )
                else:
                    gross_pnl = (
                        (position["entry"] - exit_price)
                        * contract_size
                        * position["lot"]
                    )

                commission_cost = position["lot"] * COMMISSION_PER_LOT
                pnl = gross_pnl - commission_cost

                balance += pnl
                lowest_balance = min(lowest_balance, balance)

                trades.append(
                    {
                        "type": position["type"],
                        "entry": position["entry"],
                        "exit": exit_price,
                        "pnl": pnl,
                        "lot": position["lot"],
                        "reason": exit_reason,
                        "entry_ts": position["entry_ts"],
                        "exit_ts": ts,
                        "duration": ts - position["entry_ts"],
                    }
                )
                position = None

        # === Entry Logic at 20:00 ===
        if current_ts_is_time(ts, hour=20, minute=0) and position is None:
            current_price = curr_candle["open"]

            # --- FILTER 1: Daily Range Position (Middle 30%) ---
            h24_high = highs_24h[i - 1]
            h24_low = lows_24h[i - 1]
            range_24h = h24_high - h24_low

            if range_24h > 0:
                range_position = (current_price - h24_low) / range_24h
                if 0.35 <= range_position <= 0.65:
                    continue  # Skip middle-range consolidation

            # --- FILTER 2: Asian Session Range Expansion ---
            # 08:00 HKT is index (i - 48), 15:00 HKT is index (i - 20)
            asia_bars = data[i - 48 : i - 20]
            if len(asia_bars) == 28:
                asia_high = max(b["high"] for b in asia_bars)
                asia_low = min(b["low"] for b in asia_bars)
                asia_range = asia_high - asia_low
                asia_mid = (asia_high + asia_low) / 2

                if asia_range > 0:
                    expansion_ratio = abs(current_price - asia_mid) / asia_range
                    if expansion_ratio > 2.0:
                        continue  # Skip overextended moves

            # --- Direction & Risk Sizing ---
            # 16 M15 bars represent the preceding 4-hour candle (16:00-20:00)
            h4_open = data[i - 16]["open"]
            h4_close = data[i - 1]["close"]
            signal = 1 if h4_close > h4_open else -1

            atr_val = atrs[i - 1]
            sigma_val = sigmas[i - 1]
            if np.isnan(atr_val) or np.isnan(sigma_val):
                continue

            sl_dist = max(atr_val, sigma_val * 2)
            tp_dist = sl_dist * 1.2
        

            risk_cash = balance * RISK_PER_TRADE_PCT
            lot_raw = risk_cash / (sl_dist * contract_size)
            lot = max(0.01, math.floor(lot_raw * 100) / 100)

            if signal == 1:  # BUY
                entry = current_price + spread
                position = {
                    "type": "BUY",
                    "entry": entry,
                    "sl": entry - sl_dist + spread,
                    "tp": entry + tp_dist,
                    "lot": lot,
                    "entry_ts": ts,
                }
            elif signal == -1:  # SELL
                entry = current_price - spread
                position = {
                    "type": "SELL",
                    "entry": entry,
                    "sl": entry + sl_dist - spread,
                    "tp": entry - tp_dist,
                    "lot": lot,
                    "entry_ts": ts,
                }

    # === Performance Report ===
    if not trades:
        print("No trades executed.")
        return

    wins = [t for t in trades if t["reason"] == "WIN"]
    losses = [t for t in trades if t["reason"] == "LOSS"]

    win_count = len(wins)
    loss_count = len(losses)
    total_trades = len(trades)

    total_pnl = sum(t["pnl"] for t in trades)
    avg_win = sum(t["pnl"] for t in wins) / win_count if wins else 0
    avg_loss = abs(sum(t["pnl"] for t in losses) / loss_count) if losses else 0
    actual_rr = avg_win / avg_loss if avg_loss > 0 else 0

    avg_duration = sum((t["duration"] for t in trades), pd.Timedelta(0)) / len(
        trades
    )

    print(
        "\n================ DUAL-FILTERED PERFORMANCE (DAILY RANGE + ASIA EXPANSION) ================"
    )
    print(f"Total Transactions:       {total_trades}")
    print(
        f"Winning Trades:           {win_count} ({(win_count / total_trades) * 100:.1f}%)"
    )
    print(
        f"Losing Trades:            {loss_count} ({(loss_count / total_trades) * 100:.1f}%)"
    )
    print(f"Avg Win:                  ${avg_win:,.2f}")
    print(f"Avg Loss:                 -${avg_loss:,.2f}")
    print(f"Actual Risk:Reward:       1 : {actual_rr:.2f}")
    print(f"Final Balance:            ${balance:,.2f}")
    print(
        f"Net Return:               {((balance - initial_balance) / initial_balance) * 100:,.2f}%"
    )
    print(
        f"Maximum Drawdown:         ${initial_balance - lowest_balance:,.2f}"
    )
    print(f"Total Net P&L:            ${total_pnl:,.2f}")
    print(f"Average Trade Duration:   {avg_duration}")
    print(
        "=========================================================================================="
    )


if __name__ == "__main__":
    try:
        df = pd.read_csv("history_data.csv")
        data = df.to_dict("records")
        backtest_dual_filtered(data)
    except FileNotFoundError:
        print("Error: 'history_data.csv' not found in current directory.")
    except Exception as e:
        print(f"Error during backtest: {e}")