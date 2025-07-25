import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# Set font for better display (remove Chinese font settings)
plt.rcParams['font.family'] = 'DejaVu Sans'
plt.rcParams['axes.unicode_minus'] = False

def load_and_analyze_trades(csv_file):
    """Load and analyze backtest trade data"""
    
    # Read CSV file
    df = pd.read_csv(csv_file)
    
    # Convert time format
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    df['exit_time'] = pd.to_datetime(df['exit_time'])
    
    # Calculate trade duration
    df['duration'] = df['exit_time'] - df['entry_time']
    df['duration_hours'] = df['duration'].dt.total_seconds() / 3600
    
    # Calculate return percentage
    df['return_pct'] = (df['pnl'] / (df['entry'] * df['lot'] * 100)) * 100
    
    # Add year-month information
    df['year_month'] = df['entry_time'].dt.to_period('M')
    df['year'] = df['entry_time'].dt.year
    
    return df

def calculate_performance_metrics(df):
    """Calculate performance metrics"""
    
    # Basic statistics
    total_trades = len(df)
    winning_trades = len(df[df['pnl'] > 0])
    losing_trades = len(df[df['pnl'] < 0])
    win_rate = winning_trades / total_trades * 100 if total_trades > 0 else 0
    
    # P&L statistics
    total_pnl = df['pnl'].sum()
    avg_win = df[df['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0
    avg_loss = df[df['pnl'] < 0]['pnl'].mean() if losing_trades > 0 else 0
    profit_factor = abs(df[df['pnl'] > 0]['pnl'].sum() / df[df['pnl'] < 0]['pnl'].sum()) if losing_trades > 0 else float('inf')
    
    # Maximum drawdown
    df['cumulative_pnl'] = df['pnl'].cumsum()
    df['peak'] = df['cumulative_pnl'].expanding().max()
    df['drawdown'] = df['cumulative_pnl'] - df['peak']
    max_drawdown = df['drawdown'].min()
    
    # Consecutive losses statistics
    df['is_loss'] = df['pnl'] < 0
    consecutive_losses = []
    current_streak = 0
    
    for loss in df['is_loss']:
        if loss:
            current_streak += 1
        else:
            if current_streak > 0:
                consecutive_losses.append(current_streak)
            current_streak = 0
    
    if current_streak > 0:
        consecutive_losses.append(current_streak)
    
    max_consecutive_losses = max(consecutive_losses) if consecutive_losses else 0
    
    # Annualized return
    start_date = df['entry_time'].min()
    end_date = df['exit_time'].max()
    trading_days = (end_date - start_date).days
    initial_balance = 500000  # Initial balance from CSV
    final_balance = df['balance'].iloc[-1]
    total_return = (final_balance - initial_balance) / initial_balance
    annualized_return = (1 + total_return) ** (365 / trading_days) - 1 if trading_days > 0 else 0
    
    metrics = {
        'Total Trades': total_trades,
        'Winning Trades': winning_trades,
        'Losing Trades': losing_trades,
        'Win Rate (%)': round(win_rate, 2),
        'Total PnL': round(total_pnl, 2),
        'Average Win': round(avg_win, 2),
        'Average Loss': round(avg_loss, 2),
        'Profit Factor': round(profit_factor, 2),
        'Max Drawdown': round(max_drawdown, 2),
        'Max Consecutive Losses': max_consecutive_losses,
        'Initial Balance': initial_balance,
        'Final Balance': round(final_balance, 2),
        'Total Return (%)': round(total_return * 100, 2),
        'Annualized Return (%)': round(annualized_return * 100, 2),
        'Trading Period (Days)': trading_days
    }
    
    return metrics, df

def create_visualizations(df, metrics):
    """Create visualization charts"""
    
    # Set chart style
    plt.style.use('default')
    fig = plt.figure(figsize=(24, 20))  # Increased size for additional chart
    
    # 1. Balance Curve
    plt.subplot(4, 3, 1)
    plt.plot(df['exit_time'], df['balance'], linewidth=2, color='blue')
    plt.title('Balance Curve', fontsize=14, fontweight='bold')
    plt.xlabel('Time')
    plt.ylabel('Balance')
    plt.grid(True, alpha=0.3)
    
    # 2. Cumulative PnL
    plt.subplot(4, 3, 2)
    plt.plot(df['exit_time'], df['cumulative_pnl'], linewidth=2, color='green')
    plt.title('Cumulative PnL', fontsize=14, fontweight='bold')
    plt.xlabel('Time')
    plt.ylabel('Cumulative PnL')
    plt.grid(True, alpha=0.3)
    
    # 3. Drawdown Curve
    plt.subplot(4, 3, 3)
    plt.fill_between(df['exit_time'], df['drawdown'], 0, alpha=0.7, color='red')
    plt.title('Drawdown Curve', fontsize=14, fontweight='bold')
    plt.xlabel('Time')
    plt.ylabel('Drawdown')
    plt.grid(True, alpha=0.3)
    
    # 4. Individual Trade PnL Distribution
    plt.subplot(4, 3, 4)
    plt.hist(df['pnl'], bins=50, alpha=0.7, edgecolor='black')
    plt.axvline(x=0, color='red', linestyle='--', linewidth=2)
    plt.title('Trade PnL Distribution', fontsize=14, fontweight='bold')
    plt.xlabel('Individual PnL')
    plt.ylabel('Frequency')
    plt.grid(True, alpha=0.3)
    
    # 5. Trade Type Analysis
    plt.subplot(4, 3, 5)
    type_performance = df.groupby('type')['pnl'].sum()
    colors = ['lightblue', 'lightcoral']
    bars = plt.bar(type_performance.index, type_performance.values, color=colors, edgecolor='black')
    plt.title('BUY vs SELL Performance', fontsize=14, fontweight='bold')
    plt.xlabel('Trade Type')
    plt.ylabel('Total PnL')
    plt.grid(True, alpha=0.3, axis='y')
    
    # Display values on bars
    for bar in bars:
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.0f}',
                ha='center', va='bottom' if height >= 0 else 'top')
    
    # 6. Monthly Performance
    plt.subplot(4, 3, 6)
    monthly_pnl = df.groupby('year_month')['pnl'].sum()
    colors = ['green' if x >= 0 else 'red' for x in monthly_pnl.values]
    bars = plt.bar(range(len(monthly_pnl)), monthly_pnl.values, color=colors, alpha=0.7)
    plt.title('Monthly PnL', fontsize=14, fontweight='bold')
    plt.xlabel('Month')
    plt.ylabel('Monthly PnL')
    plt.xticks(range(len(monthly_pnl)), [str(x) for x in monthly_pnl.index], rotation=45)
    plt.grid(True, alpha=0.3, axis='y')
    
    # 7. Trade Duration Analysis
    plt.subplot(4, 3, 7)
    plt.hist(df['duration_hours'], bins=30, alpha=0.7, edgecolor='black', color='orange')
    plt.title('Trade Duration Distribution', fontsize=14, fontweight='bold')
    plt.xlabel('Duration (Hours)')
    plt.ylabel('Frequency')
    plt.grid(True, alpha=0.3)
    
    # 8. Win Rate Change Over Time (30-trade moving average)
    plt.subplot(4, 3, 8)
    df['win'] = (df['pnl'] > 0).astype(int)
    df['rolling_winrate'] = df['win'].rolling(window=30, min_periods=1).mean() * 100
    plt.plot(df['exit_time'], df['rolling_winrate'], linewidth=2, color='purple')
    plt.axhline(y=50, color='red', linestyle='--', alpha=0.7)
    plt.title('Win Rate Evolution (30-Trade MA)', fontsize=14, fontweight='bold')
    plt.xlabel('Time')
    plt.ylabel('Win Rate (%)')
    plt.grid(True, alpha=0.3)
    
    # 9. Annual Performance Comparison
    plt.subplot(4, 3, 9)
    yearly_pnl = df.groupby('year')['pnl'].sum()
    colors = ['green' if x >= 0 else 'red' for x in yearly_pnl.values]
    bars = plt.bar(yearly_pnl.index, yearly_pnl.values, color=colors, alpha=0.7, edgecolor='black')
    plt.title('Annual PnL', fontsize=14, fontweight='bold')
    plt.xlabel('Year')
    plt.ylabel('Annual PnL')
    plt.grid(True, alpha=0.3, axis='y')
    
    # Display values on bars
    for bar in bars:
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.0f}',
                ha='center', va='bottom' if height >= 0 else 'top')
    
    # 10. Exit Reason Analysis
    plt.subplot(4, 3, 10)
    if 'exit_reason' in df.columns:
        exit_counts = df['exit_reason'].value_counts()
        colors_exit = plt.cm.Set3(np.linspace(0, 1, len(exit_counts)))
        bars = plt.bar(exit_counts.index, exit_counts.values, color=colors_exit, edgecolor='black')
        plt.title('Exit Reason Distribution', fontsize=14, fontweight='bold')
        plt.xlabel('Exit Reason')
        plt.ylabel('Count')
        plt.xticks(rotation=45, ha='right')
        plt.grid(True, alpha=0.3, axis='y')
        
        # Display values on bars
        for bar in bars:
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2., height,
                    f'{int(height)}',
                    ha='center', va='bottom')
    
    # 11. Exit Reason Performance Analysis
    plt.subplot(4, 3, 11)
    if 'exit_reason' in df.columns:
        exit_pnl = df.groupby('exit_reason')['pnl'].sum()
        colors_perf = ['green' if x >= 0 else 'red' for x in exit_pnl.values]
        bars = plt.bar(exit_pnl.index, exit_pnl.values, color=colors_perf, alpha=0.7, edgecolor='black')
        plt.title('Exit Reason Performance', fontsize=14, fontweight='bold')
        plt.xlabel('Exit Reason')
        plt.ylabel('Total PnL')
        plt.xticks(rotation=45, ha='right')
        plt.grid(True, alpha=0.3, axis='y')
        
        # Display values on bars
        for bar in bars:
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2., height,
                    f'{height:.0f}',
                    ha='center', va='bottom' if height >= 0 else 'top')
    
    # 12. Exit Reason Win Rate
    plt.subplot(4, 3, 12)
    if 'exit_reason' in df.columns:
        exit_winrate = df.groupby('exit_reason').apply(lambda x: (x['pnl'] > 0).mean() * 100)
        bars = plt.bar(exit_winrate.index, exit_winrate.values, color='skyblue', alpha=0.7, edgecolor='black')
        plt.title('Exit Reason Win Rate', fontsize=14, fontweight='bold')
        plt.xlabel('Exit Reason')
        plt.ylabel('Win Rate (%)')
        plt.xticks(rotation=45, ha='right')
        plt.axhline(y=50, color='red', linestyle='--', alpha=0.7)
        plt.grid(True, alpha=0.3, axis='y')
        
        # Display values on bars
        for bar in bars:
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2., height,
                    f'{height:.1f}%',
                    ha='center', va='bottom')
    
    plt.tight_layout()
    plt.savefig('backtest_analysis.png', dpi=300, bbox_inches='tight')
    plt.show()

def print_detailed_analysis(df, metrics):
    """Print detailed analysis report"""
    
    print("=" * 80)
    print("                    BACKTEST TRADING ANALYSIS REPORT")
    print("=" * 80)
    
    # Basic performance metrics
    print("\n📊 Basic Performance Metrics:")
    print("-" * 50)
    for key, value in metrics.items():
        print(f"{key:<25}: {value}")
    
    # Trade type analysis
    print("\n📈 Trade Type Analysis:")
    print("-" * 50)
    type_analysis = df.groupby('type').agg({
        'pnl': ['count', 'sum', 'mean'],
        'lot': 'mean'
    }).round(2)
    
    buy_trades = df[df['type'] == 'BUY']
    sell_trades = df[df['type'] == 'SELL']
    
    print(f"BUY Trades:")
    print(f"  - Trade Count: {len(buy_trades)}")
    print(f"  - Total PnL: {buy_trades['pnl'].sum():.2f}")
    print(f"  - Average PnL: {buy_trades['pnl'].mean():.2f}")
    print(f"  - Win Rate: {(buy_trades['pnl'] > 0).mean() * 100:.2f}%")
    
    print(f"\nSELL Trades:")
    print(f"  - Trade Count: {len(sell_trades)}")
    print(f"  - Total PnL: {sell_trades['pnl'].sum():.2f}")
    print(f"  - Average PnL: {sell_trades['pnl'].mean():.2f}")
    print(f"  - Win Rate: {(sell_trades['pnl'] > 0).mean() * 100:.2f}%")
    
    # Time analysis
    print("\n⏰ Trading Time Analysis:")
    print("-" * 50)
    print(f"Average Holding Time: {df['duration_hours'].mean():.2f} hours")
    print(f"Maximum Holding Time: {df['duration_hours'].max():.2f} hours")
    print(f"Minimum Holding Time: {df['duration_hours'].min():.2f} hours")
    
    # Risk indicators
    print("\n⚠️ Risk Indicators:")
    print("-" * 50)
    print(f"Maximum Single Loss: {df['pnl'].min():.2f}")
    print(f"Maximum Single Profit: {df['pnl'].max():.2f}")
    print(f"Standard Deviation: {df['pnl'].std():.2f}")
    print(f"Sharpe Ratio: {(df['pnl'].mean() / df['pnl'].std()):.4f}" if df['pnl'].std() != 0 else "N/A")
    
    # Monthly performance
    print("\n📅 Monthly Performance (First 10 months):")
    print("-" * 50)
    monthly_pnl = df.groupby('year_month')['pnl'].sum().head(10)
    for month, pnl in monthly_pnl.items():
        print(f"{month}: {pnl:.2f}")
    
    # Consecutive statistics
    print("\n🔗 Consecutive Statistics:")
    print("-" * 50)
    
    # Calculate consecutive wins and losses
    df['win'] = df['pnl'] > 0
    consecutive_wins = []
    consecutive_losses = []
    current_win_streak = 0
    current_loss_streak = 0
    
    for win in df['win']:
        if win:
            current_win_streak += 1
            if current_loss_streak > 0:
                consecutive_losses.append(current_loss_streak)
                current_loss_streak = 0
        else:
            current_loss_streak += 1
            if current_win_streak > 0:
                consecutive_wins.append(current_win_streak)
                current_win_streak = 0
    
    if current_win_streak > 0:
        consecutive_wins.append(current_win_streak)
    if current_loss_streak > 0:
        consecutive_losses.append(current_loss_streak)
    
    print(f"Maximum Consecutive Wins: {max(consecutive_wins) if consecutive_wins else 0}")
    print(f"Maximum Consecutive Losses: {max(consecutive_losses) if consecutive_losses else 0}")
    print(f"Average Consecutive Wins: {np.mean(consecutive_wins):.2f}" if consecutive_wins else "N/A")
    print(f"Average Consecutive Losses: {np.mean(consecutive_losses):.2f}" if consecutive_losses else "N/A")
    
    # Exit reason analysis
    if 'exit_reason' in df.columns:
        print("\n🚪 Exit Reason Analysis:")
        print("-" * 50)
        exit_stats = df.groupby('exit_reason').agg({
            'pnl': ['count', 'sum', 'mean'],
            'duration_hours': 'mean'
        }).round(2)
        
        for reason in df['exit_reason'].unique():
            reason_trades = df[df['exit_reason'] == reason]
            win_rate = (reason_trades['pnl'] > 0).mean() * 100
            print(f"{reason}:")
            print(f"  - Count: {len(reason_trades)}")
            print(f"  - Total PnL: {reason_trades['pnl'].sum():.2f}")
            print(f"  - Average PnL: {reason_trades['pnl'].mean():.2f}")
            print(f"  - Win Rate: {win_rate:.2f}%")
            if 'duration_hours' in reason_trades.columns:
                print(f"  - Avg Duration: {reason_trades['duration_hours'].mean():.2f} hours")
            print()

def main():
    """Main function"""
    try:
        # Load and analyze data
        print("Loading trading data...")
        df = load_and_analyze_trades('backtest_trades.csv')
        
        print("Calculating performance metrics...")
        metrics, df_enhanced = calculate_performance_metrics(df)
        
        print("Generating analysis report...")
        print_detailed_analysis(df_enhanced, metrics)
        
        print("\nCreating visualization charts...")
        create_visualizations(df_enhanced, metrics)
        
        # Save detailed data
        df_enhanced.to_csv('detailed_analysis.csv', index=False)
        print(f"\n✅ Analysis completed!")
        print(f"📊 Charts saved as: backtest_analysis.png")
        print(f"📋 Detailed data saved as: detailed_analysis.csv")
        
    except FileNotFoundError:
        print("❌ Error: Cannot find 'backtest_trades.csv' file")
        print("Please ensure the file exists in the current directory")
    except Exception as e:
        print(f"❌ Error occurred during analysis: {str(e)}")

if __name__ == "__main__":
    main()