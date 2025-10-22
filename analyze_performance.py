"""
Performance Analysis: Compare Yesterday's Predictions with Actual Results
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os
import logging

# Add src to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from src.data.collector import DataCollector
from src.prediction.stock_ranker import StockRanker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PredictionAnalyzer:
    """Analyze prediction accuracy against actual market performance."""
    
    def __init__(self):
        self.data_collector = DataCollector()
        self.ranker = StockRanker()
    
    def load_yesterday_predictions(self):
        """Load the most recent prediction file."""
        try:
            # Look for the most recent CSV file in data directory
            data_dir = 'data'
            if not os.path.exists(data_dir):
                print("❌ No data directory found. Run predictions first.")
                return None
            
            # Find CSV files with stock recommendations
            csv_files = [f for f in os.listdir(data_dir) if f.startswith('stock_recommendations_') and f.endswith('.csv')]
            
            if not csv_files:
                print("❌ No prediction files found. Run predictions first.")
                return None
            
            # Get the most recent file
            latest_file = max(csv_files, key=lambda x: os.path.getctime(os.path.join(data_dir, x)))
            file_path = os.path.join(data_dir, latest_file)
            
            print(f"📊 Loading predictions from: {latest_file}")
            predictions_df = pd.read_csv(file_path)
            
            return predictions_df, latest_file
            
        except Exception as e:
            logger.error(f"Error loading predictions: {str(e)}")
            return None
    
    def get_actual_performance(self, symbols, prediction_date):
        """Get actual stock performance since prediction date."""
        try:
            # Calculate date range (from prediction to today)
            pred_date = datetime.strptime(prediction_date.split('_')[1], '%Y%m%d')
            today = datetime.now()
            
            print(f"📈 Fetching actual performance from {pred_date.strftime('%Y-%m-%d')} to {today.strftime('%Y-%m-%d')}")
            
            performance_data = []
            
            for symbol in symbols:
                try:
                    # Get stock data for the period
                    stock_data = self.data_collector.fetch_stock_data(symbol, period='5d')
                    
                    if stock_data is None or stock_data.empty:
                        print(f"⚠️ No data available for {symbol}")
                        continue
                    
                    # Get price at prediction time and current price
                    start_price = stock_data['Close'].iloc[0]  # First available price after prediction
                    end_price = stock_data['Close'].iloc[-1]   # Most recent price
                    
                    # Calculate performance
                    price_change = end_price - start_price
                    percent_change = (price_change / start_price) * 100
                    
                    performance_data.append({
                        'Symbol': symbol,
                        'Start_Price': start_price,
                        'End_Price': end_price,
                        'Price_Change': price_change,
                        'Percent_Change': percent_change,
                        'Direction': 'UP' if percent_change > 0 else 'DOWN' if percent_change < 0 else 'FLAT'
                    })
                    
                    print(f"  {symbol}: {start_price:.2f} → {end_price:.2f} ({percent_change:+.2f}%)")
                    
                except Exception as e:
                    logger.warning(f"Error fetching data for {symbol}: {str(e)}")
                    continue
            
            return pd.DataFrame(performance_data)
            
        except Exception as e:
            logger.error(f"Error getting actual performance: {str(e)}")
            return pd.DataFrame()
    
    def analyze_prediction_accuracy(self, predictions_df, performance_df):
        """Analyze how accurate the predictions were."""
        try:
            # Merge predictions with actual performance
            analysis_df = predictions_df.merge(performance_df, on='Symbol', how='inner')
            
            if analysis_df.empty:
                print("❌ No matching data for analysis")
                return None
            
            # Calculate metrics
            total_stocks = len(analysis_df)
            correct_predictions = len(analysis_df[analysis_df['Percent_Change'] > 0])
            accuracy = (correct_predictions / total_stocks) * 100
            
            avg_predicted_score = analysis_df['Composite_Score'].mean()
            avg_actual_return = analysis_df['Percent_Change'].mean()
            
            # Top 3 predictions performance
            top_3 = analysis_df.head(3)
            top_3_positive = len(top_3[top_3['Percent_Change'] > 0])
            top_3_accuracy = (top_3_positive / 3) * 100
            
            # Best and worst performers
            best_performer = analysis_df.loc[analysis_df['Percent_Change'].idxmax()]
            worst_performer = analysis_df.loc[analysis_df['Percent_Change'].idxmin()]
            
            return {
                'analysis_df': analysis_df,
                'total_stocks': total_stocks,
                'correct_predictions': correct_predictions,
                'overall_accuracy': accuracy,
                'avg_predicted_score': avg_predicted_score,
                'avg_actual_return': avg_actual_return,
                'top_3_accuracy': top_3_accuracy,
                'best_performer': best_performer,
                'worst_performer': worst_performer
            }
            
        except Exception as e:
            logger.error(f"Error analyzing accuracy: {str(e)}")
            return None
    
    def generate_performance_report(self):
        """Generate a comprehensive performance analysis report."""
        print("🔍 PREDICTION PERFORMANCE ANALYSIS")
        print("=" * 60)
        
        # Load yesterday's predictions
        prediction_data = self.load_yesterday_predictions()
        if prediction_data is None:
            return
        
        predictions_df, filename = prediction_data
        
        # Extract prediction date from filename
        prediction_date = filename.replace('stock_recommendations_', '').replace('.csv', '')
        
        # Get symbols from predictions
        symbols = predictions_df['Symbol'].tolist()
        print(f"📋 Analyzing {len(symbols)} predicted stocks...")
        
        # Get actual performance
        performance_df = self.get_actual_performance(symbols, prediction_date)
        
        if performance_df.empty:
            print("❌ Could not fetch actual performance data")
            return
        
        # Analyze accuracy
        analysis = self.analyze_prediction_accuracy(predictions_df, performance_df)
        
        if analysis is None:
            print("❌ Could not complete analysis")
            return
        
        # Display results
        print("\n📊 PERFORMANCE SUMMARY")
        print("-" * 40)
        print(f"Total Stocks Analyzed: {analysis['total_stocks']}")
        print(f"Stocks That Went UP: {analysis['correct_predictions']}")
        print(f"Overall Accuracy: {analysis['overall_accuracy']:.1f}%")
        print(f"Average Predicted Score: {analysis['avg_predicted_score']:.1f}/100")
        print(f"Average Actual Return: {analysis['avg_actual_return']:+.2f}%")
        print(f"Top 3 Predictions Accuracy: {analysis['top_3_accuracy']:.1f}%")
        
        print("\n🏆 DETAILED RESULTS")
        print("-" * 60)
        
        # Display all results
        analysis_df = analysis['analysis_df']
        
        for idx, row in analysis_df.iterrows():
            direction_emoji = "🟢" if row['Percent_Change'] > 0 else "🔴" if row['Percent_Change'] < 0 else "⚪"
            print(f"{direction_emoji} {row['Symbol']:<6} | Score: {row['Composite_Score']:<5.1f} | "
                  f"Actual: {row['Percent_Change']:+6.2f}% | "
                  f"Price: ${row['Start_Price']:.2f} → ${row['End_Price']:.2f}")
        
        print(f"\n🎯 BEST PERFORMER")
        best = analysis['best_performer']
        print(f"   {best['Symbol']}: {best['Percent_Change']:+.2f}% (Predicted Score: {best['Composite_Score']:.1f})")
        
        print(f"\n📉 WORST PERFORMER")
        worst = analysis['worst_performer']
        print(f"   {worst['Symbol']}: {worst['Percent_Change']:+.2f}% (Predicted Score: {worst['Composite_Score']:.1f})")
        
        # Save analysis results
        output_file = f"data/performance_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        analysis_df.to_csv(output_file, index=False)
        print(f"\n💾 Analysis saved to: {output_file}")
        
        print("\n" + "=" * 60)
        print("📝 INSIGHTS & RECOMMENDATIONS")
        print("-" * 40)
        
        if analysis['overall_accuracy'] > 60:
            print("✅ Good prediction accuracy! The model is performing well.")
        elif analysis['overall_accuracy'] > 40:
            print("⚠️ Moderate accuracy. Consider refining the model parameters.")
        else:
            print("❌ Low accuracy. Model needs significant improvements.")
        
        if analysis['top_3_accuracy'] > analysis['overall_accuracy']:
            print("🎯 Top predictions are more accurate - ranking system is working well.")
        else:
            print("🔄 Consider adjusting the ranking algorithm weights.")
        
        return analysis


def main():
    """Main function to run performance analysis."""
    analyzer = PredictionAnalyzer()
    
    try:
        analysis = analyzer.generate_performance_report()
        
        if analysis:
            print("\n🚀 Analysis completed successfully!")
        else:
            print("\n❌ Analysis failed. Please check the logs.")
            
    except Exception as e:
        logger.error(f"Error in main analysis: {str(e)}")
        print(f"\n❌ Error: {str(e)}")


if __name__ == "__main__":
    main()