import pandas as pd
import numpy as np
from datetime import datetime
time = False;
def calculate_ema(prices, window):
    ema = np.zeros_like(prices, dtype=float)
    multiplier = 2 / (window + 1)
    
    # First EMA is the SMA of the first 'window' prices
    ema[window - 1] = np.mean(prices[:window])
    
    # Calculate subsequent EMA values
    for i in range(window, len(prices)):
        ema[i] = (prices[i] - ema[i - 1]) * multiplier + ema[i - 1]
    
    return ema[window - 1:]  # Return only valid EMA values

# Example usage


def calculate_swing_high_low(data, window=20):
    lookback = 3  # hardcoded for M15
    swing_highs = []
    swing_lows = []

    for i in range(lookback, len(data) - lookback):
        current_high = data[i]['high']
        current_low = data[i]['low']

        # Get highs/lows on both sides
        left_highs = [data[i - j]['high'] for j in range(1, lookback + 1)]
        right_highs = [data[i + j]['high'] for j in range(1, lookback + 1)]

        left_lows = [data[i - j]['low'] for j in range(1, lookback + 1)]
        right_lows = [data[i + j]['low'] for j in range(1, lookback + 1)]

        # Confirm swing high
        if all(current_high > h for h in left_highs + right_highs):
            swing_highs.append({'index': i, 'price': current_high})

        # Confirm swing low
        if all(current_low < l for l in left_lows + right_lows):
            swing_lows.append({'index': i, 'price': current_low})

    return swing_highs, swing_lows

def calculate_fibonacci_levels(swing_high, swing_low,trend):
    if trend == 'bullish':
        fib_0_5 = swing_low + (swing_high - swing_low) * 0.5
        fib_0_618 = swing_low + (swing_high - swing_low) * 0.618
    else:  # bearish
        fib_0_5 = swing_high - (swing_high - swing_low) * 0.5
        fib_0_618 = swing_high - (swing_high - swing_low) * 0.618

    return {
        '0.5': fib_0_5,
        '0.618': fib_0_618
    }

def detect_trend(ema20, ema50):
    if ema20[-1] > ema50[-1]:
        return 'bullish'
    elif ema20[-1] < ema50[-1]:
        return 'bearish'
    else:
        return 'neutral'


def calculateSignal(trend, fib_levels, currentPrice, currentHolding, ema20, ema50):
    current_hour = datetime.now().hour
    # Time filter: only trade between 22:00 and 03:00
    if current_hour >= 22 or current_hour < 3 or time == False:
        if currentHolding not in ["BUY", "SELL"]:
            if trend == 'bullish':
                if fib_levels['0.5'] < currentPrice < fib_levels['0.618']:
                    if currentPrice > ema20[-1]:
                        print("Buy signal detected")
                        return "BUY"
                    else:
                        print("Current price is below EMA20, waiting for confirmation")
                        return "WAIT"
                else:
                    print("Current price is outside the Fibonacci golden range, waiting for confirmation")
                    return "WAIT"

            elif trend == 'bearish':
                if fib_levels['0.618'] > currentPrice > fib_levels['0.5']:
                    if currentPrice < ema20[-1]:
                        print("Sell signal detected")
                        return "SELL"
                    else:
                        print("Current price is above EMA20, waiting for confirmation")
                        return "WAIT"
                else:
                    print("Current price is outside the Fibonacci golden range, waiting for confirmation")
                    return "WAIT"

            else:
                print("No clear trend detected")
                return "WAIT"
        else:
            print("Already holding a position")
            return "WAIT"
    else:
        print("Not the right time to trade")
        return "WAIT"
    
def calculate_sl_tp_fixed(current_price, take_profit, stop_loss, lot_size, tick_value, tick_size, trade_type="BUY"):
    if trade_type.upper() == "BUY":
        stop_loss_price = current_price - (stop_loss * tick_size)
        take_profit_price = current_price + (take_profit * tick_size)
    else:  # SELL
        stop_loss_price = current_price + (stop_loss * tick_size)
        take_profit_price = current_price - (take_profit * tick_size)

    # Calculate monetary values
    risk_per_trade = stop_loss * tick_value * lot_size
    potential_reward = take_profit * tick_value * lot_size
    risk_reward_ratio = potential_reward / risk_per_trade if risk_per_trade != 0 else 0

    print("Stop Loss Price:", stop_loss_price)
    print("Take Profit Price:", take_profit_price)
    print("Risk per Trade:", risk_per_trade)
    print("Potential Reward:", potential_reward)
    print("Risk-Reward Ratio:", risk_reward_ratio)
    return {
        'stop_loss_price': round(stop_loss_price, 6),
        'take_profit_price': round(take_profit_price, 6),
        'risk_per_trade': round(risk_per_trade, 2),
        'potential_reward': round(potential_reward, 2),
        'risk_reward_ratio': round(risk_reward_ratio, 2)
    }

def calculate_atr(data, window=14):
    high = np.array([bar['high'] for bar in data])
    low = np.array([bar['low'] for bar in data])
    close = np.array([bar['close'] for bar in data])
    tr = np.maximum(high[1:] - low[1:], np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1]))
    atr = pd.Series(tr).rolling(window=window).mean().values
    return np.concatenate([np.full(window, np.nan), atr])