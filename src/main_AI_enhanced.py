import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta
import time
import numpy as np
from strategy import calculate_ema, calculate_atr
from placetrade import place_trade
import tkinter as tk
from threading import Thread
from multiprocessing import Process
from collections import deque
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
import warnings
import pickle  # Add this for saving/loading data
import os     # Add this for file operations
warnings.filterwarnings('ignore')

symbol = "XAUUSD"
fast = 5
slow = 15
atr_mult_sl = 1.0
atr_mult_tp = 4.0
contract_size = 100
daily_max_loss = 500  # 每日最大虧損設定

test = False

# AI CLASSES WITH PERSISTENCE
class MarketRegimeDetector:
    def __init__(self, lookback=30):
        self.lookback = lookback
        self.model = KMeans(n_clusters=3, random_state=42, n_init=10)
        self.scaler = StandardScaler()
        self.is_fitted = False
        self.feature_history = deque(maxlen=100)
        self.save_file = "regime_detector_data.pkl"  # Save file name
        
        # Load previous data if exists
        self.load_data()
        
    def save_data(self):
        """Save AI training data to file"""
        try:
            data = {
                'feature_history': list(self.feature_history),
                'is_fitted': self.is_fitted,
                'model': self.model if self.is_fitted else None,
                'scaler': self.scaler if self.is_fitted else None
            }
            with open(self.save_file, 'wb') as f:
                pickle.dump(data, f)
            print(f"✅ Regime detector data saved ({len(self.feature_history)} features)")
        except Exception as e:
            print(f"❌ Failed to save regime data: {e}")
    
    def load_data(self):
        """Load AI training data from file"""
        try:
            if os.path.exists(self.save_file):
                with open(self.save_file, 'rb') as f:
                    data = pickle.load(f)
                
                self.feature_history = deque(data['feature_history'], maxlen=100)
                self.is_fitted = data['is_fitted']
                
                if self.is_fitted and data['model'] is not None:
                    self.model = data['model']
                    self.scaler = data['scaler']
                    print(f"✅ Loaded regime detector: {len(self.feature_history)} features, trained={self.is_fitted}")
                else:
                    print(f"📚 Loaded {len(self.feature_history)} features, model not trained yet")
            else:
                print("📝 No previous regime detector data found, starting fresh")
        except Exception as e:
            print(f"❌ Failed to load regime data: {e}")
        
    def extract_features(self, prices, atr_values, volume=None):
        """Extract market features for regime detection"""
        if len(prices) < self.lookback:
            return None
            
        try:
            # 1. Trend Strength (Linear regression slope)
            x = np.arange(self.lookback)
            y = np.array(prices[-self.lookback:])
            slope = np.polyfit(x, y, 1)[0]
            trend_strength = abs(slope) / np.mean(y) * 100
            
            # 2. Volatility Ratio
            current_atr = atr_values[-1]
            avg_atr = np.mean(atr_values[-self.lookback:])
            volatility_ratio = current_atr / avg_atr if avg_atr > 0 else 1
            
            # 3. Price Range
            price_range = (max(prices[-self.lookback:]) - min(prices[-self.lookback:])) / np.mean(prices[-self.lookback:])
            
            # 4. Momentum
            momentum = (prices[-1] - prices[-5]) / prices[-5] if len(prices) >= 5 else 0
            
            # 5. R-squared (trend consistency)
            y_pred = slope * x + np.polyfit(x, y, 1)[1]
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
            
            features = np.array([trend_strength, volatility_ratio, price_range, abs(momentum) * 100, r_squared])
            return features
            
        except Exception as e:
            print(f"Feature extraction error: {e}")
            return None
    
    def detect_regime(self, prices, atr_values, volume=None):
        """Detect market regime: 0=Trending, 1=Ranging, 2=Volatile"""
        features = self.extract_features(prices, atr_values, volume)
        
        if features is None:
            return 0  # Default to trending
            
        try:
            # Store features for training
            self.feature_history.append(features)
            
            # Auto-save every 10 new features
            if len(self.feature_history) % 10 == 0:
                self.save_data()
            
            # Train model if we have enough data and not fitted
            if len(self.feature_history) >= 20 and not self.is_fitted:
                self._train_model()
            
            if not self.is_fitted:
                # Use rule-based detection until model is trained
                return self._rule_based_regime(features)
            
            # Use trained model
            features_scaled = self.scaler.transform(features.reshape(1, -1))
            regime = self.model.predict(features_scaled)[0]
            
            return regime
            
        except Exception as e:
            print(f"Regime detection error: {e}")
            return self._rule_based_regime(features)
    
    def _train_model(self):
        """Train the clustering model"""
        try:
            if len(self.feature_history) < 20:
                return
                
            X = np.array(list(self.feature_history))
            X_scaled = self.scaler.fit_transform(X)
            self.model.fit(X_scaled)
            self.is_fitted = True
            print("AI: Market regime model trained successfully")
            
            # Save immediately after training
            self.save_data()
            
        except Exception as e:
            print(f"Model training error: {e}")
    
    def _rule_based_regime(self, features):
        """Fallback rule-based regime detection"""
        trend_strength, volatility_ratio, price_range, momentum, r_squared = features
        
        if trend_strength > 0.02 and r_squared > 0.6 and volatility_ratio < 1.4:
            return 0  # Trending
        elif volatility_ratio > 1.8 or price_range > 0.06:
            return 2  # Volatile
        else:
            return 1  # Ranging

class SignalConfidenceAI:
    def __init__(self):
        self.rf_model = RandomForestClassifier(n_estimators=50, random_state=42, max_depth=10)
        self.scaler = StandardScaler()
        self.is_fitted = False
        self.training_data = deque(maxlen=200)
        self.signal_history = deque(maxlen=100)
        self.save_file = "signal_confidence_data.pkl"  # Save file name
        
        # Load previous data if exists
        self.load_data()
        
    def save_data(self):
        """Save AI training data to file"""
        try:
            data = {
                'training_data': list(self.training_data),
                'signal_history': list(self.signal_history),
                'is_fitted': self.is_fitted,
                'model': self.rf_model if self.is_fitted else None,
                'scaler': self.scaler if self.is_fitted else None
            }
            with open(self.save_file, 'wb') as f:
                pickle.dump(data, f)
            print(f"✅ Signal confidence data saved ({len(self.training_data)} examples)")
        except Exception as e:
            print(f"❌ Failed to save signal data: {e}")
    
    def load_data(self):
        """Load AI training data from file"""
        try:
            if os.path.exists(self.save_file):
                with open(self.save_file, 'rb') as f:
                    data = pickle.load(f)
                
                self.training_data = deque(data['training_data'], maxlen=200)
                self.signal_history = deque(data['signal_history'], maxlen=100)
                self.is_fitted = data['is_fitted']
                
                if self.is_fitted and data['model'] is not None:
                    self.rf_model = data['model']
                    self.scaler = data['scaler']
                    print(f"✅ Loaded signal confidence: {len(self.training_data)} examples, trained={self.is_fitted}")
                else:
                    print(f"📚 Loaded {len(self.training_data)} examples, model not trained yet")
            else:
                print("📝 No previous signal confidence data found, starting fresh")
        except Exception as e:
            print(f"❌ Failed to load signal data: {e}")
        
    def extract_signal_features(self, ema_fast, ema_slow, atr, prices, volume=None):
        """Extract features for signal confidence"""
        try:
            # 1. EMA Strength
            ema_diff = abs(ema_fast[-1] - ema_slow[-1]) / ema_slow[-1] * 100
            
            # 2. EMA Momentum
            ema_momentum = (ema_fast[-1] - ema_fast[-3]) / ema_fast[-3] * 100 if len(ema_fast) >= 3 else 0
            
            # 3. ATR Ratio
            atr_ratio = atr[-1] / np.mean(atr[-10:]) if len(atr) >= 10 else 1
            
            # 4. Price vs EMA
            price_vs_ema = (prices[-1] - ema_fast[-1]) / ema_fast[-1] * 100
            
            # 5. Trend Consistency
            if len(ema_fast) >= 10:
                ema_trend = np.polyfit(range(10), ema_fast[-10:], 1)[0]
                trend_consistency = abs(ema_trend) / np.mean(ema_fast[-10:]) * 100
            else:
                trend_consistency = 0
            
            # 6. Recent Volatility
            if len(prices) >= 5:
                recent_volatility = np.std(prices[-5:]) / np.mean(prices[-5:]) * 100
            else:
                recent_volatility = 0
            
            features = np.array([ema_diff, abs(ema_momentum), atr_ratio, abs(price_vs_ema), 
                               trend_consistency, recent_volatility])
            return features
            
        except Exception as e:
            print(f"Signal feature extraction error: {e}")
            return np.zeros(6)
    
    def calculate_confidence(self, ema_fast, ema_slow, atr, prices, volume=None, signal_type=None):
        """Calculate signal confidence score (0.0 to 1.0)"""
        features = self.extract_signal_features(ema_fast, ema_slow, atr, prices, volume)
        
        # Store features for training (with dummy label for now)
        if signal_type:
            label = 1 if signal_type in ['BUY', 'SELL'] else 0
            self.training_data.append((features, label))
            
            # Auto-save every 5 new training examples
            if len(self.training_data) % 5 == 0:
                self.save_data()
        
        # Train model if we have enough data
        if len(self.training_data) >= 50 and not self.is_fitted:
            self._train_model()
        
        if not self.is_fitted:
            # Use rule-based confidence until model is trained
            return self._rule_based_confidence(features)
        
        try:
            # Use trained model
            features_scaled = self.scaler.transform(features.reshape(1, -1))
            confidence = self.rf_model.predict_proba(features_scaled)[0][1]  # Probability of positive class
            return min(max(confidence, 0.0), 1.0)
            
        except Exception as e:
            print(f"Confidence calculation error: {e}")
            return self._rule_based_confidence(features)
    
    def _train_model(self):
        """Train the Random Forest model"""
        try:
            if len(self.training_data) < 50:
                return
                
            X = np.array([item[0] for item in self.training_data])
            y = np.array([item[1] for item in self.training_data])
            
            X_scaled = self.scaler.fit_transform(X)
            self.rf_model.fit(X_scaled, y)
            self.is_fitted = True
            print("AI: Signal confidence model trained successfully")
            
            # Save immediately after training
            self.save_data()
            
        except Exception as e:
            print(f"Confidence model training error: {e}")
    
    def _rule_based_confidence(self, features):
        """Fallback rule-based confidence calculation"""
        ema_diff, ema_momentum, atr_ratio, price_vs_ema, trend_consistency, volatility = features
        
        # Normalize and weight factors
        confidence = 0.0
        
        # Strong EMA difference
        if ema_diff > 0.1:
            confidence += 0.25
        elif ema_diff > 0.05:
            confidence += 0.15
        
        # Good momentum
        if ema_momentum > 0.1:
            confidence += 0.2
        elif ema_momentum > 0.05:
            confidence += 0.1
        
        # Appropriate volatility
        if 0.8 <= atr_ratio <= 1.5:
            confidence += 0.2
        elif 0.6 <= atr_ratio <= 2.0:
            confidence += 0.1
        
        # Trend consistency
        if trend_consistency > 0.05:
            confidence += 0.2
        elif trend_consistency > 0.02:
            confidence += 0.1
        
        # Moderate volatility preference
        if volatility < 2.0:
            confidence += 0.15
        
        return min(confidence, 1.0)

# AI Manager with auto-save functionality
class AITradingManager:
    def __init__(self):
        self.regime_detector = MarketRegimeDetector()
        self.signal_confidence = SignalConfidenceAI()
        self.regime_names = {0: "Trending", 1: "Ranging", 2: "Volatile"}
        
    def save_all_data(self):
        """Save all AI data when shutting down"""
        print("💾 Saving all AI training data...")
        self.regime_detector.save_data()
        self.signal_confidence.save_data()
        print("✅ All AI data saved successfully!")
        
    def analyze_market(self, prices, ema_fast, ema_slow, atr, volume=None):
        """Complete AI market analysis"""
        # Detect regime
        regime = self.regime_detector.detect_regime(prices, atr, volume)
        
        # Calculate confidence for potential signals
        confidence = self.signal_confidence.calculate_confidence(
            ema_fast, ema_slow, atr, prices, volume
        )
        
        # Decision logic
        should_trade = (
            regime != 1 and  # Not ranging market
            confidence > 0.65  # High confidence threshold
        )
        
        return {
            'regime': regime,
            'regime_name': self.regime_names[regime],
            'confidence': confidence,
            'should_trade': should_trade,
            'reason': self._get_decision_reason(regime, confidence)
        }
    
    def _get_decision_reason(self, regime, confidence):
        """Get human-readable decision reason"""
        if regime == 1:
            return f"Ranging market (confidence: {confidence:.2f})"
        elif confidence <= 0.65:
            return f"Low confidence: {confidence:.2f}"
        else:
            return f"{self.regime_names[regime]} market, confidence: {confidence:.2f}"


def move_sl_to_breakeven(position):
        try:
            current_price = mt5.symbol_info_tick(symbol).last
            entry_price = position.price_open
            current_sl = position.sl
            current_tp = position.tp
            
            # 計算半個TP距離
            if position.type == mt5.POSITION_TYPE_BUY:
                half_tp_price = entry_price + (current_tp - entry_price) / 2
                # 如果當前價格達到半個TP，且還沒移動到breakeven
                if current_price >= half_tp_price and current_sl < entry_price:
                    print(f"BUY條件檢查: 當前價格={current_price:.2f}, 半TP價格={half_tp_price:.2f}, 入場價={entry_price:.2f}, 當前止損={current_sl:.2f}")
                    modify_request = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "symbol": symbol,
                        "position": position.ticket,
                        "sl": entry_price,  # 移動到breakeven
                        "tp": current_tp,
                    }
                    result = mt5.order_send(modify_request)
                    if result.retcode == mt5.TRADE_RETCODE_DONE:
                        print(f"BUY止損已移動到breakeven: {entry_price}")
                        return True
            elif position.type == mt5.POSITION_TYPE_SELL:
                    half_tp_price = entry_price - (entry_price - current_tp) / 2
                    # 如果當前價格達到半個TP，且還沒移動到breakeven
                    if current_price <= half_tp_price and current_sl > entry_price:
                        print(f"SELL條件檢查: 當前價格={current_price:.2f}, 半TP價格={half_tp_price:.2f}, 入場價={entry_price:.2f}, 當前止損={current_sl:.2f}")
                        modify_request = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "symbol": symbol,
                            "position": position.ticket,
                            "sl": entry_price,  # 移動到breakeven
                            "tp": current_tp,
                        }
                        result = mt5.order_send(modify_request)
                        if result.retcode == mt5.TRADE_RETCODE_DONE:
                            print(f"SELL止損已移動到breakeven: {entry_price}")
                            return True
                        
        except Exception as e:
            print(f"移動止損失敗: {e}")
        return False

def get_today_pnl(server_info):
    """
    使用日期計算今日損益 (簡化版本)
    """
    try:
        if server_info is None:
            return 0
            
        # 使用當地時間的今日開始時間 (00:00:00)
        today = datetime.now().date()
        today_start = datetime.combine(today, datetime.min.time())
        now = datetime.now() + timedelta(days=1)

        # 1. 今日已平倉損益
        deals = mt5.history_deals_get(today_start, now)
        realized_pnl = 0
        if deals:
            for deal in deals:
                if deal.symbol == symbol and deal.type in [mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL] and deal.reason != 1:
                    # 確認交易是今日發生的
                    deal_time = datetime.fromtimestamp(deal.time)
                    if deal_time.date() == today:
                        realized_pnl += deal.profit

        # 2. 當前持倉浮動損益 (只計算今日開倉的)
        positions = mt5.positions_get(symbol=symbol)
        unrealized_pnl = 0
        if positions:
            for pos in positions:
                # 檢查是否為今日開倉
                pos_time = datetime.fromtimestamp(pos.time)
                if pos_time.date() == today:
                    unrealized_pnl += pos.profit

        return realized_pnl + unrealized_pnl
        
    except Exception as e:
        print(f"計算PnL失敗: {e}")
        return 0
        
def get_trade_count(server_info):
    """
    獲取今日交易次數
    """
    try:
        if server_info is None:
            return 0
            
        today = datetime.now().date()
        today_start = datetime.combine(today, datetime.min.time())
        now = datetime.now() + timedelta(days=1)
        
        # 獲取今日的交易歷史
        trades = mt5.history_deals_get(today_start, now)
        trades = [trade for trade in trades if trade.reason == 1]
        if trades is None:
            return 0
            
        return len(trades)
        
    except Exception as e:
        print(f"獲取交易次數失敗: {e}")
        return 0
    
def get_current_holding():
    """
    獲取當前持倉狀態
    """
    positions = mt5.positions_get(symbol=symbol)
    if positions and len(positions) > 0:
        pos_type = positions[0].type
        if pos_type == mt5.POSITION_TYPE_BUY:
            return "BUY"
        elif pos_type == mt5.POSITION_TYPE_SELL:
            return "SELL"
        move_sl_to_breakeven(positions[0])
    return "None"

class TradingBotUI:
    def __init__(self, root):
        self.root = root
        self.root.title("StrategyBasedBOT AI 增強版 - 狀態面板")
        self.status_text = tk.StringVar()
        self.pnl_text = tk.StringVar()
        self.holding_text = tk.StringVar()
        self.signal_text = tk.StringVar()
        self.balance_text = tk.StringVar()
        self.time_now_text = tk.StringVar()
        self.last_time_update_text = tk.StringVar()
        self.trade_count_text = tk.StringVar()
        self.ai_status_text = tk.StringVar()

        # AI 狀態標籤 (置頂顯示)
        self.ai_status_label = tk.Label(root, textvariable=self.ai_status_text, font=("Arial", 12, "bold"), fg="purple", bg="lightyellow")
        self.ai_status_label.pack(pady=5, fill='x')
        
        self.status_label = tk.Label(root, textvariable=self.status_text, font=("Arial", 12), fg="blue")
        self.status_label.pack(pady=5)
        self.pnl_label = tk.Label(root, textvariable=self.pnl_text, font=("Arial", 12))
        self.pnl_label.pack(pady=5)
        self.balance_label = tk.Label(root, textvariable=self.balance_text, font=("Arial", 12))
        self.balance_label.pack(pady=5)
        self.holding_label = tk.Label(root, textvariable=self.holding_text, font=("Arial", 12))
        self.holding_label.pack(pady=5)
        self.signal_label = tk.Label(root, textvariable=self.signal_text, font=("Arial", 12))
        self.signal_label.pack(pady=5)
        self.time_now_label = tk.Label(root, textvariable=self.time_now_text, font=("Arial", 12))
        self.time_now_label.pack(pady=5)
        self.last_time_update_label = tk.Label(root, textvariable=self.last_time_update_text, font=("Arial", 12))
        self.last_time_update_label.pack(pady=5)
        self.trade_count_label = tk.Label(root, textvariable=self.trade_count_text, font=("Arial", 12))
        self.trade_count_label.pack(pady=5)
        
        self.status_text.set("AI 系統初始化中...")
        self.ai_status_text.set("AI 分析: 初始化中...")

    def update(self, status, pnl, balance, holding, signal, time_now, last_time_update, trade_count=0, ai_status=None):
        self.status_text.set(status)
        self.pnl_text.set(f"今日損益: {pnl:.2f}")
        self.balance_text.set(f"帳戶餘額: {balance:.2f}")
        self.holding_text.set(f"當前持倉: {holding}")
        self.signal_text.set(f"最新信號: {signal}")
        self.time_now_text.set(f"當前時間: {time_now}")
        self.last_time_update_text.set(f"最後更新時間: {last_time_update}")
        self.trade_count_text.set(f"交易次數: {trade_count}")
        
        if ai_status:
            self.ai_status_text.set(f"🤖 AI 分析: {ai_status}")
        else:
            self.ai_status_text.set("🤖 AI 分析: 等待數據...")

    def update_ai_status(self, regime_name, confidence, should_trade, reason):
        """專門更新 AI 狀態的方法"""
        trade_action = "✅ 可交易" if should_trade else "❌ 跳過"
        color = "green" if should_trade else "red"
        
        ai_text = f"市場狀態: {regime_name} | 信心度: {confidence:.2f} | {trade_action} | {reason}"
        self.ai_status_text.set(f"🤖 {ai_text}")
        self.ai_status_label.config(fg=color)



    
def trading_loop(ui: TradingBotUI, trading_company, percentage_of_risk=0.01, daily_max_loss_percentage=0.05): 
    if not mt5.initialize():
        ui.update("MetaTrader 5 初始化失敗", 0, 0, "None", "None")
        return
    
    # Initialize AI manager with persistence
    ai_manager = AITradingManager()
    
    # Register cleanup function to save data on exit
    import atexit
    atexit.register(ai_manager.save_all_data)
    
    account_info = mt5.account_info()
    server_info = mt5.terminal_info()
    status = ""
    signal = "None"
    balance = account_info.balance if account_info else 0
    today_pnl = get_today_pnl(server_info)
    trade_count = get_trade_count(server_info)
    currentHolding = get_current_holding()
    last_time_update = datetime.now().strftime("%H:%M:%S")
    ui.update(status, today_pnl, balance, currentHolding, signal,datetime.now().strftime("%H:%M:%S"), last_time_update,trade_count)

    while True:
        now = datetime.now()
        # 風控
        ui.update(status, today_pnl, balance, currentHolding, signal,datetime.now().strftime("%H:%M:%S"), last_time_update,trade_count)
        if now.minute % 15 == 0 and now.second == 0:
            account_info = mt5.account_info()
            server_info = mt5.terminal_info()
            if account_info is None:
                ui.update("取得帳戶資訊失敗", 0, 0, currentHolding, "None")
                time.sleep(1)
                continue
            if account_info.trade_allowed == False:
                ui.update("交易未啟用", 0, 0, "None", "None")
                continue

            # 15 minutes checking
            last_time_update=datetime.now().strftime("%H:%M:%S")
            trade_count = get_trade_count(server_info)
            balance = account_info.balance  
            currentHolding = get_current_holding()

            daily_max_profit_dynamic = balance * daily_max_loss_percentage

            if today_pnl >= daily_max_profit_dynamic:
                status = "已達日內最大獲利，暫停交易"
                ui.update(status, today_pnl, balance, currentHolding, signal,datetime.
                          now().strftime("%H:%M:%S"), last_time_update,trade_count)
                time.sleep(60)
                continue
            if today_pnl <= -daily_max_loss:
                status = "已達日內最大虧損，暫停交易"
                ui.update(status, today_pnl, balance, currentHolding, signal,datetime.
                          now().strftime("%H:%M:%S"), last_time_update,trade_count)
                time.sleep(60)
                continue

            # 取得最新K線資料
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 100)
            if rates is None or len(rates) < slow + 1:
                status = "K線資料不足，等待中"
                ui.update(status, today_pnl, balance, currentHolding, signal,datetime.
                          now().strftime("%H:%M:%S"), last_time_update,trade_count)
                time.sleep(1)
                continue

            close_prices = [bar['close'] for bar in rates]
            ema_fast = calculate_ema(close_prices, fast)
            ema_slow = calculate_ema(close_prices, slow)
            atr = calculate_atr([{'high': bar['high'], 'low': bar['low'], 'close': bar['close']} for bar in rates], 14)
            
            # AI Analysis
            try:
                ai_analysis = ai_manager.analyze_market(
                    close_prices, ema_fast, ema_slow, atr
                )
                
                # Update AI status in UI
                ui.update_ai_status(
                    ai_analysis['regime_name'],
                    ai_analysis['confidence'],
                    ai_analysis['should_trade'],
                    ai_analysis['reason']
                )
                
                ai_status = f"AI: {ai_analysis['regime_name']} 市場 (信心度: {ai_analysis['confidence']:.2f})"
                print(f"AI 分析: {ai_status}")
                
            except Exception as e:
                print(f"AI 分析錯誤: {e}")
                ai_analysis = {'should_trade': True, 'reason': 'AI 分析失敗，使用基本策略'}
                ai_status = "AI 分析失敗"
                ui.update_ai_status("錯誤", 0.0, True, "AI 分析失敗，使用基本策略")
            
            # 訊號偵測
            basic_signal = None
            if ema_fast[-2] < ema_slow[-2] and ema_fast[-1] > ema_slow[-1] and currentHolding == "None":
                basic_signal = "BUY"
            elif ema_fast[-2] > ema_slow[-2] and ema_fast[-1] < ema_slow[-1] and currentHolding == "None":
                basic_signal = "SELL"
            
            # AI-Enhanced Trading Decision
            if basic_signal and ai_analysis['should_trade']:
                entry_price = close_prices[-1]
                
                if basic_signal == "BUY":
                    sl = entry_price - atr_mult_sl * atr[-1]
                    tp = entry_price + atr_mult_tp * atr[-1]
                else:  # SELL
                    sl = entry_price + atr_mult_sl * atr[-1]
                    tp = entry_price - atr_mult_tp * atr[-1]
                
                sl_distance = abs(entry_price - sl)
                risk_per_trade = min(balance * percentage_of_risk, daily_max_loss)
                lot_size = risk_per_trade / (sl_distance * contract_size) if sl_distance > 0 else 0.01
                lot_size = max(0.01, round(lot_size, 2))
                
                status = f"AI 確認下單 {basic_signal}: lot={lot_size:.2f}, sl={sl:.2f}, tp={tp:.2f} | {ai_status}"
                signal = basic_signal
                place_trade(symbol, basic_signal, lot_size, sl, tp, entry_price, trading_company)
                currentHolding = basic_signal
                
            elif basic_signal and not ai_analysis['should_trade']:
                status = f"AI 建議跳過 {basic_signal} 訊號: {ai_analysis['reason']} | {ai_status}"
                signal = f"跳過 {basic_signal}"
                
            else:
                status = f"等待交易訊號 | {ai_status}"

            ui.update(status, today_pnl, balance, currentHolding, signal,datetime.now().strftime("%H:%M:%S"), last_time_update,trade_count)

        time.sleep(1)

def run_account():
    percentage_of_risk = float(input("設定每單最大虧損:(E.g 0.01 = 1% , 0.1 = 10%...ETC)\n"))
    trading_company = input("請輸入交易公司:\n")
    daily_max_loss_percentage = float(input("設定每日最大虧損百分比:(E.g 0.05 = 5% , 0.1 = 10%...ETC)\n"))
    root = tk.Tk()
    ui = TradingBotUI(root)
    t = Thread(target=trading_loop, args=(ui, trading_company, percentage_of_risk,daily_max_loss_percentage), daemon=True)
    t.start()
    root.mainloop()

if __name__ == "__main__":
    run_account()