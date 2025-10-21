"""
Main entry point for the Stock Prediction System.
"""

import sys
import os

# Add src to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.prediction.stock_ranker import StockRanker
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def main():
    """Main function to run stock analysis."""
    print("🚀 Stock Market Prediction System")
    print("=" * 50)
    
    try:
        # Initialize the system
        print("Initializing system...")
        ranker = StockRanker()
        
        # Use a smaller set for demo
        demo_symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'META', 'NVDA', 'JPM', 'V', 'UNH']
        
        print(f"Analyzing {len(demo_symbols)} stocks...")
        print("This may take a few minutes...")
        
        # Get recommendations
        recommendations = ranker.get_top_10_recommendations(demo_symbols)
        
        if recommendations['top_10'].empty:
            print("❌ No recommendations generated. Please check the logs.")
            return
        
        # Display results
        print("\n🏆 TOP 10 STOCK RECOMMENDATIONS")
        print("=" * 80)
        
        top_10 = recommendations['top_10']
        
        print(f"{'Rank':<4} {'Symbol':<8} {'Company':<30} {'Score':<6} {'Price':<8} {'Change%':<8}")
        print("-" * 80)
        
        for idx, (_, row) in enumerate(top_10.iterrows(), 1):
            company_name = row['Company_Name'][:27] + "..." if len(row['Company_Name']) > 30 else row['Company_Name']
            print(f"{idx:<4} {row['Symbol']:<8} {company_name:<30} {row['Composite_Score']:<6.1f} "
                  f"${row['Current_Price']:<7.2f} {row['Daily_Change_Pct']:<7.1f}%")
        
        # Show summary
        summary = recommendations['analysis_summary']
        print(f"\n📊 ANALYSIS SUMMARY")
        print("-" * 30)
        print(f"Total Analyzed: {summary['total_analyzed']} stocks")
        print(f"Average Score: {summary['average_composite_score']:.1f}")
        print(f"Market Sentiment: {summary['market_sentiment']}")
        print(f"Analysis Date: {summary['analysis_date']}")
        
        # Save results
        filename = ranker.save_recommendations(recommendations)
        if filename:
            print(f"\n💾 Results saved to: {filename}")
        
        # Show detailed analysis for top 3
        print(f"\n🔍 TOP 3 DETAILED ANALYSIS")
        print("=" * 50)
        
        for idx, (_, row) in enumerate(top_10.head(3).iterrows(), 1):
            print(f"\n#{idx} - {row['Symbol']}: {row['Company_Name']}")
            print(f"   Score: {row['Composite_Score']:.1f}/100")
            print(f"   Price: ${row['Current_Price']:.2f} ({row['Daily_Change_Pct']:+.1f}%)")
            print(f"   ML Confidence: {row['ML_Confidence']:.2f}")
            print(f"   Sector: {row['Sector']}")
            
            # Recommendation
            score = row['Composite_Score']
            confidence = row['ML_Confidence']
            
            if score >= 75 and confidence >= 0.7:
                recommendation = "🟢 STRONG BUY"
            elif score >= 65 and confidence >= 0.6:
                recommendation = "🟡 BUY"
            elif score >= 55:
                recommendation = "🟠 HOLD/WATCH"
            else:
                recommendation = "🔴 AVOID"
            
            print(f"   Recommendation: {recommendation}")
        
        print(f"\n⚠️  DISCLAIMER: This analysis is for educational purposes only.")
        print("   Always conduct your own research before making investment decisions.")
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        logging.error(f"Main execution error: {str(e)}", exc_info=True)

if __name__ == "__main__":
    main()