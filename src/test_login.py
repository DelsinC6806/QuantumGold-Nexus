#!/usr/bin/env python3
"""Test MT5 login and connection verification"""

from mt5_login_manager import MT5LoginManager
import sys

def main():
    print("\n" + "=" * 70)
    print("QuantumGold-Nexus MT5 Login Verification Tool")
    print("=" * 70 + "\n")
    
    # Initialize login manager
    login_manager = MT5LoginManager()
    
    # Step 1: Attempt login
    print("[STEP 1] Attempting MT5 login...")
    login_success = login_manager.attempt_login(max_retries=3, retry_delay=2)
    
    if not login_success:
        print("\n[FAILED] Could not authenticate to MT5 server")
        login_manager.print_login_summary()
        login_manager.save_login_log()
        return False
    
    # Step 2: Verify account info
    print("\n[STEP 2] Verifying account information...")
    account_info = login_manager.verify_account_info()
    
    if not account_info:
        print("\n[FAILED] Could not retrieve account information")
        login_manager.print_login_summary()
        login_manager.save_login_log()
        return False
    
    # Step 3: Check trading enabled
    print("\n[STEP 3] Checking if trading is enabled...")
    trading_enabled = login_manager.check_trading_enabled()
    
    if not trading_enabled:
        print("\n[WARNING] Trading is not enabled on this account")
        login_manager.print_login_summary()
        login_manager.save_login_log()
        return False
    
    # Print summary
    login_manager.print_login_summary()
    login_manager.save_login_log()
    
    print("\n[SUCCESS] All login verification checks passed!")
    print("The bot is ready to trade.\n")
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
