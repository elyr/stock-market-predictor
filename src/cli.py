"""
Command line interface for Ledger.

Each command parses its options, runs the pipeline and hands the result to
:mod:`src.cli_output`, which prints it.
"""

import logging
import os
import sys
from datetime import datetime
from typing import List, Optional

import click

# Make the project root importable whether run as `python src/cli.py` or `python -m src.cli`
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import cli_output as out  # noqa: E402
from src.backtest import Backtester  # noqa: E402
from src.data.synthetic import SyntheticDataCollector  # noqa: E402
from src.prediction import UNIVERSES, create_pipeline  # noqa: E402
from src.prediction.stock_ranker import StockRanker  # noqa: E402

console = out.console

DEMO_SIZE = 30  # assets used in demo mode, to keep it quick

universe_option = click.option('--universe', '-u', type=click.Choice(UNIVERSES), default='stocks',
                               show_default=True, help='Asset class to analyze')
config_option = click.option('--config', '-c', default='config/config.yaml', help='Path to configuration file')
demo_option = click.option('--demo', is_flag=True, help='Use synthetic data (no network needed)')


def make_ranker(config: str, demo: bool, universe: str = 'stocks') -> StockRanker:
    """Create the stock or crypto pipeline on live data, or on synthetic data in demo mode."""
    if demo:
        console.print("[yellow]Demo mode: using synthetic prices, not real market data.[/yellow]")
        return create_pipeline(universe, config, data_collector=SyntheticDataCollector(reversal=0.2))
    return create_pipeline(universe, config)


def default_symbols(ranker: StockRanker, demo: bool) -> list:
    return ranker.symbols[:DEMO_SIZE] if demo else ranker.symbols


def parse_symbols(symbols: Optional[str]) -> Optional[List[str]]:
    """'aapl, msft' -> ['AAPL', 'MSFT']; None when no list was given."""
    return [s.strip().upper() for s in symbols.split(',') if s.strip()] if symbols else None


def configure_logging(verbose: bool = False) -> None:
    """Log to logs/ledger.log; only warnings reach the terminal unless verbose."""
    os.makedirs('logs', exist_ok=True)
    file_handler = logging.FileHandler('logs/ledger.log')
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

    This tool uses machine learning and technical analysis
    to identify the most promising stocks for next-day trading.
    """
    configure_logging()
    os.makedirs('data', exist_ok=True)


@cli.command()
@click.option('--symbols', '-s', help='Comma-separated list of stock symbols')
@config_option
@click.option('--output', '-o', help='Output CSV filename')
@click.option('--top-n', '-n', default=10, help='Number of top stocks to return')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
@demo_option
@universe_option
@out.reports_errors("Error during analysis")
def analyze(symbols: Optional[str], config: str, output: Optional[str],
            top_n: int, verbose: bool, demo: bool, universe: str):
    """
    Analyze stocks and generate recommendations.

    Examples:
        python src/cli.py analyze
        python src/cli.py analyze --symbols AAPL,MSFT,GOOGL
        python src/cli.py analyze --output my_picks.csv --top-n 5
    """
    if verbose:
        configure_logging(verbose=True)
    out.print_analysis_header()
    symbol_list = parse_symbols(symbols)
    console.print(f"Analyzing {len(symbol_list)} specified symbols..." if symbol_list
                  else "Using default symbol list from configuration...")

    with out.spinner("Initializing system..."):
        ranker = make_ranker(config, demo, universe)
        symbol_list = symbol_list or default_symbols(ranker, demo)
    with out.spinner("Fetching data, training models and scoring..."):
        recommendations = ranker.get_top_10_recommendations(symbol_list, top_n=top_n)

    if recommendations['top_10'].empty:
        console.print("[bold red]No recommendations generated![/bold red]")
        console.print("Check the logs for potential issues.")
        return
    out.print_summary(recommendations['analysis_summary'], universe)
    out.print_picks(recommendations['top_10'], top_n)

    filename = output or f"data/{universe}_recommendations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    saved_file = ranker.save_recommendations(recommendations, filename)
    if saved_file:
        console.print(f"[bold green]Results saved to: {saved_file}[/bold green]")
    out.print_notes()


@cli.command()
@click.option('--symbol', '-s', required=True, help='Stock symbol to analyze')
@config_option
@demo_option
@universe_option
@out.reports_errors("Error analyzing the symbol")
def single(symbol: str, config: str, demo: bool, universe: str):
    """
    Analyze a single stock in detail.

    Example:
        python src/cli.py single --symbol AAPL
    """
    symbol = symbol.upper()
    console.print(f"[bold blue]Detailed Analysis: {symbol}[/bold blue]")
    ranker = make_ranker(config, demo, universe)
    with out.spinner(f"Analyzing {symbol} against its universe..."):
        # Models are trained on the whole universe; the symbol is scored within it
        universe_symbols = list(dict.fromkeys([symbol] + default_symbols(ranker, demo)))
        rankings = ranker.get_top_10_recommendations(universe_symbols, top_n=1)['full_rankings']
        row = rankings[rankings['Symbol'] == symbol]
    if row.empty:
        console.print(f"[bold red]Unable to analyze {symbol}[/bold red]")
        console.print("The symbol may be invalid or data unavailable.")
        return
    out.print_single(symbol, row.iloc[0])


@cli.command()
@config_option
@out.reports_errors("Error fetching market data")
def market(config: str):
    """
    Show overall market analysis and sentiment.
    """
    console.print("[bold blue]Market Overview[/bold blue]")
    ranker = StockRanker(config)
    with out.spinner("Fetching market data..."):
        market_data = ranker.data_collector.fetch_market_data()
    if not market_data:
        console.print("[bold red]Unable to fetch market data[/bold red]")
        return
    out.print_market(market_data)


@cli.command()
@click.option('--symbols', '-s', help='Comma-separated list of stock symbols (default: config list)')
@config_option
@click.option('--top-n', '-n', type=int, help='Picks per day (default: ranking_config.top_picks)')
@click.option('--days', '-d', type=int, help='Trading days to simulate (default: backtest.test_days)')
@click.option('--period', '-p', help='History to fetch, e.g. 2y (default: backtest.period)')
@click.option('--retrain-every', type=int, help='Days between ML retrains (default: backtest.retrain_every)')
@click.option('--cost-bps', type=float, help='One-way transaction cost in basis points')
@click.option('--no-ml', is_flag=True, help='Skip the ML component (much faster)')
@demo_option
@click.option('--output-dir', '-o', default='data', help='Where to write the CSV and HTML results')
@universe_option
@out.reports_errors("Backtest failed")
def backtest(symbols, config, top_n, days, period, retrain_every, cost_bps, no_ml, demo, output_dir, universe):
    """
    Test how the daily top-N picks would have performed historically.

    Each day it scores every stock using only data available at that day's
    close, buys the top N, and measures their next-day return against an
    equal-weight portfolio of the whole universe.

    Examples:
        python src/cli.py backtest --symbols AAPL,MSFT,GOOGL,AMZN,NVDA,META,JPM,V,UNH,XOM,PG,HD --top-n 3
        python src/cli.py backtest --days 250 --no-ml
    """
    ranker = make_ranker(config, demo, universe)
    symbol_list = parse_symbols(symbols) or default_symbols(ranker, demo)
    if not symbol_list:
        console.print("[bold red]No symbols to backtest[/bold red]")
        return

    tester = Backtester.from_config(ranker, top_n=top_n, test_days=days, retrain_every=retrain_every,
                                    cost_bps=cost_bps, use_ml=not no_ml)
    retrain = f" (ML retrained every {tester.retrain_every} days)" if tester.use_ml else ''
    console.print(f"Backtesting top {tester.top_n} {universe} picks, rebalanced every {tester.horizon} days, "
                  f"over the last {tester.test_days} days for {len(symbol_list)} symbols{retrain}...")
    with out.spinner("Fetching data and simulating each day..."):
        result = tester.run_symbols(symbol_list, period=period)
    out.print_backtest(result)

    os.makedirs(output_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    paths = [os.path.join(output_dir, f"{universe}_backtest_{name}_{stamp}.csv") for name in ('periods', 'picks')]
    paths.append(os.path.join(output_dir, f"{universe}_backtest_{stamp}.html"))
    result.daily.to_csv(paths[0])
    result.picks.to_csv(paths[1], index=False)
    out.write_backtest_chart(result, paths[2])
    out.print_backtest_verdict(result, paths)


@cli.command()
@config_option
@out.reports_errors("Error reading configuration")
def config(config: str):
    """Show current configuration settings."""
    from src.data.collector import load_config
    out.print_config(load_config(config))


if __name__ == '__main__':
    cli()
