import math
import numpy as np
import pandas as pd

# ==============================================================================
# UNIFIED KALMAN + VP + REGIME SHIELD BACKTEST (ZERO LOOKAHEAD)
# ==============================================================================
BASE_RISK_PCT = 0.005       # 0.50% standard prop-safe risk
HOT_RISK_PCT = 0.0075       # 0.75% when trend efficiency is clean (no 5% blowups)
TARGET_RR = 1.50
VP_LOOKBACK = 96
VP_BINS = 50
SD_MULT = 0.7
CONTRACT_SIZE = 100         # Adjust per symbol (100 Gold, 100000 FX, 1/20 NAS100)
DEFAULT_SPREAD = 0.20       # Used only if CSV has no 'spread' column
POINT_VALUE = 0.01          # 0.01 for XAUUSD (2-digit), 0.001 for EURJPY (3-digit)


def calculate_atr(highs, lows, closes, window=14):
    tr1 = highs - lows
    tr2 = np.abs(highs[1:] - closes[:-1])
    tr3 = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(tr1, np.maximum(np.pad(tr2, (1, 0)), np.pad(tr3, (1, 0))))
    return pd.Series(tr).rolling(window=window).mean().values


def run_kalman_2d(log_prices, q=1e-5, r=1e-3):
    x = np.array([log_prices[0], 0.0])
    P = np.eye(2)
    F = np.array([[1.0, 1.0], [0.0, 1.0]])
    H = np.array([[1.0, 0.0]])
    Q = np.array([[q, 0.0], [0.0, q]])
    R = np.array([[r]])
    for z in log_prices[1:]:
        x = F @ x
        P = F @ P @ F.T + Q
        y = z - (H @ x)[0]
        S = (H @ P @ H.T + R)[0, 0]
        K = (P @ H.T)[:, 0] / S
        x = x + K * y
        P = (np.eye(2) - np.outer(K, H)) @ P
    return x[1]


def calculate_vp(window_df, num_bins=VP_BINS):
    p_min, p_max = window_df["low"].min(), window_df["high"].max()
    if p_max == p_min:
        c = window_df["close"].iloc[-1]
        return c, c
    vol_col = "tick_volume" if "tick_volume" in window_df.columns else None
    vols = window_df[vol_col].values if vol_col else np.ones(len(window_df))
    bins = np.linspace(p_min, p_max, num_bins + 1)
    idxs = np.clip(np.digitize(window_df["close"].values, bins) - 1, 0, num_bins - 1)
    bin_vols = np.bincount(idxs, weights=vols, minlength=num_bins)
    order = np.argsort(bin_vols)[::-1]
    cum, target, sel = 0.0, bin_vols.sum() * 0.68, []
    for idx in order:
        cum += bin_vols[idx]
        sel.append(idx)
        if cum >= target:
            break
    return bins[max(sel) + 1], bins[min(sel)]


def run_unified_backtest(csv_path="history_data.csv", initial_balance=100000.0):
    df = pd.read_csv(csv_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["atr"] = calculate_atr(df["high"].values, df["low"].values, df["close"].values, 14)
    df["sigma"] = df["close"].rolling(20).std()
    df["d1_sma"] = df["close"].rolling(1920, min_periods=200).mean()

    balance = initial_balance
    peak_balance = initial_balance
    max_dd_pct = 0.0
    position = None
    trades = []

    for i in range(200, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]

        # 1. Manage Open Trade (SL checked conservatively first)
        if position is not None:
            exit_price, reason = None, None
            if position["type"] == "BUY":
                if row["low"] <= position["sl"]:
                    exit_price, reason = position["sl"], "LOSS"
                elif row["high"] >= position["tp"]:
                    exit_price, reason = position["tp"], "WIN"
            else:
                if row["high"] >= position["sl"]:
                    exit_price, reason = position["sl"], "LOSS"
                elif row["low"] <= position["tp"]:
                    exit_price, reason = position["tp"], "WIN"

            if exit_price is not None:
                diff = (exit_price - position["entry"]) if position["type"] == "BUY" else (position["entry"] - exit_price)
                pnl = diff * CONTRACT_SIZE * position["lot"]
                r_mult = pnl / position["risk_cash"]
                balance += pnl
                peak_balance = max(peak_balance, balance)
                max_dd_pct = max(max_dd_pct, (peak_balance - balance) / peak_balance * 100.0)
                trades.append({"pnl": pnl, "r": r_mult, "reason": reason})
                position = None
            continue

        # 2. Entry Checks ( strictly using bars up to i-1 )
        atr_val, sigma_val, d1_val = prev["atr"], prev["sigma"], prev["d1_sma"]
        if np.isnan(atr_val) or np.isnan(sigma_val) or np.isnan(d1_val) or atr_val <= 0:
            continue

        bar_spread = (row["spread"] * POINT_VALUE) if "spread" in df.columns else DEFAULT_SPREAD

        # Shield A: Friction Trap (skip when spread eats > 10% of ATR)
        if (bar_spread / atr_val) > 0.10:
            continue

        # Shield B: Anti-Chase Exhaustion (skip parabolic signal candles > 1.8x ATR)
        if (prev["high"] - prev["low"]) > 1.8 * atr_val:
            continue

        # Shield C: Chop / Wick Asymmetry Trap (from your Blackjack script)
        w64 = df.iloc[i - 64 : i]
        wick_sum = np.sum(w64["high"].values - w64["low"].values)
        body_sum = np.sum(np.abs(w64["close"].values - w64["open"].values))
        if body_sum == 0 or (wick_sum / body_sum) > 3.0:
            continue

        # Core Signal: 2D Kalman Drift + Volume Profile Breakout + D1 Trend Alignment
        closes_48 = df["close"].iloc[i - 48 : i].values
        drift = run_kalman_2d(np.log(closes_48))
        signal = 1 if drift > 0 else (-1 if drift < 0 else 0)
        if signal == 0:
            continue

        d1_trend = 1 if prev["close"] > d1_val else -1
        if signal != d1_trend:
            continue

        vah, val = calculate_vp(df.iloc[i - VP_LOOKBACK : i])
        if signal == 1 and prev["close"] <= vah:
            continue
        if signal == -1 and prev["close"] >= val:
            continue

        # Hot-Deck sizing when trend is ultra-clean (wick/body < 1.8)
        risk_pct = HOT_RISK_PCT if (wick_sum / body_sum) < 1.8 else BASE_RISK_PCT
        risk_cash = balance * risk_pct
        sl_dist = max(atr_val, sigma_val * SD_MULT)
        tp_dist = sl_dist * TARGET_RR
        lot = max(0.01, math.floor((risk_cash / (sl_dist * CONTRACT_SIZE)) * 100) / 100)

        entry = row["open"] + bar_spread if signal == 1 else row["open"] - bar_spread
        position = {
            "type": "BUY" if signal == 1 else "SELL",
            "entry": entry,
            "sl": entry - sl_dist if signal == 1 else entry + sl_dist,
            "tp": entry + tp_dist if signal == 1 else entry - tp_dist,
            "lot": lot,
            "risk_cash": risk_cash,
        }

    if not trades:
        print("No trades triggered.")
        return

    res = pd.DataFrame(trades)
    wins = res[res["reason"] == "WIN"]
    print(f"Trades: {len(res)} | Win Rate: {len(wins)/len(res)*100:.2f}% | Net R: {res['r'].sum():+.2f}R")
    print(f"Expectancy: {res['r'].mean():+.3f}R/trade | Max DD: {max_dd_pct:.2f}% | Final: ${balance:,.2f}")


if __name__ == "__main__":
    run_unified_backtest("history_data.csv")