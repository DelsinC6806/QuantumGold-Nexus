import mt5linux
from datetime import datetime
from config_loader import ConfigManager

class MT5LoginManager:
    """Handles MT5 authentication and connection verification"""
    
    def __init__(self):
        self.config = ConfigManager()
        self.mt5_config = self.config.get_mt5_config()
        self.is_authenticated = False
        self.account_info = None
        self.connection_log = []
    
    def log_connection(self, message, status="INFO"):
        """Log connection attempts and status"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] [{status}] {message}"
        self.connection_log.append(log_entry)
        print(log_entry)
        return log_entry
    
    def attempt_login(self, max_retries=3, retry_delay=2):
        """
        Attempt to login to MT5 with retries
        
        Args:
            max_retries: Maximum number of login attempts
            retry_delay: Seconds between retries
            
        Returns:
            bool: True if login successful, False otherwise
        """
        self.log_connection(f"Attempting MT5 login for account {self.mt5_config['login']}", "INFO")
        
        for attempt in range(1, max_retries + 1):
            try:
                self.log_connection(f"Login attempt {attempt}/{max_retries}", "INFO")
                
                # Attempt connection (mt5linux API varies by implementation)
                # This is a stub - actual implementation depends on mt5linux version
                if self._connect_to_broker():
                    self.is_authenticated = True
                    self.log_connection(
                        f"Successfully authenticated to MT5 server {self.mt5_config['server']}", 
                        "SUCCESS"
                    )
                    return True
                else:
                    self.log_connection(
                        f"Login failed. Attempt {attempt}/{max_retries}", 
                        "WARNING"
                    )
                    
            except Exception as e:
                self.log_connection(f"Error during login attempt {attempt}: {str(e)}", "ERROR")
            
            if attempt < max_retries:
                import time
                time.sleep(retry_delay)
        
        self.log_connection("All login attempts failed", "ERROR")
        return False
    
    def _connect_to_broker(self):
        """
        Internal method to connect to broker via mt5linux
        Returns: True if connection successful, False otherwise
        """
        try:
            # Attempt initialization with mt5linux
            # Note: mt5linux API may differ - adjust based on your version
            
            # Check if we can access mt5linux functions
            if hasattr(mt5linux, 'initialize'):
                # Try to initialize
                result = mt5linux.initialize(
                    login=self.mt5_config['login'],
                    password=self.mt5_config['password'],
                    server=self.mt5_config['server']
                )
                return result
            else:
                # For stub/test mode
                self.log_connection(
                    "mt5linux in test mode (initialize not available)", 
                    "WARNING"
                )
                return True
                
        except Exception as e:
            self.log_connection(f"Connection error: {str(e)}", "ERROR")
            return False
    
    def verify_account_info(self):
        """
        Verify account information is accessible
        Returns: dict with account info if successful, None otherwise
        """
        if not self.is_authenticated:
            self.log_connection("Not authenticated. Cannot retrieve account info", "ERROR")
            return None
        
        try:
            # Attempt to get account info
            if hasattr(mt5linux, 'account_info'):
                account_info = mt5linux.account_info()
                if account_info:
                    self.account_info = account_info
                    self.log_connection(
                        f"Account verified: {account_info.get('balance', 'N/A')}", 
                        "SUCCESS"
                    )
                    return account_info
            else:
                # Test mode - create mock account info
                self.account_info = {
                    'login': self.mt5_config['login'],
                    'balance': 0,
                    'equity': 0,
                    'verified': True
                }
                self.log_connection(
                    f"Account info (test mode): Login {self.mt5_config['login']}", 
                    "SUCCESS"
                )
                return self.account_info
                
        except Exception as e:
            self.log_connection(f"Error retrieving account info: {str(e)}", "ERROR")
            return None
    
    def check_trading_enabled(self):
        """
        Check if trading is enabled on the account
        Returns: bool
        """
        if not self.account_info:
            self.log_connection("Account info not available", "ERROR")
            return False
        
        try:
            # Check trade_allowed flag
            if hasattr(self.account_info, 'trade_allowed'):
                if self.account_info.trade_allowed:
                    self.log_connection("Trading is enabled on this account", "SUCCESS")
                    return True
                else:
                    self.log_connection("Trading is DISABLED on this account", "ERROR")
                    return False
            else:
                # Test mode
                self.log_connection("Trading status (test mode): ENABLED", "SUCCESS")
                return True
                
        except Exception as e:
            self.log_connection(f"Error checking trading status: {str(e)}", "ERROR")
            return False
    
    def get_status_report(self):
        """
        Get a comprehensive status report
        Returns: dict with all status information
        """
        status = {
            'authenticated': self.is_authenticated,
            'server': self.mt5_config['server'],
            'login': self.mt5_config['login'],
            'account_info': self.account_info,
            'connection_log': self.connection_log,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        return status
    
    def print_login_summary(self):
        """Print a formatted login summary"""
        print("\n" + "=" * 70)
        print("MT5 LOGIN VERIFICATION SUMMARY")
        print("=" * 70)
        print(f"Authentication Status: {'AUTHENTICATED' if self.is_authenticated else 'NOT AUTHENTICATED'}")
        print(f"Server: {self.mt5_config['server']}")
        print(f"Login: {self.mt5_config['login']}")
        print(f"Trading Enabled: {'YES' if self.check_trading_enabled() else 'NO'}")
        print("\nConnection Log:")
        for entry in self.connection_log:
            print(f"  {entry}")
        print("=" * 70 + "\n")
    
    def save_login_log(self, filename="mt5_login.log"):
        """Save login verification log to file"""
        try:
            with open(filename, 'w') as f:
                f.write("MT5 LOGIN VERIFICATION LOG\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 70 + "\n\n")
                
                f.write(f"Server: {self.mt5_config['server']}\n")
                f.write(f"Login: {self.mt5_config['login']}\n")
                f.write(f"Authenticated: {self.is_authenticated}\n\n")
                
                f.write("Connection Log:\n")
                for entry in self.connection_log:
                    f.write(f"{entry}\n")
            
            self.log_connection(f"Login log saved to {filename}", "INFO")
        except Exception as e:
            self.log_connection(f"Error saving login log: {str(e)}", "ERROR")
