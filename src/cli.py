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

# Make the project root importable whether run as `python src/cli.py` or `python -m src.cli`
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.prediction import UNIVERSES, create_pipeline
from src.prediction.stock_ranker import StockRanker
from src.backtest import Backtester
from src.data.synthetic import SyntheticDataCollector

console = Console()

DEMO_SIZE = 30  # assets used in demo mode, to keep it quick

universe_option = click.option('--universe', '-u', type=click.Choice(UNIVERSES), default='stocks',
                               show_default=True, help='Asset class to analyze')


def make_ranker(config: str, demo: bool, universe: str = 'stocks') -> StockRanker:
    """Create the stock or crypto pipeline on live data, or on synthetic data in demo mode."""
    if demo:
        console.print("[yellow]Demo mode: using synthetic prices, not real market data.[/yellow]")
        ranker = create_pipeline(universe, config, data_collector=SyntheticDataCollector(reversal=0.2))
        ranker.use_sentiment = False
        return ranker
    return create_pipeline(universe, config)


def default_symbols(ranker: StockRanker, demo: bool) -> list:
    return ranker.symbols[:DEMO_SIZE] if demo else ranker.symbols


def configure_logging(verbose: bool = False) -> None:
    """Log to logs/stock_predictor.log; only warnings reach the terminal unless verbose."""
    os.makedirs('logs', exist_ok=True)
    file_handler = logging.FileHandler('logs/stock_predictor.log')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    root = logging.getLogger()
    root.handlers = [file_handler, stream_handler]
    root.setLevel(logging.DEBUG if verbose else logging.INFO)


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """
    Stock Market Prediction System - Analyze stocks and get top 10 recommendations.
    
    This tool uses machine learning, technical analysis, and sentiment analysis
    to identify the most promising stocks for next-day trading.
    """
    configure_logging()
    os.makedirs('data', exist_ok=True)


@cli.command()
@click.option('--symbols', '-s', help='Comma-separated list of stock symbols')
@click.option('--config', '-c', default='config/config.yaml', help='Path to configuration file')
@click.option('--output', '-o', help='Output CSV filename')
@click.option('--top-n', '-n', default=10, help='Number of top stocks to return')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
@click.option('--demo', is_flag=True, help='Use synthetic data (no network needed)')
@universe_option
def analyze(symbols: Optional[str], config: str, output: Optional[str], 
           top_n: int, verbose: bool, demo: bool, universe: str):
    """
    Analyze stocks and generate recommendations.
    
    Examples:
        stock-predictor analyze
        stock-predictor analyze --symbols AAPL,MSFT,GOOGL
        stock-predictor analyze --output my_picks.csv --top-n 5
    """
    if verbose:
        configure_logging(verbose=True)
    
    try:
        console.print(Panel.fit(
            "[bold blue]Stock Market Prediction System[/bold blue]\n"
            "Analyzing market data and generating recommendations...",
            border_style="blue"
        ))
        
        # Parse symbols
        symbol_list = None
        if symbols:
            symbol_list = [s.strip().upper() for s in symbols.split(',') if s.strip()]
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
            ranker = make_ranker(config, demo, universe)
            if symbol_list is None:
                symbol_list = default_symbols(ranker, demo)
            progress.remove_task(task1)
            
            task2 = progress.add_task("Fetching data, training models and scoring...", total=None)
            recommendations = ranker.get_top_10_recommendations(symbol_list, top_n=top_n)
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
        console.print(f"• Universe: {summary.get('label', universe)} · horizon {summary.get('horizon_days')} days · "
                      f"target: {summary.get('target')}")
        quality = summary.get('model_quality') or {}
        if quality.get('ic_mean') is not None:
            console.print(f"• Model quality on hold-out ({quality.get('test_start')} → {quality.get('test_end')}): "
                          f"IC {quality['ic_mean']:+.3f} (t {quality.get('ic_t_stat', float('nan')):+.1f}), "
                          f"AUC {quality.get('test_auc') or float('nan'):.3f}")
        vol = summary.get('volatility_model') or {}
        if vol:
            console.print(f"• Volatility model: {vol['accuracy']:.0%} accuracy (majority class {vol['base_rate']:.0%}), "
                          f"R² {vol['r2_model']:.2f} vs naive {vol['r2_naive']:.2f}")
        
        # Create results table
        table = Table(title=f"Top {min(top_n, len(recommendations['top_10']))} Stock Recommendations")
        
        table.add_column("Rank", style="cyan", justify="center")
        table.add_column("Symbol", style="bold magenta")
        table.add_column("Company", style="white")
        table.add_column("Score", style="bold green", justify="right")
        table.add_column("Price", style="yellow", justify="right")
        table.add_column("Change%", style="white", justify="right")
        table.add_column("ML Prob.", style="blue", justify="right")
        table.add_column("Weight", style="cyan", justify="right")
        table.add_column("Signal", style="white")
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
                f"{row['ML_Probability']:.1%}" if pd.notna(row['ML_Probability']) else "n/a",
                f"{row['Weight']:.0%}",
                row['Recommendation'],
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
            rsi_text = f"RSI: {row['RSI']:.1f}" if pd.notna(row.get('RSI')) else "RSI: N/A"
            detail_table.add_row("Technical Score", f"{row['Technical_Score']:.1f}/100", rsi_text)
            detail_table.add_row("ML Prediction", f"{row['ML_Score']:.1f}/100", f"Confidence: {row['ML_Confidence']:.2f}")
            detail_table.add_row("Momentum Score", f"{row['Momentum_Score']:.1f}/100", "Price momentum analysis")
            detail_table.add_row("Volume Score", f"{row['Volume_Score']:.1f}/100", f"Volume: {row['Volume']:,.0f}")
            if pd.notna(row['Sentiment_Score']):
                detail_table.add_row("Sentiment Score", f"{row['Sentiment_Score']:.1f}/100", "Market sentiment")
            
            console.print(detail_table)
            console.print()
        
        # Save to file
        if output:
            filename = output
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"data/{universe}_recommendations_{timestamp}.csv"
        
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
            "• These are predictions, not guarantees!\n"
            "• Run `backtest` to see how these rules performed historically",
            title="Important Notes",
            border_style="yellow"
        ))
        
    except Exception as e:
        console.print(f"[bold red]Error during analysis: {str(e)}[/bold red]")
        logging.error(f"CLI analysis error: {str(e)}", exc_info=True)


@cli.command()
@click.option('--symbol', '-s', required=True, help='Stock symbol to analyze')
@click.option('--config', '-c', default='config/config.yaml', help='Path to configuration file')
@click.option('--demo', is_flag=True, help='Use synthetic data (no network needed)')
@universe_option
def single(symbol: str, config: str, demo: bool, universe: str):
    """
    Analyze a single stock in detail.
    
    Example:
        stock-predictor single --symbol AAPL
    """
    try:
        symbol = symbol.upper()
        console.print(f"[bold blue]Detailed Analysis: {symbol}[/bold blue]")
        
        ranker = make_ranker(config, demo, universe)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task(f"Analyzing {symbol} against its universe...", total=None)
            # Models are trained on the whole universe; the symbol is scored within it
            universe_symbols = list(dict.fromkeys([symbol] + default_symbols(ranker, demo)))
            all_recs = ranker.get_top_10_recommendations(universe_symbols, top_n=1)
            rankings = all_recs['full_rankings']
            recommendations = {'top_10': rankings[rankings['Symbol'] == symbol]}
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
            elif score >= 50: return "[dark_orange]Below Average[/dark_orange]"
            else: return "[red]Poor[/red]"
        
        scores_table.add_row("Composite Score", f"{stock_data['Composite_Score']:.1f}/100", get_rating(stock_data['Composite_Score']))
        scores_table.add_row("Technical Analysis", f"{stock_data['Technical_Score']:.1f}/100", get_rating(stock_data['Technical_Score']))
        scores_table.add_row("ML Prediction", f"{stock_data['ML_Score']:.1f}/100", get_rating(stock_data['ML_Score']))
        scores_table.add_row("Momentum", f"{stock_data['Momentum_Score']:.1f}/100", get_rating(stock_data['Momentum_Score']))
        scores_table.add_row("Volume Analysis", f"{stock_data['Volume_Score']:.1f}/100", get_rating(stock_data['Volume_Score']))
        if pd.notna(stock_data['Sentiment_Score']):
            scores_table.add_row("Sentiment", f"{stock_data['Sentiment_Score']:.1f}/100", get_rating(stock_data['Sentiment_Score']))
        
        console.print(scores_table)
        console.print()
        
        # Technical Indicators
        tech_table = Table(title="Technical Indicators")
        tech_table.add_column("Indicator", style="cyan")
        tech_table.add_column("Value", style="white", justify="right")
        tech_table.add_column("Signal", style="white")
        
        rsi = stock_data.get('RSI', None)
        if rsi is not None and not pd.isna(rsi):
            if rsi < 30:
                rsi_signal = "[green]Oversold (Buy)[/green]"
            elif rsi > 70:
                rsi_signal = "[red]Overbought (Sell)[/red]"
            else:
                rsi_signal = "[yellow]Neutral[/yellow]"
            tech_table.add_row("RSI", f"{rsi:.1f}", rsi_signal)
        
        macd = stock_data.get('MACD', None)
        if macd is not None and not pd.isna(macd):
            macd_signal = "[green]Positive[/green]" if macd > 0 else "[red]Negative[/red]"
            tech_table.add_row("MACD", f"{macd:.3f}", macd_signal)
        
        console.print(tech_table)
        
        # Investment Recommendation
        score = stock_data['Composite_Score']
        confidence = stock_data['ML_Confidence']
        
        label = stock_data['Recommendation']
        recommendation, reason = {
            'STRONG BUY': ("[bold green]STRONG BUY[/bold green]", "High score with high confidence"),
            'BUY': ("[green]BUY[/green]", "Good score with decent confidence"),
            'HOLD/WATCH': ("[yellow]HOLD/WATCH[/yellow]", "Average score, monitor for changes"),
        }.get(label, ("[red]AVOID[/red]", "Low score, higher risk"))
        
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
@click.option('--symbols', '-s', help='Comma-separated list of stock symbols (default: config list)')
@click.option('--config', '-c', default='config/config.yaml', help='Path to configuration file')
@click.option('--top-n', '-n', type=int, help='Picks per day (default: ranking_config.top_picks)')
@click.option('--days', '-d', type=int, help='Trading days to simulate (default: backtest.test_days)')
@click.option('--period', '-p', help='History to fetch, e.g. 2y (default: backtest.period)')
@click.option('--retrain-every', type=int, help='Days between ML retrains (default: backtest.retrain_every)')
@click.option('--cost-bps', type=float, help='One-way transaction cost in basis points')
@click.option('--no-ml', is_flag=True, help='Skip the ML component (much faster)')
@click.option('--demo', is_flag=True, help='Use synthetic data (no network needed)')
@click.option('--output-dir', '-o', default='data', help='Where to write the CSV and HTML results')
@universe_option
def backtest(symbols, config, top_n, days, period, retrain_every, cost_bps, no_ml, demo, output_dir, universe):
    """
    Test how the daily top-N picks would have performed historically.

    Each day it scores every stock using only data available at that day's
    close, buys the top N, and measures their next-day return against an
    equal-weight portfolio of the whole universe.

    Examples:
        stock-predictor backtest --symbols AAPL,MSFT,GOOGL,AMZN,NVDA,META,JPM,V,UNH,XOM,PG,HD --top-n 3
        stock-predictor backtest --days 250 --no-ml
    """
    try:
        ranker = make_ranker(config, demo, universe)
        symbol_list = ([s.strip().upper() for s in symbols.split(',') if s.strip()] if symbols
                       else default_symbols(ranker, demo))
        if not symbol_list:
            console.print("[bold red]No symbols to backtest[/bold red]")
            return

        tester = Backtester.from_config(ranker, top_n=top_n, test_days=days,
                                        retrain_every=retrain_every, cost_bps=cost_bps,
                                        use_ml=not no_ml)
        console.print(f"Backtesting top {tester.top_n} {universe} picks, rebalanced every {tester.horizon} days, "
                      f"over the last {tester.test_days} days "
                      f"for {len(symbol_list)} symbols{' (ML retrained every ' + str(tester.retrain_every) + ' days)' if tester.use_ml else ''}...")

        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
            task = progress.add_task("Fetching data and simulating each day...", total=None)
            result = tester.run_symbols(symbol_list, period=period)
            progress.remove_task(task)

        settings = result.settings
        table = Table(title=f"Backtest {settings['start']} → {settings['end']} "
                            f"({settings['periods']} periods of {settings['horizon']} days, "
                            f"{settings['universe_size']} assets, top {settings['top_n']})")
        table.add_column("Strategy", style="cyan")
        for header in ["Total", "Annualized", "Sharpe", "Max DD", "Excess/period", "t-stat", "Periods > univ."]:
            table.add_column(header, justify="right")

        for name, m in result.metrics.iterrows():
            def pct(v):
                return "" if pd.isna(v) else f"{v:+.1%}"
            table.add_row(
                name, pct(m['total_return']), pct(m['annualized_return']),
                "" if pd.isna(m['sharpe']) else f"{m['sharpe']:.2f}",
                pct(m['max_drawdown']),
                "" if name.startswith('Equal') else f"{m['avg_excess_bps']:+.1f} bp",
                "" if pd.isna(m['excess_t_stat']) else f"{m['excess_t_stat']:+.2f}",
                "" if pd.isna(m['periods_beating_universe']) else f"{m['periods_beating_universe']:.0%}",
            )
        console.print(table)

        ic_table = Table(title="Ranking quality: information coefficient (score vs. subsequent return)")
        ic_table.add_column("Score", style="cyan")
        for header in ["Mean IC", "t-stat", "Positive periods", "IC IR (annual)"]:
            ic_table.add_column(header, justify="right")
        for name, v in result.ic.items():
            ic_table.add_row(name, f"{v['ic_mean']:+.3f}",
                             "" if pd.isna(v['ic_t_stat']) else f"{v['ic_t_stat']:+.2f}",
                             f"{v['ic_positive_share']:.0%}",
                             "" if pd.isna(v['ic_ir']) else f"{v['ic_ir']:+.2f}")
        console.print(ic_table)

        os.makedirs(output_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        daily_path = os.path.join(output_dir, f"{universe}_backtest_periods_{stamp}.csv")
        picks_path = os.path.join(output_dir, f"{universe}_backtest_picks_{stamp}.csv")
        chart_path = os.path.join(output_dir, f"{universe}_backtest_{stamp}.html")
        result.daily.to_csv(daily_path)
        result.picks.to_csv(picks_path, index=False)
        write_backtest_chart(result, chart_path)

        composite = result.metrics.loc['Composite after costs'] if 'Composite after costs' in result.metrics.index else None
        if composite is not None:
            t = composite['excess_t_stat']
            verdict = ("[green]beat the universe with statistical support (|t| > 2)[/green]" if t > 2
                       else "[red]underperformed the universe (t < -2)[/red]" if t < -2
                       else "[yellow]was not distinguishable from picking at random (|t| < 2)[/yellow]")
            console.print(f"\nAfter costs, the composite strategy {verdict}.")
        console.print(f"[dim]A t-stat between -2 and 2 means the difference could easily be luck. "
                      f"Results saved to {daily_path}, {picks_path} and {chart_path}[/dim]")

    except Exception as e:
        console.print(f"[bold red]Backtest failed: {str(e)}[/bold red]")
        logging.error(f"Backtest error: {str(e)}", exc_info=True)


def write_backtest_chart(result, path: str) -> None:
    """Write an HTML chart of cumulative returns for each strategy."""
    import plotly.graph_objs as go

    from src.backtest.backtester import STRATEGY_LABELS as labels
    fig = go.Figure()
    for col, label in labels.items():
        if col in result.daily.columns and result.daily[col].notna().any():
            equity = (1 + result.daily[col].fillna(0)).cumprod() - 1
            fig.add_trace(go.Scatter(x=equity.index, y=equity, name=label, mode='lines',
                                     line={'width': 3 if col in ('composite_net', 'universe') else 1.5},
                                     visible=True if col in ('composite_net', 'universe', 'ml_prediction') else 'legendonly'))
    fig.update_layout(title=f"Backtest ({result.settings['universe']}): cumulative return of top picks",
                      yaxis_tickformat='.0%',
                      xaxis_title='Date', yaxis_title='Cumulative return', hovermode='x unified')
    fig.write_html(path, include_plotlyjs='cdn')


@cli.command()
@click.option('--config', '-c', default='config/config.yaml', help='Path to configuration file')
def config(config: str):
    """Show current configuration settings."""
    try:
        from src.data.collector import load_config
        config_data = load_config(config)
        for key, universe_cfg in config_data.get('universes', {}).items():
            console.print(f"\n[bold]{universe_cfg.get('label', key)} ({key}):[/bold] "
                          f"{len(universe_cfg.get('symbols', []))} symbols, {universe_cfg.get('timeframe')} history")
        
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
            min_volume = filters.get('min_volume', 'N/A')
            console.print(f"• Min volume: {min_volume:,}" if isinstance(min_volume, (int, float)) else f"• Min volume: {min_volume}")
            console.print(f"• Exclude penny stocks: {filters.get('exclude_penny_stocks', 'N/A')}")
        
    except Exception as e:
        console.print(f"[bold red]Error reading configuration: {str(e)}[/bold red]")


if __name__ == '__main__':
    cli()