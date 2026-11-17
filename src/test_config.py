#!/usr/bin/env python3
"""Test script to verify configuration loading"""

import sys
sys.path.insert(0, '.')

from config_loader import ConfigManager

print("=" * 70)
print("QuantumGold-Nexus Configuration Test")
print("=" * 70)

config = ConfigManager()

# Test MT5 config
mt5 = config.get_mt5_config()
print("\n[MT5 Configuration]")
print(f"  Login: {mt5['login']}")
print(f"  Server: {mt5['server']}")
print(f"  Password: {'*' * len(mt5['password']) if mt5['password'] else 'NOT SET'}")

# Test Trading config
trading = config.get_trading_config()
print("\n[Trading Parameters]")
print(f"  Fast EMA: {trading['fast_ema']}")
print(f"  Slow EMA: {trading['slow_ema']}")
print(f"  ATR SL Multiplier: {trading['atr_mult_sl']}")
print(f"  ATR TP Multiplier: {trading['atr_mult_tp']}")
print(f"  Contract Size: {trading['contract_size']}")
print(f"  Max Slippage: {trading['max_slippage_pips']} pips")

# Test Instances config
instances = config.get_instances_config()
print("\n[Instance Configuration]")
print(f"  Instance Name: {instances['instance_name']}")
print(f"  Symbols: {', '.join(instances['symbols'])}")
print(f"  Trading Company: {instances['trading_company']}")
print(f"  Risk Percentage: {instances['percentage_of_risk']}")
print(f"  Magic Number: {instances['magic_number']}")

# Test Discord config
webhook = config.get_discord_webhook()
print("\n[Discord Configuration]")
print(f"  Webhook URL: {'CONFIGURED' if webhook and 'YOUR_WEBHOOK' not in webhook else 'NOT CONFIGURED'}")

print("\n" + "=" * 70)
print("✓ Configuration test completed successfully!")
print("=" * 70)
