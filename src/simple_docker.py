from mt5linux import MetaTrader5
from datetime import datetime, timezone, timedelta
import time
import numpy as np
from strategy import calculate_ema, calculate_atr, calculate_rsi
from placetrade_docker import place_trade, send_discord_notification
from mt5_login_manager import MT5LoginManager
import math
import os
import pandas as pd
import configparser
import socket

fast = 5
slow = 20
atr_mult_sl = 1.25
atr_mult_tp = 3.5  
contract_size = 100
symbol = ""
position = "None"
last_history_check = datetime.now(timezone.utc) - timedelta(seconds=10)
MAX_SLIPPAGE_PIPS = 25.0

# Retry configuration
MAX_RETRIES = 5
RETRY_DELAY = 5  # seconds

# Load config from config.ini
config = configparser.ConfigParser()
config.read('/app/config.ini')

# MT5 Account Creds
MT5_LOGIN = config.getint('mt5', 'login')
MT5_PASSWORD = config.get('mt5', 'password')
MT5_SERVER = config.get('mt5', 'server')

instances = [
    {                                                                       
        'instance_name': config.get('instances', 'instance_name'),
        'symbol': [s.strip() for s in config.get('instances', 'symbols').split(',')],
        'trading_company': config.get('instances', 'trading_company'),
        'percentage_of_risk': config.getfloat('instances', 'percentage_of_risk'),
        'position_holding': "None",         
        'trade_count': 0,
        'magic_number': config.getint('instances', 'magic_number')
    }
]

def check_recently_closed_trades(symbol, last_check_time, mt5):
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
    """Count trades logged today"""
    if not os.path.isfile(log_path):
        return 0
    count = 0
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            if target_date in line:
                count += 1
    return count

def get_current_holding(symbol, mt5):
    """Get current holding status"""
    positions = mt5.positions_get(symbol=symbol)
    if positions and len(positions) > 0:
        pos_type = positions[0].type
        if pos_type == mt5.POSITION_TYPE_BUY:
            return "BUY"
        elif pos_type == mt5.POSITION_TYPE_SELL:
            return "SELL"

    return "None"

def round_to_step(volume, step):
    """Round volume to step"""
    if step <= 0:
        return round(volume, 2)
    return math.floor(volume / step) * step

def close_all_positions(symbol, trading_company, mt5):
    """Close all positions for symbol"""
    positions = mt5.positions_get(symbol=symbol) or []
    tick = mt5.symbol_info_tick(symbol)
    for pos in positions:
        vol = pos.volume
        if vol <= 0:
            continue
        if pos.type == mt5.POSITION_TYPE_BUY:
            place_trade(mt5, symbol, "SELL", vol, 0, 0, tick.bid, trading_company)
        elif pos.type == mt5.POSITION_TYPE_SELL:
            place_trade(mt5, symbol, "BUY", vol, 0, 0, tick.ask, trading_company)

def get_h4_direction_and_atr(symbol, mt5):
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H4, 0, 5)
    
    df = pd.DataFrame(rates)
    last_closed_candle = df.iloc[-2]
    
    open_price = last_closed_candle['open']
    close_price = last_closed_candle['close']
    
    if close_price > open_price:
        signal = 1   # Bullish (BUY)
    else:
        signal = -1
    
    return signal

def trading_loop(instances, mt5):
    master = instances[0]

    # Use MT5LoginManager for authentication
    login_manager = MT5LoginManager()
    
    print("\n" + "=" * 70)
    print("QuantumGold-Nexus MT5 Login Verification")
    print("=" * 70 + "\n")
    
    # Attempt login with retries
    print("[STEP 1] Attempting MT5 login...")
    login_success = login_manager.attempt_login(max_retries=3, retry_delay=2)
    
    if not login_success:
        print(f"\n❌ Failed to login to account {MT5_LOGIN} on server {MT5_SERVER}")
        login_manager.print_login_summary()
        login_manager.save_login_log()
        return
    
    # Verify account info
    print("\n[STEP 2] Verifying account information...")
    account_info = login_manager.verify_account_info()
    
    if not account_info:
        print("\n❌ Could not retrieve account information")
        login_manager.print_login_summary()
        login_manager.save_login_log()
        return
    
    # Check trading enabled
    print("\n[STEP 3] Checking if trading is enabled...")
    trading_enabled = login_manager.check_trading_enabled()
    
    if not trading_enabled:
        print("\n❌ Trading is not enabled on this account")
        login_manager.print_login_summary()
        login_manager.save_login_log()
        return
    
    login_manager.print_login_summary()
    print(f"\n✅ Successfully authenticated to server: {MT5_SERVER}\n")
    
    # Get MT5 instance from login manager
    mt5 = login_manager.mt5
    
    position = get_current_holding(master['symbol'][0], mt5) if master['symbol'] else "None"

    if datetime.now().hour >= 0 and datetime.now().hour < 6:
        today = datetime.now() - timedelta(days=1)
    else:
        today = datetime.now()

    today_str = today.strftime("%Y-%m-%d")
    trade_count = count_trades_today_simple("/app/trade_log.txt", today_str)
    signal = 0
    last_history_check = datetime.now(timezone.utc) - timedelta(seconds=10)
    
    print(f"🚀 Trading loop started for {master['instance_name']}")
    
    while True:
        try:
            now = datetime.now()

            if now.second % 5 == 0:
                for sym in master['symbol']:
                    check_recently_closed_trades(sym, last_history_check, mt5)
                last_history_check = datetime.now(timezone.utc)
                
            if now.minute % 1 == 0 and (now.second in (0, 1, 2)):
                account_info = mt5.account_info()
                if account_info is None:
                    print("Failed to get account info")
                    time.sleep(1)
                    continue

                if now.hour == 6 and now.minute == 0:
                    trade_count = 0
                    print("Trade count reset at 6:00 AM")

                if now.hour == 4 and now.minute == 45 and position != "None":
                    print(f"Closing all positions for {master['symbol']}...")
                    for sym in master['symbol']:
                        close_all_positions(sym, master['trading_company'], mt5)
                    position = "None"
                    time.sleep(60)
                    continue

                if now.hour == 20 and now.minute == 3 and now.second == 1:
                    print(f"Triggering trades for {now.date()}")
                    for i, sym in enumerate(master['symbol']):
                        h4_signal = get_h4_direction_and_atr(sym, mt5)
                        signal = 1 if h4_signal == 1 else -1

                        target_tick = mt5.symbol_info_tick(sym)
                        req_price = target_tick.ask if signal == 1 else target_tick.bid

                        for instance in instances:
                            rates_m15 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 1, 250)
                            atr14_val = calculate_atr(rates_m15, 14)[-1]
                            atr_sl = atr14_val * atr_mult_sl
                            
                            closes = np.array([x['close'] for x in rates_m15])
                            sigma = np.std(closes[-20:])
                            sd_sl = sigma * 2
                            sl_dist = max(atr_sl, sd_sl)
                            tp_dist = sl_dist * 1.1
                            signal_Granted(instance, instance['symbol'][i], signal, tp_dist, sl_dist, req_price, mt5)
            
            time.sleep(1)
        except Exception as e:
            print(f"Error in trading loop: {e}")
            send_discord_notification(f"❌ Trading loop error: {str(e)}")
            time.sleep(5)

def signal_Granted(instance, symbol, signal, tp_dist, sl_dist, requested_price, mt5):
    """Execute trade based on signal"""
    try:
        tick = mt5.symbol_info_tick(symbol)
        symbol_info = mt5.symbol_info(symbol)
        point = symbol_info.point
        
        current_market_price = tick.ask if signal == 1 else tick.bid
        price_diff_pips = abs(current_market_price - requested_price) / (point * 10)
        
        if price_diff_pips > MAX_SLIPPAGE_PIPS:
            print(f"[{instance['instance_name']}] SKIP: Slippage too high! ({price_diff_pips:.1f} pips)")
            return

        account_info = mt5.account_info()
        if account_info is None or not account_info.trade_allowed:
            print(f"{instance['instance_name']}: Trading not allowed")
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

        lot = round_to_step(lot_raw, symbol_info.volume_step)
        lot = round(lot, 2)

        if signal == 1:  # BUY
            entry_price = tick.ask
            sl = entry_price - sl_dist
            tp = entry_price + tp_dist
            print(f"[{instance['instance_name']}] BUY | Lot: {lot:.2f} | SL: {sl:.2f} | TP: {tp:.2f}")
            place_trade(mt5, symbol, "BUY", lot, sl, tp, entry_price, instance['trading_company'])
            
        elif signal == -1:  # SELL
            entry_price = tick.bid
            sl = entry_price + sl_dist
            tp = entry_price - tp_dist
            print(f"[{instance['instance_name']}] SELL | Lot: {lot:.2f} | SL: {sl:.2f} | TP: {tp:.2f}")
            place_trade(mt5, symbol, "SELL", lot, sl, tp, entry_price, instance['trading_company'])
    except Exception as e:
        print(f"Error in signal_Granted: {e}")
        send_discord_notification(f"❌ Signal execution error: {str(e)}")

if __name__ == "__main__":
    try:
        # No longer need connect_with_retry—MT5LoginManager handles initialization
        send_discord_notification(f"🚀 **QuantumGold-Nexus Docker Bot Started** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        trading_loop(instances, None)
    except Exception as e:
        error_msg = f"❌ **QuantumGold-Nexus Failed to Start** \nError: {str(e)}\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        print(error_msg)
        send_discord_notification(error_msg)
        raise
