import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime
import numpy as np

# 設置中文字體
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False

# 讀取數據
df = pd.read_csv('src/backtest_trades.csv')

# 清理列名（去除空格）
df.columns = df.columns.str.strip()

# 轉換時間格式
df['entry_time'] = pd.to_datetime(df['entry_time'])
df['exit_time'] = pd.to_datetime(df['exit_time'])

# 提取進場時間的小時
df['entry_hour'] = df['entry_time'].dt.hour

# 判斷是否為盈利交易
df['is_win'] = df['pnl'] > 0

# 定義交易時段
def classify_session(hour):
    if 0 <= hour < 6:
        return '亞洲早盤 (00:00-06:00)'
    elif 6 <= hour < 12:
        return '亞洲午盤 (06:00-12:00)'
    elif 12 <= hour < 18:
        return '歐洲盤 (12:00-18:00)'
    elif 18 <= hour < 24:
        return '美洲盤 (18:00-24:00)'

df['session'] = df['entry_hour'].apply(classify_session)

# 計算每個時段的統計數據
session_stats = df.groupby('session').agg({
    'is_win': ['count', 'sum', 'mean'],
    'pnl': ['sum', 'mean']
}).round(4)

session_stats.columns = ['總交易數', '盈利交易數', '勝率', '總損益', '平均損益']

print("各時段交易統計:")
print(session_stats)
print("\n")

# 按小時計算統計數據
hourly_stats = df.groupby('entry_hour').agg({
    'is_win': ['count', 'sum', 'mean'],
    'pnl': ['sum', 'mean']
}).round(4)

hourly_stats.columns = ['總交易數', '盈利交易數', '勝率', '總損益', '平均損益']

# 創建圖表
fig, axes = plt.subplots(2, 2, figsize=(16, 12))
fig.suptitle('交易時段分析', fontsize=16, fontweight='bold')

# 1. 各時段勝率條形圖
ax1 = axes[0, 0]
sessions = session_stats.index
win_rates = session_stats['勝率'].values
colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A']

bars1 = ax1.bar(sessions, win_rates, color=colors, alpha=0.8, edgecolor='black', linewidth=1)
ax1.set_title('各時段勝率比較', fontsize=12, fontweight='bold')
ax1.set_ylabel('勝率')
ax1.set_ylim(0, 1)
ax1.grid(True, alpha=0.3)

# 在條形圖上添加數值標籤
for bar, rate in zip(bars1, win_rates):
    height = bar.get_height()
    ax1.text(bar.get_x() + bar.get_width()/2., height + 0.01,
             f'{rate:.1%}', ha='center', va='bottom', fontweight='bold')

# 旋轉x軸標籤
ax1.tick_params(axis='x', rotation=45)

# 2. 各時段交易數量
ax2 = axes[0, 1]
trade_counts = session_stats['總交易數'].values
bars2 = ax2.bar(sessions, trade_counts, color=colors, alpha=0.8, edgecolor='black', linewidth=1)
ax2.set_title('各時段交易數量', fontsize=12, fontweight='bold')
ax2.set_ylabel('交易數量')
ax2.grid(True, alpha=0.3)

# 添加數值標籤
for bar, count in zip(bars2, trade_counts):
    height = bar.get_height()
    ax2.text(bar.get_x() + bar.get_width()/2., height + 0.5,
             f'{int(count)}', ha='center', va='bottom', fontweight='bold')

ax2.tick_params(axis='x', rotation=45)

# 3. 24小時勝率分布
ax3 = axes[1, 0]
hours = hourly_stats.index
hourly_win_rates = hourly_stats['勝率'].values

# 創建漸變顏色
colors_hourly = plt.cm.viridis(np.linspace(0, 1, len(hours)))
bars3 = ax3.bar(hours, hourly_win_rates, color=colors_hourly, alpha=0.8, edgecolor='black', linewidth=0.5)
ax3.set_title('24小時勝率分布', fontsize=12, fontweight='bold')
ax3.set_xlabel('小時')
ax3.set_ylabel('勝率')
ax3.set_xticks(range(0, 24, 2))
ax3.set_ylim(0, 1)
ax3.grid(True, alpha=0.3)

# 4. 各時段平均損益
ax4 = axes[1, 1]
avg_pnl = session_stats['平均損益'].values
colors_pnl = ['red' if x < 0 else 'green' for x in avg_pnl]
bars4 = ax4.bar(sessions, avg_pnl, color=colors_pnl, alpha=0.8, edgecolor='black', linewidth=1)
ax4.set_title('各時段平均損益', fontsize=12, fontweight='bold')
ax4.set_ylabel('平均損益')
ax4.axhline(y=0, color='black', linestyle='-', alpha=0.5)
ax4.grid(True, alpha=0.3)

# 添加數值標籤
for bar, pnl in zip(bars4, avg_pnl):
    height = bar.get_height()
    ax4.text(bar.get_x() + bar.get_width()/2., height + (5 if height > 0 else -15),
             f'{pnl:.1f}', ha='center', va='bottom' if height > 0 else 'top', fontweight='bold')

ax4.tick_params(axis='x', rotation=45)

plt.tight_layout()
plt.savefig('time_session_winrate_analysis.png', dpi=300, bbox_inches='tight')
plt.show()

# 輸出最佳時段
best_session = session_stats.loc[session_stats['勝率'].idxmax()]
worst_session = session_stats.loc[session_stats['勝率'].idxmin()]

print(f"最佳時段: {session_stats['勝率'].idxmax()}")
print(f"勝率: {best_session['勝率']:.1%}")
print(f"交易數: {int(best_session['總交易數'])}")
print(f"平均損益: {best_session['平均損益']:.2f}")
print()
print(f"最差時段: {session_stats['勝率'].idxmin()}")
print(f"勝率: {worst_session['勝率']:.1%}")
print(f"交易數: {int(worst_session['總交易數'])}")
print(f"平均損益: {worst_session['平均損益']:.2f}")

# 創建詳細的小時級別分析表
print("\n24小時詳細統計:")
print("小時\t交易數\t勝率\t\t平均損益")
print("-" * 40)
for hour in range(24):
    if hour in hourly_stats.index:
        stats = hourly_stats.loc[hour]
        print(f"{hour:02d}:00\t{int(stats['總交易數'])}\t{stats['勝率']:.1%}\t\t{stats['平均損益']:.2f}")
    else:
        print(f"{hour:02d}:00\t0\t-\t\t-")
