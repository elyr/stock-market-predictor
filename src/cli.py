"""
Command Line Interface for Stock Prediction System.
"""

import click
import pandas as pd
import numpy as np
import sys
import os
from typing import Optional, List
from datetime import datetime
import logging
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich import print as rprint

# Add src to Python path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from prediction import StockRanker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/stock_predictor.log'),
        logging.StreamHandler()
    ]
)

console = Console()


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """
    Stock Market Prediction System - Analyze stocks and get top 10 recommendations.
    
    This tool uses machine learning, technical analysis, and sentiment analysis
    to identify the most promising stocks for next-day trading.
    """
    # Ensure logs directory exists
    os.makedirs('logs', exist_ok=True)
    os.makedirs('data', exist_ok=True)


@cli.command()
@click.option('--symbols', '-s', help='Comma-separated list of stock symbols')
@click.option('--config', '-c', default='config/config.yaml', help='Path to configuration file')
@click.option('--output', '-o', help='Output CSV filename')
@click.option('--top-n', '-n', default=10, help='Number of top stocks to return')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def analyze(symbols: Optional[str], config: str, output: Optional[str], 
           top_n: int, verbose: bool):
    """
    Analyze stocks and generate recommendations.
    
    Examples:
        stock-predictor analyze
        stock-predictor analyze --symbols AAPL,MSFT,GOOGL
        stock-predictor analyze --output my_picks.csv --top-n 5
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        console.print(Panel.fit(
            "[bold blue]Stock Market Prediction System[/bold blue]\n"
            "Analyzing market data and generating recommendations...",
            border_style="blue"
        ))
        
        # Parse symbols
        symbol_list = None
        if symbols:
            symbol_list = [s.strip().upper() for s in symbols.split(',')]
            console.print(f"Analyzing {len(symbol_list)} specified symbols...")
        else:
            console.print("Using default symbol list from configuration...")
        
        # Initialize ranker
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            
            task1 = progress.add_task("Initializing system...", total=None)
            ranker = StockRanker(config)
            progress.remove_task(task1)
            
            task2 = progress.add_task("Fetching and analyzing data...", total=None)
            recommendations = ranker.get_top_10_recommendations(symbol_list)
            progress.remove_task(task2)
        
        # Display results
        if recommendations['top_10'].empty:
            console.print("[bold red]No recommendations generated![/bold red]")
            console.print("Check the logs for potential issues.")
            return
        
        # Show summary
        summary = recommendations['analysis_summary']
        console.print(f"\n[bold green]Analysis Complete![/bold green]")
        console.print(f"• Analyzed: {summary['total_analyzed']} stocks")
        console.print(f"• Average Score: {summary['average_composite_score']:.1f}")
        console.print(f"• Market Sentiment: {summary['market_sentiment']}")
        console.print(f"• Analysis Date: {summary['analysis_date']}")
        
        # Create results table
        table = Table(title=f"Top {min(top_n, len(recommendations['top_10']))} Stock Recommendations")
        
        table.add_column("Rank", style="cyan", justify="center")
        table.add_column("Symbol", style="bold magenta")
        table.add_column("Company", style="white")
        table.add_column("Score", style="bold green", justify="right")
        table.add_column("Price", style="yellow", justify="right")
        table.add_column("Change%", style="white", justify="right")
        table.add_column("ML Conf.", style="blue", justify="right")
        table.add_column("Sector", style="dim white")
        
        top_stocks = recommendations['top_10'].head(top_n)
        
        for idx, (_, row) in enumerate(top_stocks.iterrows(), 1):
            # Color code the change
            change_pct = row['Daily_Change_Pct']
            if change_pct > 0:
                change_color = "green"
                change_str = f"+{change_pct:.1f}%"
            elif change_pct < 0:
                change_color = "red"
                change_str = f"{change_pct:.1f}%"
            else:
                change_color = "white"
                change_str = "0.0%"
            
            table.add_row(
                str(idx),
                row['Symbol'],
                row['Company_Name'][:25] + "..." if len(row['Company_Name']) > 25 else row['Company_Name'],
                f"{row['Composite_Score']:.1f}",
                f"${row['Current_Price']:.2f}",
                f"[{change_color}]{change_str}[/{change_color}]",
                f"{row['ML_Confidence']:.2f}",
                row['Sector'][:15] + "..." if len(row['Sector']) > 15 else row['Sector']
            )
        
        console.print(table)
        
        # Show detailed analysis for top 3
        console.print(f"\n[bold]Detailed Analysis - Top 3 Picks:[/bold]")
        
        for idx, (_, row) in enumerate(top_stocks.head(3).iterrows(), 1):
            detail_table = Table(title=f"#{idx} - {row['Symbol']} ({row['Company_Name']})")
            detail_table.add_column("Metric", style="cyan")
            detail_table.add_column("Score", style="white", justify="right")
            detail_table.add_column("Details", style="dim white")
            
            detail_table.add_row("Composite Score", f"{row['Composite_Score']:.1f}/100", "Overall ranking score")
            detail_table.add_row("Technical Score", f"{row['Technical_Score']:.1f}/100", f"RSI: {row.get('RSI', 'N/A'):.1f}")
            detail_table.add_row("ML Prediction", f"{row['ML_Score']:.1f}/100", f"Confidence: {row['ML_Confidence']:.2f}")
            detail_table.add_row("Momentum Score", f"{row['Momentum_Score']:.1f}/100", "Price momentum analysis")
            detail_table.add_row("Volume Score", f"{row['Volume_Score']:.1f}/100", f"Volume: {row['Volume']:,.0f}")
            detail_table.add_row("Sentiment Score", f"{row['Sentiment_Score']:.1f}/100", "Market sentiment")
            
            console.print(detail_table)
            console.print()
        
        # Save to file
        if output:
            filename = output
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"data/recommendations_{timestamp}.csv"
        
        saved_file = ranker.save_recommendations(recommendations, filename)
        if saved_file:
            console.print(f"[bold green]Results saved to: {saved_file}[/bold green]")
        
        # Show trading suggestions
        console.print(Panel(
            "[bold yellow]💡 Trading Suggestions:[/bold yellow]\n\n"
            "• Consider the ML confidence scores when making decisions\n"
            "• Higher composite scores indicate stronger buy signals\n"
            "• Check current market conditions before trading\n"
            "• Use proper risk management and position sizing\n"
            "• These are predictions, not guarantees!",
            title="Important Notes",
            border_style="yellow"
        ))
        
    except Exception as e:
        console.print(f"[bold red]Error during analysis: {str(e)}[/bold red]")
        logging.error(f"CLI analysis error: {str(e)}", exc_info=True)


@cli.command()
@click.option('--symbol', '-s', required=True, help='Stock symbol to analyze')
@click.option('--config', '-c', default='config/config.yaml', help='Path to configuration file')
def single(symbol: str, config: str):
    """
    Analyze a single stock in detail.
    
    Example:
        stock-predictor single --symbol AAPL
    """
    try:
        symbol = symbol.upper()
        console.print(f"[bold blue]Detailed Analysis: {symbol}[/bold blue]")
        
        ranker = StockRanker(config)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task(f"Analyzing {symbol}...", total=None)
            recommendations = ranker.get_top_10_recommendations([symbol])
            progress.remove_task(task)
        
        if recommendations['top_10'].empty:
            console.print(f"[bold red]Unable to analyze {symbol}[/bold red]")
            console.print("The symbol may be invalid or data unavailable.")
            return
        
        stock_data = recommendations['top_10'].iloc[0]
        
        # Company Info Table
        info_table = Table(title=f"{symbol} - Company Information")
        info_table.add_column("Attribute", style="cyan")
        info_table.add_column("Value", style="white")
        
        info_table.add_row("Company Name", stock_data['Company_Name'])
        info_table.add_row("Sector", stock_data['Sector'])
        info_table.add_row("Current Price", f"${stock_data['Current_Price']:.2f}")
        info_table.add_row("Daily Change", f"{stock_data['Daily_Change_Pct']:.2f}%")
        info_table.add_row("Volume", f"{stock_data['Volume']:,.0f}")
        
        console.print(info_table)
        console.print()
        
        # Scores Table
        scores_table = Table(title="Analysis Scores")
        scores_table.add_column("Category", style="cyan")
        scores_table.add_column("Score", style="white", justify="right")
        scores_table.add_column("Rating", style="white")
        
        def get_rating(score):
            if score >= 80: return "[bold green]Excellent[/bold green]"
            elif score >= 70: return "[green]Good[/green]"
            elif score >= 60: return "[yellow]Fair[/yellow]"
            elif score >= 50: return "[orange]Below Average[/orange]"
            else: return "[red]Poor[/red]"
        
        scores_table.add_row("Composite Score", f"{stock_data['Composite_Score']:.1f}/100", get_rating(stock_data['Composite_Score']))
        scores_table.add_row("Technical Analysis", f"{stock_data['Technical_Score']:.1f}/100", get_rating(stock_data['Technical_Score']))
        scores_table.add_row("ML Prediction", f"{stock_data['ML_Score']:.1f}/100", get_rating(stock_data['ML_Score']))
        scores_table.add_row("Momentum", f"{stock_data['Momentum_Score']:.1f}/100", get_rating(stock_data['Momentum_Score']))
        scores_table.add_row("Volume Analysis", f"{stock_data['Volume_Score']:.1f}/100", get_rating(stock_data['Volume_Score']))
        scores_table.add_row("Sentiment", f"{stock_data['Sentiment_Score']:.1f}/100", get_rating(stock_data['Sentiment_Score']))
        
        console.print(scores_table)
        console.print()
        
        # Technical Indicators
        tech_table = Table(title="Technical Indicators")
        tech_table.add_column("Indicator", style="cyan")
        tech_table.add_column("Value", style="white", justify="right")
        tech_table.add_column("Signal", style="white")
        
        rsi = stock_data.get('RSI', None)
        if not pd.isna(rsi):
            if rsi < 30:
                rsi_signal = "[green]Oversold (Buy)[/green]"
            elif rsi > 70:
                rsi_signal = "[red]Overbought (Sell)[/red]"
            else:
                rsi_signal = "[yellow]Neutral[/yellow]"
            tech_table.add_row("RSI", f"{rsi:.1f}", rsi_signal)
        
        macd = stock_data.get('MACD', None)
        if not pd.isna(macd):
            macd_signal = "[green]Positive[/green]" if macd > 0 else "[red]Negative[/red]"
            tech_table.add_row("MACD", f"{macd:.3f}", macd_signal)
        
        console.print(tech_table)
        
        # Investment Recommendation
        score = stock_data['Composite_Score']
        confidence = stock_data['ML_Confidence']
        
        if score >= 75 and confidence >= 0.7:
            recommendation = "[bold green]STRONG BUY[/bold green]"
            reason = "High score with high confidence"
        elif score >= 65 and confidence >= 0.6:
            recommendation = "[green]BUY[/green]"
            reason = "Good score with decent confidence"
        elif score >= 55:
            recommendation = "[yellow]HOLD/WATCH[/yellow]"
            reason = "Average score, monitor for changes"
        else:
            recommendation = "[red]AVOID[/red]"
            reason = "Low score, higher risk"
        
        console.print(Panel(
            f"[bold]Investment Recommendation: {recommendation}[/bold]\n\n"
            f"Reasoning: {reason}\n"
            f"ML Confidence: {confidence:.2f}\n"
            f"Composite Score: {score:.1f}/100",
            title=f"{symbol} Recommendation",
            border_style="blue"
        ))
        
    except Exception as e:
        console.print(f"[bold red]Error analyzing {symbol}: {str(e)}[/bold red]")
        logging.error(f"Single stock analysis error: {str(e)}", exc_info=True)


@cli.command()
@click.option('--config', '-c', default='config/config.yaml', help='Path to configuration file')
def market(config: str):
    """
    Show overall market analysis and sentiment.
    """
    try:
        console.print("[bold blue]Market Overview[/bold blue]")
        
        ranker = StockRanker(config)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Fetching market data...", total=None)
            market_data = ranker.data_collector.fetch_market_data()
            progress.remove_task(task)
        
        if not market_data:
            console.print("[bold red]Unable to fetch market data[/bold red]")
            return
        
        # Market Indices Table
        market_table = Table(title="Major Market Indices")
        market_table.add_column("Index", style="cyan")
        market_table.add_column("Price", style="white", justify="right")
        market_table.add_column("Change %", style="white", justify="right")
        market_table.add_column("Trend", style="white")
        
        for symbol, data in market_data.items():
            change_pct = data['change_pct']
            
            if change_pct > 1:
                trend = "[bold green]Strong Up[/bold green]"
                change_color = "bold green"
            elif change_pct > 0:
                trend = "[green]Up[/green]"
                change_color = "green"
            elif change_pct > -1:
                trend = "[red]Down[/red]"
                change_color = "red"
            else:
                trend = "[bold red]Strong Down[/bold red]"
                change_color = "bold red"
            
            market_table.add_row(
                f"{symbol} ({data['name']})",
                f"${data['price']:.2f}",
                f"[{change_color}]{change_pct:+.2f}%[/{change_color}]",
                trend
            )
        
        console.print(market_table)
        
        # Market Sentiment
        avg_change = np.mean([data['change_pct'] for data in market_data.values()])
        
        if avg_change > 0.5:
            sentiment = "[bold green]Bullish[/bold green]"
            sentiment_desc = "Market is showing strong positive momentum"
        elif avg_change > 0:
            sentiment = "[green]Positive[/green]"
            sentiment_desc = "Market is slightly positive"
        elif avg_change > -0.5:
            sentiment = "[red]Negative[/red]"
            sentiment_desc = "Market is showing weakness"
        else:
            sentiment = "[bold red]Bearish[/bold red]"
            sentiment_desc = "Market is under significant pressure"
        
        console.print(Panel(
            f"[bold]Overall Market Sentiment: {sentiment}[/bold]\n\n"
            f"{sentiment_desc}\n"
            f"Average Index Change: {avg_change:+.2f}%\n"
            f"Analysis Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            title="Market Sentiment",
            border_style="blue"
        ))
        
    except Exception as e:
        console.print(f"[bold red]Error fetching market data: {str(e)}[/bold red]")
        logging.error(f"Market analysis error: {str(e)}", exc_info=True)


@cli.command()
def config():
    """Show current configuration settings."""
    try:
        ranker = StockRanker()
        config_data = ranker.config
        
        console.print("[bold blue]Current Configuration[/bold blue]")
        
        # Stock Configuration
        if 'stock_config' in config_data:
            stock_config = config_data['stock_config']
            console.print(f"\n[bold]Stock Configuration:[/bold]")
            console.print(f"• Symbols: {len(stock_config.get('symbols', []))} configured")
            console.print(f"• Timeframe: {stock_config.get('timeframe', 'N/A')}")
            console.print(f"• Interval: {stock_config.get('interval', 'N/A')}")
        
        # Ranking Configuration
        if 'ranking_config' in config_data:
            ranking_config = config_data['ranking_config']
            console.print(f"\n[bold]Ranking Configuration:[/bold]")
            console.print(f"• Top picks: {ranking_config.get('top_picks', 'N/A')}")
            
            weights = ranking_config.get('weights', {})
            console.print(f"• Technical weight: {weights.get('technical_score', 'N/A')}")
            console.print(f"• ML weight: {weights.get('ml_prediction', 'N/A')}")
            console.print(f"• Momentum weight: {weights.get('momentum_score', 'N/A')}")
            console.print(f"• Volume weight: {weights.get('volume_score', 'N/A')}")
            console.print(f"• Sentiment weight: {weights.get('sentiment_score', 'N/A')}")
        
        # Filters
        if 'ranking_config' in config_data and 'filters' in config_data['ranking_config']:
            filters = config_data['ranking_config']['filters']
            console.print(f"\n[bold]Stock Filters:[/bold]")
            console.print(f"• Min price: ${filters.get('min_price', 'N/A')}")
            console.print(f"• Max price: ${filters.get('max_price', 'N/A')}")
            console.print(f"• Min volume: {filters.get('min_volume', 'N/A'):,}")
            console.print(f"• Exclude penny stocks: {filters.get('exclude_penny_stocks', 'N/A')}")
        
    except Exception as e:
        console.print(f"[bold red]Error reading configuration: {str(e)}[/bold red]")


if __name__ == '__main__':
    cli()