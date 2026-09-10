import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta
import time
import numpy as np
from strategy import calculate_ema, calculate_atr, calculate_rsi
from placetrade import place_trade, send_discord_notification
import math
import os
import pandas as pd

# Strategy & Risk Parameters
fast = 5
slow = 20
atr_mult_sl = 1.25
atr_mult_tp = 3.5  
symbol = "EURJPY"

# Execution & Friction Control
MAX_ALLOWED_SPREAD_PIPS = 2.0  # Reject entries if spread > 2.0 pips
MAX_SLIPPAGE_PIPS = 2.0        # Reject entries if price slips > 2.0 pips

instances = [
    {                                                                        
        'mt5_path': 'C:/Program Files/MetaTrader 5/terminal64.exe',
        'instance_name': 'FundingPips',
        'symbol': ['EURJPY'],
        'trading_company': 'OANDA',
        'percentage_of_risk': 0.0075,
        'position_holding': "None",         
        'trade_count': 0,
        'magic_numeber': 111111
    },
    # Add more instances as needed
]


def check_recently_closed_trades(symbol, last_check_time):
    """
    Looks at the history from last_check_time to now to find closed deals
    and sends a notification.
    """
    now = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(last_check_time, now, group=symbol)

    if deals is None or len(deals) == 0:
        return

    for deal in deals:
        if deal.entry == 1: 
            profit = deal.profit + deal.swap + deal.commission
            deal_type = "BUY (Closed)" if deal.type == mt5.DEAL_TYPE_SELL else "SELL (Closed)"

            reason_str = "Manual / Bot Close"
            if deal.reason == mt5.DEAL_REASON_SL:
                reason_str = "🛑 Hit Stop Loss (SL)"
            elif deal.reason == mt5.DEAL_REASON_TP:
                reason_str = "🎯 Hit Take Profit (TP)"

            message = (
                f"📊 Trade Closed Alert\n"
                f"• Symbol: {deal.symbol}\n"
                f"• Type: {deal_type}\n"
                f"• Lots: {deal.volume}\n"
                f"• Profit/Loss: ${profit:.2f}\n"
                f"• Exit Reason: {reason_str}\n"
                f"• Time: {datetime.fromtimestamp(deal.time).strftime('%Y-%m-%d %H:%M:%S')}"
            )

            send_discord_notification(message)
            print(f"Notification Sent: {deal.symbol} closed via {reason_str}")


def count_trades_today_simple(log_path: str, target_date: str) -> int:
    if not os.path.isfile(log_path):
        return 0
    count = 0
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            if target_date in line:
                count += 1
    return count


def get_current_holding(symbol):
    positions = mt5.positions_get(symbol=symbol)
    if positions and len(positions) > 0:
        pos_type = positions[0].type
        if pos_type == mt5.POSITION_TYPE_BUY:
            return "BUY"
        elif pos_type == mt5.POSITION_TYPE_SELL:
            return "SELL"
    return "None"


def round_to_step(volume, step):
    if step <= 0:
        return round(volume, 2)
    return math.floor(volume / step) * step


def close_all_positions(symbol, trading_company):
    positions = mt5.positions_get(symbol=symbol) or []
    tick = mt5.symbol_info_tick(symbol)
    for pos in positions:
        vol = pos.volume
        if vol <= 0:
            continue
        if pos.type == mt5.POSITION_TYPE_BUY:
            place_trade(symbol, "SELL", vol, 0, 0, tick.bid, trading_company)
        elif pos.type == mt5.POSITION_TYPE_SELL:
            place_trade(symbol, "BUY", vol, 0, 0, tick.ask, trading_company)


def get_h4_direction_and_atr(symbol):
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H4, 0, 5)
    df = pd.DataFrame(rates)
    last_closed_candle = df.iloc[-2]
    
    open_price = last_closed_candle['open']
    close_price = last_closed_candle['close']
    
    if close_price > open_price:
        signal = 1   # Bullish (BUY)
    else:
        signal = -1  # Bearish (SELL)
    
    return signal


def signal_Granted(instance, symbol, signal, tp_dist, sl_dist, requested_price):
    if not mt5.initialize(path=instance['mt5_path']):
        print(f"initialize() failed for {instance['instance_name']}")
        return
    
    tick = mt5.symbol_info_tick(symbol)
    symbol_info = mt5.symbol_info(symbol)
    if tick is None or symbol_info is None:
        print(f"[{instance['instance_name']}] Failed to retrieve tick/symbol info")
        return

    point = symbol_info.point
    current_market_price = tick.ask if signal == 1 else tick.bid
    price_diff_pips = abs(current_market_price - requested_price) / (point * 10)
    
    if price_diff_pips > MAX_SLIPPAGE_PIPS:
        print(f"[{instance['instance_name']}] SKIP: Slippage too high! ({price_diff_pips:.1f} pips > {MAX_SLIPPAGE_PIPS} pips)")
        return

    account_info = mt5.account_info()
    if account_info is None or not account_info.trade_allowed:
        print(f"{instance['instance_name']}: Trade permission denied")
        return
    
    balance = account_info.balance
    risk_amount = balance * instance['percentage_of_risk']

    tick_size = symbol_info.trade_tick_size
    tick_value = symbol_info.trade_tick_value

    sl_in_ticks = sl_dist / tick_size

    if sl_in_ticks > 0 and tick_value > 0:
        lot_raw = risk_amount / (sl_in_ticks * tick_value)
    else:
        lot_raw = symbol_info.volume_min

    # Clamp lot size within broker boundaries
    lot = round_to_step(lot_raw, symbol_info.volume_step)
    lot = max(symbol_info.volume_min, min(symbol_info.volume_max, lot))
    lot = round(lot, 2)

    if signal == 1:  # BUY
        entry_price = tick.ask
        sl = round(entry_price - sl_dist, 2)
        tp = round(entry_price + tp_dist, 2)
        print(f"[{instance['instance_name']}] Executing BUY | Risk: ${risk_amount:.2f} | Lot: {lot:.2f} | SL: {sl:.2f} | TP: {tp:.2f}")
        place_trade(symbol, "BUY", lot, sl, tp, entry_price, instance['trading_company'])
        
    elif signal == -1:  # SELL
        entry_price = tick.bid
        sl = round(entry_price + sl_dist, 2)
        tp = round(entry_price - tp_dist, 2)
        print(f"[{instance['instance_name']}] Executing SELL | Risk: ${risk_amount:.2f} | Lot: {lot:.2f} | SL: {sl:.2f} | TP: {tp:.2f}")
        place_trade(symbol, "SELL", lot, sl, tp, entry_price, instance['trading_company'])


def trading_loop(instances):
    master = instances[0]

    if not mt5.initialize(path=master['mt5_path']):
        print(f"initialize() failed for {master['symbol']}, {master['instance_name']}")
        return
    
    last_history_check = datetime.now(timezone.utc) - timedelta(seconds=10)
    
    while True:
        now = datetime.now()

        # Check for closed trades every 5 seconds
        if now.second % 5 == 0:
            for symbol in master['symbol']:
                check_recently_closed_trades(symbol, last_history_check)
            last_history_check = datetime.now(timezone.utc)
            
        # Re-initialize MT5 context every minute
        if now.minute % 1 == 0 and now.second == 0:
            if not mt5.initialize(path=master['mt5_path']):
                print(f"Re-initializing MT5 failed for {master['instance_name']}")
                time.sleep(1)
                continue

            # Reset holding status check
            position = get_current_holding(master['symbol'][0])

            # Close all positions at 4:45 AM HKT
            if now.hour == 4 and now.minute == 45 and position != "None":
                close_all_positions(master['symbol'][0], master['trading_company'])
                time.sleep(60)
                continue

            # =================================================================
            # STRATEGY TRIGGER WITH SPREAD RETRY LOOP AT 20:00:00 HKT
            # =================================================================
            if now.hour == 20 and now.minute == 0:
                print(f"Triggering execution routine for {now.date()} at 20:00 HKT")
                
                for i, symbol in enumerate(master['symbol']):
                    symbol_info = mt5.symbol_info(symbol)
                    if symbol_info is None:
                        continue
                    
                    point = symbol_info.point
                    spread_ok = False
                    start_time = time.time()
                    
                    # Retry loop for up to 300 seconds (20:00:00 - 20:05:00)
                    while time.time() - start_time < 300:
                        tick = mt5.symbol_info_tick(symbol)
                        if tick is not None:
                            spread_pips = (tick.ask - tick.bid) / (point * 10)
                            if spread_pips <= MAX_ALLOWED_SPREAD_PIPS:
                                print(f"Spread acceptable ({spread_pips:.1f} pips <= {MAX_ALLOWED_SPREAD_PIPS} pips). Executing order...")
                                spread_ok = True
                                break
                            else:
                                print(f"Spread too wide ({spread_pips:.1f} pips). Retrying in 1 second...")
                        time.sleep(1)
                    
                    if not spread_ok:
                        print(f"SKIP EXECUTION: Spread did not normalize within 300s window.")
                        continue

                    # Calculate direction & distances
                    h4_signal = get_h4_direction_and_atr(symbol)
                    signal = 1 if h4_signal == 1 else -1

                    target_tick = mt5.symbol_info_tick(symbol)
                    req_price = target_tick.ask if signal == 1 else target_tick.bid

                    for instance in instances:
                        rates_m15 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 1, 250)
                        atr14_val = calculate_atr(rates_m15, 14)[-1]
                        atr_sl = atr14_val * atr_mult_sl 
                        
                        closes = np.array([x['close'] for x in rates_m15])
                        sigma = np.std(closes[-20:])
                        sd_sl = sigma * 2
                        sl_dist = max(atr_sl, sd_sl)
                        tp_dist = sl_dist * 1.1
                        
                        signal_Granted(instance, instance['symbol'][i], signal, tp_dist, sl_dist, req_price)
                
                # Sleep 60s to ensure trigger fires exactly once at 20:00 HKT
                time.sleep(60)
                continue

        time.sleep(1)


if __name__ == "__main__":
    send_discord_notification(f"🚀 **ROG ALLY Trading Bot Started** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    trading_loop(instances)