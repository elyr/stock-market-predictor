"""
Terminal output for the command line (``src/cli.py``): tables, panels and the
backtest chart. The commands parse options and run the pipeline; everything
they print is built here.
"""

import functools
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Dict, Iterator

import numpy as np
import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

console = Console()


@contextmanager
def spinner(description: str) -> Iterator[None]:
    """Show a spinner with a description while the block runs."""
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console) as progress:
        task = progress.add_task(description, total=None)
        yield
        progress.remove_task(task)


def reports_errors(message: str) -> Callable:
    """Print ``message: error`` and log the traceback instead of crashing the command."""
    def decorate(command: Callable) -> Callable:
        @functools.wraps(command)
        def wrapper(*args, **kwargs):
            try:
                return command(*args, **kwargs)
            except Exception as e:
                console.print(f"[bold red]{message}: {str(e)}[/bold red]")
                logging.error(f"{message}: {str(e)}", exc_info=True)
        return wrapper
    return decorate


# ----------------------------------------------------------------- analyze

def print_analysis_header() -> None:
    console.print(Panel.fit(
        "[bold blue]Stock Market Prediction System[/bold blue]\n"
        "Analyzing market data and generating recommendations...",
        border_style="blue"
    ))


def print_summary(summary: Dict[str, Any], universe: str) -> None:
    console.print("\n[bold green]Analysis Complete![/bold green]")
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


def _shorten(text: str, length: int) -> str:
    return text[:length] + "..." if len(text) > length else text


def _change(change_pct: float) -> str:
    if change_pct > 0:
        return f"[green]+{change_pct:.1f}%[/green]"
    if change_pct < 0:
        return f"[red]{change_pct:.1f}%[/red]"
    return "[white]0.0%[/white]"


def print_picks(top: pd.DataFrame, top_n: int) -> None:
    """The picks table, then a detail table for the first three."""
    table = Table(title=f"Top {min(top_n, len(top))} Stock Recommendations")
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

    top = top.head(top_n)
    for idx, (_, row) in enumerate(top.iterrows(), 1):
        table.add_row(
            str(idx), row['Symbol'], _shorten(row['Company_Name'], 25),
            f"{row['Composite_Score']:.1f}", f"${row['Current_Price']:.2f}", _change(row['Daily_Change_Pct']),
            f"{row['ML_Probability']:.1%}" if pd.notna(row['ML_Probability']) else "n/a",
            f"{row['Weight']:.0%}", row['Recommendation'], _shorten(row['Sector'], 15),
        )
    console.print(table)

    console.print("\n[bold]Detailed Analysis - Top 3 Picks:[/bold]")
    for idx, (_, row) in enumerate(top.head(3).iterrows(), 1):
        detail = Table(title=f"#{idx} - {row['Symbol']} ({row['Company_Name']})")
        detail.add_column("Metric", style="cyan")
        detail.add_column("Score", style="white", justify="right")
        detail.add_column("Details", style="dim white")
        detail.add_row("Composite Score", f"{row['Composite_Score']:.1f}/100", "Overall ranking score")
        rsi_text = f"RSI: {row['RSI']:.1f}" if pd.notna(row.get('RSI')) else "RSI: N/A"
        detail.add_row("Technical Score", f"{row['Technical_Score']:.1f}/100", rsi_text)
        detail.add_row("ML Prediction", f"{row['ML_Score']:.1f}/100", f"Confidence: {row['ML_Confidence']:.2f}")
        detail.add_row("Momentum Score", f"{row['Momentum_Score']:.1f}/100", "Price momentum analysis")
        detail.add_row("Volume Score", f"{row['Volume_Score']:.1f}/100", f"Volume: {row['Volume']:,.0f}")
        console.print(detail)
        console.print()


def print_notes() -> None:
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


# ------------------------------------------------------------------ single

def _rating(score: float) -> str:
    if score >= 80:
        return "[bold green]Excellent[/bold green]"
    if score >= 70:
        return "[green]Good[/green]"
    if score >= 60:
        return "[yellow]Fair[/yellow]"
    if score >= 50:
        return "[dark_orange]Below Average[/dark_orange]"
    return "[red]Poor[/red]"


def print_single(symbol: str, row: pd.Series) -> None:
    """Company facts, the score parts, indicators and the label for one asset."""
    info = Table(title=f"{symbol} - Company Information")
    info.add_column("Attribute", style="cyan")
    info.add_column("Value", style="white")
    info.add_row("Company Name", row['Company_Name'])
    info.add_row("Sector", row['Sector'])
    info.add_row("Current Price", f"${row['Current_Price']:.2f}")
    info.add_row("Daily Change", f"{row['Daily_Change_Pct']:.2f}%")
    info.add_row("Volume", f"{row['Volume']:,.0f}")
    console.print(info)
    console.print()

    scores = Table(title="Analysis Scores")
    scores.add_column("Category", style="cyan")
    scores.add_column("Score", style="white", justify="right")
    scores.add_column("Rating", style="white")
    for label, column in [("Composite Score", 'Composite_Score'), ("Technical Analysis", 'Technical_Score'),
                          ("ML Prediction", 'ML_Score'), ("Momentum", 'Momentum_Score'),
                          ("Volume Analysis", 'Volume_Score')]:
        scores.add_row(label, f"{row[column]:.1f}/100", _rating(row[column]))
    console.print(scores)
    console.print()

    tech = Table(title="Technical Indicators")
    tech.add_column("Indicator", style="cyan")
    tech.add_column("Value", style="white", justify="right")
    tech.add_column("Signal", style="white")
    rsi = row.get('RSI', None)
    if rsi is not None and not pd.isna(rsi):
        signal = ("[green]Oversold (Buy)[/green]" if rsi < 30 else "[red]Overbought (Sell)[/red]" if rsi > 70
                  else "[yellow]Neutral[/yellow]")
        tech.add_row("RSI", f"{rsi:.1f}", signal)
    macd = row.get('MACD', None)
    if macd is not None and not pd.isna(macd):
        tech.add_row("MACD", f"{macd:.3f}", "[green]Positive[/green]" if macd > 0 else "[red]Negative[/red]")
    console.print(tech)

    recommendation, reason = {
        'STRONG BUY': ("[bold green]STRONG BUY[/bold green]", "High score with high confidence"),
        'BUY': ("[green]BUY[/green]", "Good score with decent confidence"),
        'HOLD/WATCH': ("[yellow]HOLD/WATCH[/yellow]", "Average score, monitor for changes"),
    }.get(row['Recommendation'], ("[red]AVOID[/red]", "Low score, higher risk"))
    console.print(Panel(
        f"[bold]Investment Recommendation: {recommendation}[/bold]\n\n"
        f"Reasoning: {reason}\n"
        f"ML Confidence: {row['ML_Confidence']:.2f}\n"
        f"Composite Score: {row['Composite_Score']:.1f}/100",
        title=f"{symbol} Recommendation",
        border_style="blue"
    ))


# ------------------------------------------------------------------ market

def print_market(market_data: Dict[str, Dict[str, Any]]) -> None:
    """Index table and the overall mood from the average move."""
    table = Table(title="Major Market Indices")
    table.add_column("Index", style="cyan")
    table.add_column("Price", style="white", justify="right")
    table.add_column("Change %", style="white", justify="right")
    table.add_column("Trend", style="white")
    for symbol, data in market_data.items():
        change = data['change_pct']
        trend, color = (("[bold green]Strong Up[/bold green]", "bold green") if change > 1
                        else ("[green]Up[/green]", "green") if change > 0
                        else ("[red]Down[/red]", "red") if change > -1
                        else ("[bold red]Strong Down[/bold red]", "bold red"))
        table.add_row(f"{symbol} ({data['name']})", f"${data['price']:.2f}",
                      f"[{color}]{change:+.2f}%[/{color}]", trend)
    console.print(table)

    avg_change = np.mean([data['change_pct'] for data in market_data.values()])
    sentiment, description = (
        ("[bold green]Bullish[/bold green]", "Market is showing strong positive momentum") if avg_change > 0.5
        else ("[green]Positive[/green]", "Market is slightly positive") if avg_change > 0
        else ("[red]Negative[/red]", "Market is showing weakness") if avg_change > -0.5
        else ("[bold red]Bearish[/bold red]", "Market is under significant pressure"))
    console.print(Panel(
        f"[bold]Overall Market Sentiment: {sentiment}[/bold]\n\n"
        f"{description}\n"
        f"Average Index Change: {avg_change:+.2f}%\n"
        f"Analysis Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        title="Market Sentiment",
        border_style="blue"
    ))


# ---------------------------------------------------------------- backtest

def _pct(value: float) -> str:
    return "" if pd.isna(value) else f"{value:+.1%}"


def print_backtest(result) -> None:
    """Strategy metrics and the ranking-quality table."""
    settings = result.settings
    table = Table(title=f"Backtest {settings['start']} → {settings['end']} "
                        f"({settings['periods']} periods of {settings['horizon']} days, "
                        f"{settings['universe_size']} assets, top {settings['top_n']})")
    table.add_column("Strategy", style="cyan")
    for header in ["Total", "Annualized", "Sharpe", "Max DD", "Excess/period", "t-stat", "Periods > univ."]:
        table.add_column(header, justify="right")
    for name, m in result.metrics.iterrows():
        table.add_row(
            name, _pct(m['total_return']), _pct(m['annualized_return']),
            "" if pd.isna(m['sharpe']) else f"{m['sharpe']:.2f}",
            _pct(m['max_drawdown']),
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


def print_backtest_verdict(result, paths) -> None:
    composite = result.metrics.loc['Composite after costs'] if 'Composite after costs' in result.metrics.index else None
    if composite is not None:
        t = composite['excess_t_stat']
        verdict = ("[green]beat the universe with statistical support (|t| > 2)[/green]" if t > 2
                   else "[red]underperformed the universe (t < -2)[/red]" if t < -2
                   else "[yellow]was not distinguishable from picking at random (|t| < 2)[/yellow]")
        console.print(f"\nAfter costs, the composite strategy {verdict}.")
    console.print(f"[dim]A t-stat between -2 and 2 means the difference could easily be luck. "
                  f"Results saved to {', '.join(paths[:-1])} and {paths[-1]}[/dim]")


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


# ------------------------------------------------------------------ config

def print_config(config_data: Dict[str, Any]) -> None:
    for key, universe_cfg in config_data.get('universes', {}).items():
        console.print(f"\n[bold]{universe_cfg.get('label', key)} ({key}):[/bold] "
                      f"{len(universe_cfg.get('symbols', []))} symbols, {universe_cfg.get('timeframe')} history")
    console.print("[bold blue]Current Configuration[/bold blue]")

    if 'stock_config' in config_data:
        stock_config = config_data['stock_config']
        console.print("\n[bold]Stock Configuration:[/bold]")
        console.print(f"• Symbols: {len(stock_config.get('symbols', []))} configured")
        console.print(f"• Timeframe: {stock_config.get('timeframe', 'N/A')}")
        console.print(f"• Interval: {stock_config.get('interval', 'N/A')}")

    ranking_config = config_data.get('ranking_config')
    if ranking_config is not None:
        console.print("\n[bold]Ranking Configuration:[/bold]")
        console.print(f"• Top picks: {ranking_config.get('top_picks', 'N/A')}")
        weights = ranking_config.get('weights', {})
        console.print(f"• Technical weight: {weights.get('technical_score', 'N/A')}")
        console.print(f"• ML weight: {weights.get('ml_prediction', 'N/A')}")
        console.print(f"• Momentum weight: {weights.get('momentum_score', 'N/A')}")
        console.print(f"• Volume weight: {weights.get('volume_score', 'N/A')}")

        if 'filters' in ranking_config:
            filters = ranking_config['filters']
            console.print("\n[bold]Stock Filters:[/bold]")
            console.print(f"• Min price: ${filters.get('min_price', 'N/A')}")
            console.print(f"• Max price: ${filters.get('max_price', 'N/A')}")
            min_volume = filters.get('min_volume', 'N/A')
            console.print(f"• Min volume: {min_volume:,}" if isinstance(min_volume, (int, float))
                          else f"• Min volume: {min_volume}")
            console.print(f"• Exclude penny stocks: {filters.get('exclude_penny_stocks', 'N/A')}")
