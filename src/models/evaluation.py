"""
Model evaluation and validation utilities.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Any
import logging
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    roc_auc_score, confusion_matrix, classification_report
)
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class ModelEvaluator:
    """
    Comprehensive model evaluation and validation system.
    """
    
    def __init__(self):
        self.evaluation_history = []
    
    def evaluate_classification_model(self, y_true: np.ndarray, y_pred: np.ndarray, 
                                    y_pred_proba: np.ndarray = None, 
                                    model_name: str = "Model") -> Dict[str, Any]:
        """
        Comprehensive evaluation of classification model.
        
        Args:
            y_true: True labels
            y_pred: Predicted labels
            y_pred_proba: Predicted probabilities
            model_name: Name of the model
        
        Returns:
            Dictionary with evaluation metrics
        """
        results = {
            'model_name': model_name,
            'accuracy': accuracy_score(y_true, y_pred),
            'precision': precision_score(y_true, y_pred, average='weighted'),
            'recall': recall_score(y_true, y_pred, average='weighted'),
            'f1': f1_score(y_true, y_pred, average='weighted'),
        }
        
        # Add ROC AUC if probabilities are provided
        if y_pred_proba is not None:
            try:
                results['roc_auc'] = roc_auc_score(y_true, y_pred_proba)
            except ValueError:
                results['roc_auc'] = None
        
        # Confusion matrix
        cm = confusion_matrix(y_true, y_pred)
        results['confusion_matrix'] = cm
        
        # Classification report
        results['classification_report'] = classification_report(y_true, y_pred, output_dict=True)
        
        # Calculate additional metrics for binary classification
        if len(np.unique(y_true)) == 2:
            tn, fp, fn, tp = cm.ravel()
            results['true_negatives'] = int(tn)
            results['false_positives'] = int(fp)
            results['false_negatives'] = int(fn)
            results['true_positives'] = int(tp)
            results['specificity'] = tn / (tn + fp) if (tn + fp) > 0 else 0
            results['sensitivity'] = tp / (tp + fn) if (tp + fn) > 0 else 0
        
        return results
    
    def backtest_model(self, data: pd.DataFrame, model, feature_columns: List[str],
                      target_column: str = 'Target_Up', 
                      start_date: str = None, end_date: str = None,
                      rebalance_frequency: str = 'monthly') -> Dict[str, Any]:
        """
        Backtest model performance over time.
        
        Args:
            data: DataFrame with historical data
            model: Trained model object
            feature_columns: List of feature column names
            target_column: Target column name
            start_date: Start date for backtest
            end_date: End date for backtest
            rebalance_frequency: How often to retrain ('monthly', 'quarterly')
        
        Returns:
            Dictionary with backtest results
        """
        # Prepare data
        df = data.copy()
        if start_date:
            df = df[df.index >= start_date]
        if end_date:
            df = df[df.index <= end_date]
        
        # Sort by date
        df = df.sort_index()
        
        # Remove rows with missing targets
        df = df.dropna(subset=[target_column])
        
        if len(df) < 100:
            logger.warning("Insufficient data for backtesting")
            return {}
        
        # Determine rebalancing periods
        if rebalance_frequency == 'monthly':
            periods = pd.date_range(start=df.index[0], end=df.index[-1], freq='MS')
        elif rebalance_frequency == 'quarterly':
            periods = pd.date_range(start=df.index[0], end=df.index[-1], freq='QS')
        else:
            periods = [df.index[0], df.index[-1]]
        
        predictions = []
        actuals = []
        probabilities = []
        dates = []
        
        train_window = 252  # Use 1 year of data for training
        
        for i, period_start in enumerate(periods[:-1]):
            period_end = periods[i + 1] if i + 1 < len(periods) else df.index[-1]
            
            # Get training data (before period_start)
            train_end = period_start
            train_start = train_end - timedelta(days=train_window)
            
            train_data = df[(df.index >= train_start) & (df.index < train_end)]
            test_data = df[(df.index >= period_start) & (df.index < period_end)]
            
            if len(train_data) < 50 or len(test_data) == 0:
                continue
            
            try:
                # Prepare training data
                X_train = train_data[feature_columns].fillna(0)
                y_train = train_data[target_column]
                
                # Prepare test data
                X_test = test_data[feature_columns].fillna(0)
                y_test = test_data[target_column]
                
                # Retrain model for this period
                model.fit(X_train, y_train)
                
                # Make predictions
                y_pred = model.predict(X_test)
                y_pred_proba = model.predict_proba(X_test)[:, 1]
                
                # Store results
                predictions.extend(y_pred)
                actuals.extend(y_test.values)
                probabilities.extend(y_pred_proba)
                dates.extend(test_data.index)
                
            except Exception as e:
                logger.warning(f"Error in backtest period {period_start}: {str(e)}")
                continue
        
        if not predictions:
            return {}
        
        # Calculate overall metrics
        overall_accuracy = accuracy_score(actuals, predictions)
        overall_precision = precision_score(actuals, predictions, average='weighted')
        overall_recall = recall_score(actuals, predictions, average='weighted')
        overall_f1 = f1_score(actuals, predictions, average='weighted')
        
        # Calculate time-series metrics
        results_df = pd.DataFrame({
            'date': dates,
            'actual': actuals,
            'predicted': predictions,
            'probability': probabilities
        })
        
        results_df['correct'] = (results_df['actual'] == results_df['predicted']).astype(int)
        
        # Rolling accuracy
        results_df['rolling_accuracy'] = results_df['correct'].rolling(window=30, min_periods=10).mean()
        
        # Monthly performance
        monthly_performance = results_df.groupby(pd.Grouper(key='date', freq='M')).agg({
            'correct': 'mean',
            'actual': 'sum',
            'predicted': 'sum'
        }).rename(columns={'correct': 'monthly_accuracy'})
        
        return {
            'overall_accuracy': overall_accuracy,
            'overall_precision': overall_precision,
            'overall_recall': overall_recall,
            'overall_f1': overall_f1,
            'predictions_df': results_df,
            'monthly_performance': monthly_performance,
            'total_predictions': len(predictions),
            'backtest_period': f"{df.index[0].date()} to {df.index[-1].date()}"
        }
    
    def calculate_trading_performance(self, data: pd.DataFrame, predictions: np.ndarray,
                                    probabilities: np.ndarray = None,
                                    transaction_cost: float = 0.001) -> Dict[str, Any]:
        """
        Calculate trading performance metrics.
        
        Args:
            data: DataFrame with price data
            predictions: Model predictions (1 for buy, 0 for hold/sell)
            probabilities: Prediction probabilities
            transaction_cost: Transaction cost as percentage of trade value
        
        Returns:
            Dictionary with trading performance metrics
        """
        df = data.copy()
        
        # Ensure we have the required columns
        if 'Close' not in df.columns:
            logger.error("Price data must contain 'Close' column")
            return {}
        
        # Align predictions with data
        min_length = min(len(df), len(predictions))
        df = df.iloc[-min_length:]
        predictions = predictions[-min_length:]
        
        if probabilities is not None:
            probabilities = probabilities[-min_length:]
        
        # Calculate daily returns
        df['daily_return'] = df['Close'].pct_change()
        df['predictions'] = predictions
        
        if probabilities is not None:
            df['probabilities'] = probabilities
        
        # Calculate strategy returns
        df['position'] = df['predictions']  # 1 for long, 0 for cash
        df['position_change'] = df['position'].diff().fillna(0)
        
        # Apply transaction costs
        df['transaction_cost'] = abs(df['position_change']) * transaction_cost
        
        # Calculate strategy returns
        df['strategy_return'] = df['position'].shift(1) * df['daily_return'] - df['transaction_cost']
        df['strategy_return'] = df['strategy_return'].fillna(0)
        
        # Calculate cumulative returns
        df['cumulative_market_return'] = (1 + df['daily_return']).cumprod() - 1
        df['cumulative_strategy_return'] = (1 + df['strategy_return']).cumprod() - 1
        
        # Performance metrics
        total_return = df['cumulative_strategy_return'].iloc[-1]
        market_return = df['cumulative_market_return'].iloc[-1]
        
        # Annualized returns (assuming daily data)
        trading_days = len(df)
        years = trading_days / 252
        
        if years > 0:
            annualized_return = (1 + total_return) ** (1/years) - 1
            annualized_market_return = (1 + market_return) ** (1/years) - 1
        else:
            annualized_return = total_return
            annualized_market_return = market_return
        
        # Risk metrics
        strategy_volatility = df['strategy_return'].std() * np.sqrt(252)
        market_volatility = df['daily_return'].std() * np.sqrt(252)
        
        # Sharpe ratio (assuming 0% risk-free rate)
        sharpe_ratio = annualized_return / strategy_volatility if strategy_volatility > 0 else 0
        market_sharpe = annualized_market_return / market_volatility if market_volatility > 0 else 0
        
        # Maximum drawdown
        running_max = df['cumulative_strategy_return'].expanding().max()
        drawdown = df['cumulative_strategy_return'] - running_max
        max_drawdown = drawdown.min()
        
        # Win rate
        positive_returns = df['strategy_return'] > 0
        win_rate = positive_returns.mean()
        
        # Number of trades
        num_trades = abs(df['position_change']).sum() / 2  # Divide by 2 because each trade has entry and exit
        
        return {
            'total_return': total_return,
            'annualized_return': annualized_return,
            'market_return': market_return,
            'annualized_market_return': annualized_market_return,
            'excess_return': annualized_return - annualized_market_return,
            'volatility': strategy_volatility,
            'market_volatility': market_volatility,
            'sharpe_ratio': sharpe_ratio,
            'market_sharpe': market_sharpe,
            'max_drawdown': max_drawdown,
            'win_rate': win_rate,
            'num_trades': num_trades,
            'trading_days': trading_days,
            'performance_df': df
        }
    
    def compare_models(self, model_results: Dict[str, Dict[str, Any]]) -> pd.DataFrame:
        """
        Compare multiple model results.
        
        Args:
            model_results: Dictionary of model evaluation results
        
        Returns:
            DataFrame comparing all models
        """
        comparison_data = []
        
        for model_name, results in model_results.items():
            model_data = {'Model': model_name}
            
            # Add classification metrics
            for metric in ['accuracy', 'precision', 'recall', 'f1', 'roc_auc']:
                if metric in results:
                    model_data[metric.capitalize()] = results[metric]
            
            # Add trading metrics if available
            if 'trading_performance' in results:
                trading = results['trading_performance']
                model_data['Total_Return'] = trading.get('total_return', 0)
                model_data['Sharpe_Ratio'] = trading.get('sharpe_ratio', 0)
                model_data['Max_Drawdown'] = trading.get('max_drawdown', 0)
                model_data['Win_Rate'] = trading.get('win_rate', 0)
            
            comparison_data.append(model_data)
        
        return pd.DataFrame(comparison_data)
    
    def plot_model_performance(self, results: Dict[str, Any], save_path: str = None):
        """
        Create visualization of model performance.
        
        Args:
            results: Model evaluation results
            save_path: Path to save the plot
        """
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        
        # Confusion Matrix
        if 'confusion_matrix' in results:
            sns.heatmap(results['confusion_matrix'], annot=True, fmt='d', 
                       cmap='Blues', ax=axes[0, 0])
            axes[0, 0].set_title('Confusion Matrix')
            axes[0, 0].set_ylabel('True Label')
            axes[0, 0].set_xlabel('Predicted Label')
        
        # Performance Metrics Bar Chart
        metrics = ['accuracy', 'precision', 'recall', 'f1']
        metric_values = [results.get(metric, 0) for metric in metrics]
        
        axes[0, 1].bar(metrics, metric_values)
        axes[0, 1].set_title('Classification Metrics')
        axes[0, 1].set_ylabel('Score')
        axes[0, 1].set_ylim(0, 1)
        
        # Trading Performance (if available)
        if 'trading_performance' in results:
            perf_df = results['trading_performance']['performance_df']
            
            axes[1, 0].plot(perf_df.index, perf_df['cumulative_strategy_return'], 
                           label='Strategy', linewidth=2)
            axes[1, 0].plot(perf_df.index, perf_df['cumulative_market_return'], 
                           label='Market', linewidth=2)
            axes[1, 0].set_title('Cumulative Returns')
            axes[1, 0].set_ylabel('Return')
            axes[1, 0].legend()
            
            # Rolling accuracy (if available)
            if 'rolling_accuracy' in perf_df.columns:
                axes[1, 1].plot(perf_df.index, perf_df['rolling_accuracy'])
                axes[1, 1].set_title('Rolling Accuracy (30-day)')
                axes[1, 1].set_ylabel('Accuracy')
                axes[1, 1].set_ylim(0, 1)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            logger.info(f"Performance plot saved to {save_path}")
        
        plt.show()
    
    def generate_evaluation_report(self, model_results: Dict[str, Dict[str, Any]]) -> str:
        """
        Generate a comprehensive text report of model evaluation.
        
        Args:
            model_results: Dictionary of model evaluation results
        
        Returns:
            Formatted text report
        """
        report = []
        report.append("=" * 60)
        report.append("MODEL EVALUATION REPORT")
        report.append("=" * 60)
        report.append(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")
        
        # Model comparison table
        comparison_df = self.compare_models(model_results)
        report.append("MODEL COMPARISON SUMMARY:")
        report.append("-" * 30)
        report.append(comparison_df.to_string(index=False))
        report.append("")
        
        # Detailed results for each model
        for model_name, results in model_results.items():
            report.append(f"DETAILED RESULTS - {model_name.upper()}")
            report.append("-" * 40)
            
            # Classification metrics
            report.append(f"Accuracy: {results.get('accuracy', 'N/A'):.4f}")
            report.append(f"Precision: {results.get('precision', 'N/A'):.4f}")
            report.append(f"Recall: {results.get('recall', 'N/A'):.4f}")
            report.append(f"F1-Score: {results.get('f1', 'N/A'):.4f}")
            
            if 'roc_auc' in results and results['roc_auc'] is not None:
                report.append(f"ROC AUC: {results['roc_auc']:.4f}")
            
            # Trading performance
            if 'trading_performance' in results:
                trading = results['trading_performance']
                report.append("")
                report.append("Trading Performance:")
                report.append(f"  Total Return: {trading.get('total_return', 0):.2%}")
                report.append(f"  Annualized Return: {trading.get('annualized_return', 0):.2%}")
                report.append(f"  Sharpe Ratio: {trading.get('sharpe_ratio', 0):.3f}")
                report.append(f"  Max Drawdown: {trading.get('max_drawdown', 0):.2%}")
                report.append(f"  Win Rate: {trading.get('win_rate', 0):.2%}")
                report.append(f"  Number of Trades: {trading.get('num_trades', 0):.0f}")
            
            report.append("")
        
        # Recommendations
        report.append("RECOMMENDATIONS:")
        report.append("-" * 15)
        
        # Find best performing model
        best_accuracy = 0
        best_model = None
        
        for model_name, results in model_results.items():
            if results.get('accuracy', 0) > best_accuracy:
                best_accuracy = results['accuracy']
                best_model = model_name
        
        if best_model:
            report.append(f"• Best performing model by accuracy: {best_model} ({best_accuracy:.4f})")
        
        # Trading performance recommendations
        best_sharpe = -999
        best_trading_model = None
        
        for model_name, results in model_results.items():
            if 'trading_performance' in results:
                sharpe = results['trading_performance'].get('sharpe_ratio', -999)
                if sharpe > best_sharpe:
                    best_sharpe = sharpe
                    best_trading_model = model_name
        
        if best_trading_model:
            report.append(f"• Best trading performance: {best_trading_model} (Sharpe: {best_sharpe:.3f})")
        
        report.append("")
        report.append("=" * 60)
        
        return "\n".join(report)


if __name__ == "__main__":
    # Example usage
    evaluator = ModelEvaluator()
    
    # Create some sample data for demonstration
    np.random.seed(42)
    y_true = np.random.randint(0, 2, 100)
    y_pred = np.random.randint(0, 2, 100)
    y_pred_proba = np.random.random(100)
    
    # Evaluate a sample model
    results = evaluator.evaluate_classification_model(y_true, y_pred, y_pred_proba, "Sample Model")
    
    print("Sample Evaluation Results:")
    print(f"Accuracy: {results['accuracy']:.4f}")
    print(f"Precision: {results['precision']:.4f}")
    print(f"Recall: {results['recall']:.4f}")
    print(f"F1-Score: {results['f1']:.4f}")
    if results['roc_auc'] is not None:
        print(f"ROC AUC: {results['roc_auc']:.4f}")
    
    # Generate comparison report
    sample_results = {
        'Model_A': results,
        'Model_B': {
            'accuracy': 0.65,
            'precision': 0.68,
            'recall': 0.62,
            'f1': 0.65,
            'roc_auc': 0.70
        }
    }
    
    comparison = evaluator.compare_models(sample_results)
    print("\nModel Comparison:")
    print(comparison)