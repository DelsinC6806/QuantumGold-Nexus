import configparser
import os
from pathlib import Path

class ConfigManager:
    """Load and manage configuration from config.ini file"""
    
    def __init__(self, config_path="config.ini"):
        self.config = configparser.ConfigParser()
        
        # Try to load from provided path, then parent directory, then common locations
        paths_to_try = [
            config_path,
            Path.cwd() / config_path,
            Path.cwd().parent / config_path,  # /app/config.ini when cwd is /app/src
            Path("/app") / config_path,
            Path("/app/src") / config_path,
        ]
        
        loaded = False
        for path in paths_to_try:
            if os.path.exists(path):
                self.config.read(path)
                loaded = True
                print(f"[INFO] Configuration loaded from: {path}")
                break
        
        if not loaded:
            print(f"[WARNING] Config file not found. Using defaults.")
    
    def get_mt5_config(self):
        """Get MT5 configuration"""
        return {
            'login': int(self.config.get('mt5', 'login', fallback='1234567')),
            'password': self.config.get('mt5', 'password', fallback=''),
            'server': self.config.get('mt5', 'server', fallback='OANDA-V20'),
        }
    
    def get_discord_webhook(self):
        """Get Discord webhook URL"""
        return self.config.get('discord', 'webhook_url', fallback='')
    
    def get_trading_config(self):
        """Get trading parameters"""
        return {
            'fast_ema': int(self.config.get('trading', 'fast_ema', fallback='5')),
            'slow_ema': int(self.config.get('trading', 'slow_ema', fallback='20')),
            'atr_mult_sl': float(self.config.get('trading', 'atr_mult_sl', fallback='1.25')),
            'atr_mult_tp': float(self.config.get('trading', 'atr_mult_tp', fallback='3.5')),
            'contract_size': int(self.config.get('trading', 'contract_size', fallback='100')),
            'max_slippage_pips': float(self.config.get('trading', 'max_slippage_pips', fallback='25.0')),
        }
    
    def get_instances_config(self):
        """Get trading instances configuration"""
        symbols = self.config.get('instances', 'symbols', fallback='EURJPY').split(',')
        symbols = [s.strip() for s in symbols]
        
        return {
            'instance_name': self.config.get('instances', 'instance_name', fallback='FundingPips'),
            'symbols': symbols,
            'trading_company': self.config.get('instances', 'trading_company', fallback='OANDA'),
            'percentage_of_risk': float(self.config.get('instances', 'percentage_of_risk', fallback='0.0075')),
            'magic_number': int(self.config.get('instances', 'magic_number', fallback='111111')),
        }
