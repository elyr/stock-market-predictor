"""
Investment Performance Calculator: Calculate portfolio value based on predictions
"""

import pandas as pd
import numpy as np
from datetime import datetime
import sys
import os

# Add src to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.data.collector import DataCollector
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class InvestmentCalculator:
    """Calculate investment performance based on predictions."""
    
    def __init__(self):
        self.data_collector = DataCollector()
    
    def calculate_portfolio_performance(self, investment_per_stock=100):
        """Calculate portfolio performance with equal investment in each predicted stock."""
        
        print("💰 INVESTMENT PERFORMANCE CALCULATOR")
        print("=" * 60)
        
        # Load the performance analysis results
        try:
            analysis_file = "data/performance_analysis_20251022_115608.csv"
            if not os.path.exists(analysis_file):
                print("❌ Performance analysis file not found. Run analyze_performance.py first.")
                return
            
            df = pd.read_csv(analysis_file)
            
            print(f"📊 Investment Strategy: ${investment_per_stock} per stock")
            print(f"📈 Total Initial Investment: ${len(df) * investment_per_stock}")
            print(f"📅 Investment Period: Based on yesterday's predictions")
            print()
            
            # Calculate investment details for each stock
            investment_results = []
            total_initial_value = 0
            total_current_value = 0
            
            print("🏦 INDIVIDUAL STOCK PERFORMANCE")
            print("-" * 80)
            print(f"{'Stock':<6} {'Initial':<10} {'Current':<10} {'Shares':<8} {'Gain/Loss':<12} {'Return%':<8}")
            print("-" * 80)
            
            for _, row in df.iterrows():
                symbol = row['Symbol']
                start_price = row['Start_Price']
                end_price = row['End_Price']
                percent_change = row['Percent_Change']
                
                # Calculate shares bought and current value
                shares_bought = investment_per_stock / start_price
                current_value = shares_bought * end_price
                gain_loss = current_value - investment_per_stock
                
                # Track totals
                total_initial_value += investment_per_stock
                total_current_value += current_value
                
                # Format for display
                gain_loss_str = f"+${gain_loss:.2f}" if gain_loss >= 0 else f"-${abs(gain_loss):.2f}"
                return_str = f"+{percent_change:.2f}%" if percent_change >= 0 else f"{percent_change:.2f}%"
                
                # Color coding for console
                emoji = "🟢" if gain_loss >= 0 else "🔴"
                
                print(f"{emoji} {symbol:<6} ${investment_per_stock:<9.2f} ${current_value:<9.2f} {shares_bought:<7.3f} {gain_loss_str:<11} {return_str:<8}")
                
                investment_results.append({
                    'Symbol': symbol,
                    'Initial_Investment': investment_per_stock,
                    'Shares_Bought': shares_bought,
                    'Start_Price': start_price,
                    'End_Price': end_price,
                    'Current_Value': current_value,
                    'Gain_Loss': gain_loss,
                    'Return_Percent': percent_change
                })
            
            print("-" * 80)
            
            # Calculate overall portfolio performance
            total_gain_loss = total_current_value - total_initial_value
            portfolio_return_percent = (total_gain_loss / total_initial_value) * 100
            
            print("\n💼 PORTFOLIO SUMMARY")
            print("=" * 40)
            print(f"Initial Investment:    ${total_initial_value:,.2f}")
            print(f"Current Value:         ${total_current_value:,.2f}")
            print(f"Total Gain/Loss:       ${total_gain_loss:+,.2f}")
            print(f"Portfolio Return:      {portfolio_return_percent:+.2f}%")
            
            # Performance analysis
            winning_stocks = len([r for r in investment_results if r['Gain_Loss'] > 0])
            losing_stocks = len([r for r in investment_results if r['Gain_Loss'] < 0])
            
            print(f"\nWinning Stocks:        {winning_stocks}/{len(df)}")
            print(f"Losing Stocks:         {losing_stocks}/{len(df)}")
            print(f"Success Rate:          {(winning_stocks/len(df))*100:.1f}%")
            
            # Best and worst performers
            best_stock = max(investment_results, key=lambda x: x['Gain_Loss'])
            worst_stock = min(investment_results, key=lambda x: x['Gain_Loss'])
            
            print(f"\n🏆 Best Performer:     {best_stock['Symbol']} (+${best_stock['Gain_Loss']:.2f})")
            print(f"📉 Worst Performer:    {worst_stock['Symbol']} (${worst_stock['Gain_Loss']:.2f})")
            
            # Market comparison
            print("\n📊 PERFORMANCE BENCHMARKS")
            print("-" * 40)
            
            # Calculate what the same money would earn in different scenarios
            daily_savings_rate = 0.04 / 365  # 4% annual savings account
            savings_account_value = total_initial_value * (1 + daily_savings_rate)
            savings_gain = savings_account_value - total_initial_value
            
            print(f"Savings Account (4% APY): ${savings_account_value:.2f} (+${savings_gain:.2f})")
            print(f"Your Portfolio:           ${total_current_value:.2f} (+${total_gain_loss:.2f})")
            
            outperformance = total_gain_loss - savings_gain
            print(f"Outperformance:           +${outperformance:.2f}")
            
            # Investment insights
            print("\n💡 INVESTMENT INSIGHTS")
            print("-" * 40)
            
            if portfolio_return_percent > 1:
                print("✅ Excellent performance! Your predictions generated strong returns.")
            elif portfolio_return_percent > 0:
                print("✅ Positive returns! Your strategy is working.")
            elif portfolio_return_percent > -2:
                print("⚠️ Small loss, but close to break-even. Consider refining strategy.")
            else:
                print("❌ Significant loss. Strategy needs adjustment.")
            
            if winning_stocks >= 7:
                print("🎯 High accuracy rate suggests good stock selection.")
            elif winning_stocks >= 5:
                print("🎯 Decent accuracy rate with room for improvement.")
            else:
                print("🔄 Low accuracy rate. Consider adjusting prediction criteria.")
            
            # Calculate annualized return (extrapolated)
            days_invested = 1  # Since this is 1-day performance
            annualized_return = ((total_current_value / total_initial_value) ** (365 / days_invested) - 1) * 100
            
            print(f"\n📈 PROJECTED ANNUAL PERFORMANCE")
            print("-" * 40)
            print(f"If this daily performance continued for a year:")
            print(f"Annualized Return:     {annualized_return:+.1f}%")
            print(f"$1000 would become:    ${1000 * (total_current_value / total_initial_value) ** 365:.2f}")
            print("⚠️ Note: This is theoretical - actual results will vary!")
            
            # Save detailed results
            results_df = pd.DataFrame(investment_results)
            output_file = f"data/investment_performance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            results_df.to_csv(output_file, index=False)
            print(f"\n💾 Detailed results saved to: {output_file}")
            
            return {
                'initial_investment': total_initial_value,
                'current_value': total_current_value,
                'total_gain_loss': total_gain_loss,
                'return_percent': portfolio_return_percent,
                'winning_stocks': winning_stocks,
                'total_stocks': len(df),
                'best_performer': best_stock,
                'worst_performer': worst_stock
            }
            
        except Exception as e:
            logger.error(f"Error calculating investment performance: {str(e)}")
            print(f"❌ Error: {str(e)}")
            return None


def main():
    """Main function to calculate investment performance."""
    calculator = InvestmentCalculator()
    
    print("Enter investment amount per stock (default: $100): ", end="")
    try:
        user_input = input().strip()
        investment_amount = float(user_input) if user_input else 100.0
    except:
        investment_amount = 100.0
    
    results = calculator.calculate_portfolio_performance(investment_amount)
    
    if results:
        print("\n🎉 Investment analysis completed!")
        print(f"Your ${results['initial_investment']:.0f} investment is now worth ${results['current_value']:.2f}")
    else:
        print("\n❌ Could not complete investment analysis")


if __name__ == "__main__":
    main()