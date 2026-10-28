"""
Web-based dashboard for Stock Prediction System using Dash.
"""

import dash
from dash import dcc, html, Input, Output, State, dash_table
import plotly.graph_objs as go
import plotly.express as px
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os
import logging

# Make the project root importable when run as `python web/dashboard.py`
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.backtest import Backtester
from src.data.synthetic import SyntheticDataCollector
from src.prediction.stock_ranker import StockRanker

DEMO_SYMBOLS = ','.join(f"DEMO{chr(65 + i)}" for i in range(20))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Dash app
app = dash.Dash(__name__)
app.title = "Stock Prediction Dashboard"

# Global variables for caching (one live ranker and one demo ranker)
rankers = {}
last_analysis = None
last_analysis_time = None

def get_ranker(demo: bool = False):
    """Get or initialize the stock ranker (synthetic data in demo mode)."""
    key = 'demo' if demo else 'live'
    if key not in rankers:
        if demo:
            ranker = StockRanker(data_collector=SyntheticDataCollector(reversal=0.2))
            ranker.use_sentiment = False
        else:
            ranker = StockRanker()
        rankers[key] = ranker
    return rankers[key]


def parse_symbols(symbols_input, demo):
    """Split the comma-separated input; default to the demo list in demo mode."""
    if symbols_input:
        symbols = [s.strip().upper() for s in symbols_input.split(',') if s.strip()]
        if symbols:
            return symbols
    return DEMO_SYMBOLS.split(',') if demo else None

# Define the layout
app.layout = html.Div([
    # Header
    html.Div([
        html.H1("🚀 Stock Market Prediction Dashboard", 
                style={'textAlign': 'center', 'color': '#2E86AB', 'marginBottom': '10px'}),
        html.P("AI-Powered Stock Analysis & Recommendations", 
               style={'textAlign': 'center', 'color': '#6C757D', 'fontSize': '18px'})
    ], style={'backgroundColor': '#F8F9FA', 'padding': '20px', 'marginBottom': '20px'}),
    
    # Controls Section
    html.Div([
        html.Div([
            html.Label("Stock Symbols (comma-separated):", style={'fontWeight': 'bold'}),
            dcc.Input(
                id='symbols-input',
                type='text',
                placeholder='AAPL,MSFT,GOOGL,AMZN,TSLA...',
                style={'width': '100%', 'padding': '8px', 'marginTop': '5px'},
                value='AAPL,MSFT,GOOGL,AMZN,TSLA,META,NVDA,JPM,V,UNH'
            ),
        ], style={'width': '70%', 'display': 'inline-block', 'verticalAlign': 'top'}),
        
        html.Div([
            html.Label("Number of Recommendations:", style={'fontWeight': 'bold'}),
            dcc.Dropdown(
                id='top-n-dropdown',
                options=[
                    {'label': '5', 'value': 5},
                    {'label': '10', 'value': 10},
                    {'label': '15', 'value': 15},
                    {'label': '20', 'value': 20}
                ],
                value=10,
                style={'marginTop': '5px'}
            ),
        ], style={'width': '25%', 'display': 'inline-block', 'marginLeft': '5%'}),
        
        html.Div([
            dcc.Checklist(
                id='demo-mode',
                options=[{'label': ' Demo mode (synthetic prices, no internet needed)', 'value': 'demo'}],
                value=[],
            ),
        ], style={'marginTop': '15px'}),
        
        html.Div([
            html.Button('🔍 Analyze Stocks', id='analyze-button', n_clicks=0,
                       style={'backgroundColor': '#28A745', 'color': 'white', 'border': 'none',
                              'padding': '10px 20px', 'fontSize': '16px', 'borderRadius': '5px',
                              'cursor': 'pointer', 'marginTop': '15px', 'width': '49%'}),
            html.Button('📈 Backtest These Rules', id='backtest-button', n_clicks=0,
                       style={'backgroundColor': '#2E86AB', 'color': 'white', 'border': 'none',
                              'padding': '10px 20px', 'fontSize': '16px', 'borderRadius': '5px',
                              'cursor': 'pointer', 'marginTop': '15px', 'width': '49%', 'marginLeft': '2%'}),
        ], style={'marginTop': '10px'})
    ], style={'padding': '20px', 'backgroundColor': '#FFFFFF', 'marginBottom': '20px',
              'borderRadius': '8px', 'boxShadow': '0 2px 4px rgba(0,0,0,0.1)'}),
    
    # Loading indicator
    dcc.Loading(
        id="loading",
        children=[html.Div(id="loading-output")],
        type="default",
    ),
    
    # Results Section
    html.Div(id='results-container', children=[
        # Summary Cards
        html.Div(id='summary-cards', style={'marginBottom': '20px'}),
        
        # Main Results Table
        html.Div(id='recommendations-table', style={'marginBottom': '20px'}),
        
        # Charts Section
        html.Div([
            html.Div([
                dcc.Graph(id='scores-chart')
            ], style={'width': '50%', 'display': 'inline-block'}),
            
            html.Div([
                dcc.Graph(id='sector-chart')
            ], style={'width': '50%', 'display': 'inline-block'})
        ]),
        
        # Detailed Analysis
        html.Div(id='detailed-analysis', style={'marginTop': '20px'})
    ]),
    
    # Backtest Section
    dcc.Loading(type="default", children=html.Div(id='backtest-container', style={'marginTop': '20px'})),
    
    # Market Overview Section
    html.Div([
        html.H3("📊 Market Overview", style={'color': '#2E86AB'}),
        html.Div(id='market-overview')
    ], style={'padding': '20px', 'backgroundColor': '#FFFFFF', 'marginTop': '20px',
              'borderRadius': '8px', 'boxShadow': '0 2px 4px rgba(0,0,0,0.1)'}),
    
    # Footer
    html.Div([
        html.P("⚠️ Disclaimer: This tool provides analysis for educational purposes only. "
               "Past performance does not guarantee future results. Always do your own research "
               "and consult with financial advisors before making investment decisions.",
               style={'textAlign': 'center', 'color': '#6C757D', 'fontSize': '12px'})
    ], style={'padding': '20px', 'backgroundColor': '#F8F9FA', 'marginTop': '40px'})
])

@app.callback(
    [Output('loading-output', 'children'),
     Output('summary-cards', 'children'),
     Output('recommendations-table', 'children'),
     Output('scores-chart', 'figure'),
     Output('sector-chart', 'figure'),
     Output('detailed-analysis', 'children')],
    [Input('analyze-button', 'n_clicks')],
    [State('symbols-input', 'value'),
     State('top-n-dropdown', 'value'),
     State('demo-mode', 'value')]
)
def update_analysis(n_clicks, symbols_input, top_n, demo_value):
    if n_clicks == 0:
        # Return empty components on initial load
        return "", "", "", {}, {}, ""
    
    try:
        demo = 'demo' in (demo_value or [])
        symbols = parse_symbols(symbols_input, demo)
        
        # Get analysis
        ranker = get_ranker(demo)
        recommendations = ranker.get_top_10_recommendations(symbols, top_n=top_n)
        
        if recommendations['top_10'].empty:
            return (
                html.Div("No recommendations generated. Please check your symbols.", 
                        style={'color': 'red', 'textAlign': 'center'}),
                "", "", {}, {}, ""
            )
        
        # Update global cache
        global last_analysis, last_analysis_time
        last_analysis = recommendations
        last_analysis_time = datetime.now()
        
        top_stocks = recommendations['top_10'].head(top_n)
        summary = recommendations['analysis_summary']
        
        # Create summary cards
        summary_cards = create_summary_cards(summary, len(top_stocks))
        
        # Create recommendations table
        table = create_recommendations_table(top_stocks)
        
        # Create charts
        scores_chart = create_scores_chart(top_stocks)
        sector_chart = create_sector_chart(top_stocks)
        
        # Create detailed analysis
        detailed = create_detailed_analysis(top_stocks.head(3))
        
        return "", summary_cards, table, scores_chart, sector_chart, detailed
        
    except Exception as e:
        error_msg = f"Error during analysis: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return (
            html.Div(error_msg, style={'color': 'red', 'textAlign': 'center'}),
            "", "", {}, {}, ""
        )

def create_summary_cards(summary, num_results):
    """Create summary cards display."""
    cards = html.Div([
        # Total Analyzed Card
        html.Div([
            html.H4(f"{summary['total_analyzed']}", style={'color': '#2E86AB', 'margin': '0'}),
            html.P("Stocks Analyzed", style={'margin': '0', 'color': '#6C757D'})
        ], style={'textAlign': 'center', 'padding': '20px', 'backgroundColor': '#E3F2FD',
                  'borderRadius': '8px', 'width': '18%', 'display': 'inline-block', 'margin': '1%'}),
        
        # Top Recommendations Card
        html.Div([
            html.H4(f"{num_results}", style={'color': '#28A745', 'margin': '0'}),
            html.P("Top Picks", style={'margin': '0', 'color': '#6C757D'})
        ], style={'textAlign': 'center', 'padding': '20px', 'backgroundColor': '#E8F5E8',
                  'borderRadius': '8px', 'width': '18%', 'display': 'inline-block', 'margin': '1%'}),
        
        # Average Score Card
        html.Div([
            html.H4(f"{summary['average_composite_score']:.1f}", style={'color': '#FFC107', 'margin': '0'}),
            html.P("Avg Score", style={'margin': '0', 'color': '#6C757D'})
        ], style={'textAlign': 'center', 'padding': '20px', 'backgroundColor': '#FFF8E1',
                  'borderRadius': '8px', 'width': '18%', 'display': 'inline-block', 'margin': '1%'}),
        
        # Market Sentiment Card
        html.Div([
            html.H4(f"{summary['market_sentiment']}", style={'color': '#DC3545', 'margin': '0'}),
            html.P("Market Sentiment", style={'margin': '0', 'color': '#6C757D'})
        ], style={'textAlign': 'center', 'padding': '20px', 'backgroundColor': '#FFEBEE',
                  'borderRadius': '8px', 'width': '18%', 'display': 'inline-block', 'margin': '1%'}),
        
        # Analysis Time Card
        html.Div([
            html.H4(f"{summary['analysis_date'].split()[1][:5]}", style={'color': '#6F42C1', 'margin': '0'}),
            html.P("Analysis Time", style={'margin': '0', 'color': '#6C757D'})
        ], style={'textAlign': 'center', 'padding': '20px', 'backgroundColor': '#F3E5F5',
                  'borderRadius': '8px', 'width': '18%', 'display': 'inline-block', 'margin': '1%'})
    ])
    
    return cards

def create_recommendations_table(top_stocks):
    """Create the main recommendations table."""
    # Prepare data for the table
    table_data = []
    for idx, (_, row) in enumerate(top_stocks.iterrows(), 1):
        table_data.append({
            'Rank': idx,
            'Symbol': row['Symbol'],
            'Company': row['Company_Name'][:30] + "..." if len(row['Company_Name']) > 30 else row['Company_Name'],
            'Score': f"{row['Composite_Score']:.1f}",
            'Price': f"${row['Current_Price']:.2f}",
            'Change%': f"{row['Daily_Change_Pct']:+.1f}%",
            'ML Score': f"{row['ML_Score']:.1f}",
            'ML Conf.': f"{row['ML_Confidence']:.2f}",
            'Sector': row['Sector'][:20] + "..." if len(row['Sector']) > 20 else row['Sector']
        })
    
    # Create the table
    table = dash_table.DataTable(
        data=table_data,
        columns=[
            {'name': 'Rank', 'id': 'Rank', 'type': 'numeric'},
            {'name': 'Symbol', 'id': 'Symbol'},
            {'name': 'Company', 'id': 'Company'},
            {'name': 'Score', 'id': 'Score', 'type': 'numeric'},
            {'name': 'Price', 'id': 'Price'},
            {'name': 'Change%', 'id': 'Change%'},
            {'name': 'ML Score', 'id': 'ML Score', 'type': 'numeric'},
            {'name': 'ML Conf.', 'id': 'ML Conf.', 'type': 'numeric'},
            {'name': 'Sector', 'id': 'Sector'}
        ],
        style_cell={
            'textAlign': 'left',
            'padding': '10px',
            'fontFamily': 'Arial'
        },
        style_header={
            'backgroundColor': '#2E86AB',
            'color': 'white',
            'fontWeight': 'bold'
        },
        style_data_conditional=[
            {
                'if': {'row_index': 0},
                'backgroundColor': '#E8F5E8',
                'color': 'black',
            },
            {
                'if': {'row_index': 1},
                'backgroundColor': '#FFF8E1',
                'color': 'black',
            },
            {
                'if': {'row_index': 2},
                'backgroundColor': '#FFEBEE',
                'color': 'black',
            }
        ],
        style_as_list_view=True,
    )
    
    return html.Div([
        html.H3("🏆 Top Stock Recommendations", style={'color': '#2E86AB'}),
        table
    ], style={'backgroundColor': '#FFFFFF', 'padding': '20px', 'borderRadius': '8px',
              'boxShadow': '0 2px 4px rgba(0,0,0,0.1)'})

def create_scores_chart(top_stocks):
    """Create a chart showing different score components."""
    symbols = top_stocks['Symbol'].tolist()
    
    fig = go.Figure()
    
    # Add traces for each score component
    fig.add_trace(go.Bar(
        name='Technical Score',
        x=symbols,
        y=top_stocks['Technical_Score'],
        marker_color='#2E86AB'
    ))
    
    fig.add_trace(go.Bar(
        name='ML Score',
        x=symbols,
        y=top_stocks['ML_Score'],
        marker_color='#28A745'
    ))
    
    fig.add_trace(go.Bar(
        name='Momentum Score',
        x=symbols,
        y=top_stocks['Momentum_Score'],
        marker_color='#FFC107'
    ))
    
    fig.add_trace(go.Bar(
        name='Volume Score',
        x=symbols,
        y=top_stocks['Volume_Score'],
        marker_color='#DC3545'
    ))
    
    fig.update_layout(
        title='Score Components by Stock',
        xaxis_title='Stock Symbol',
        yaxis_title='Score (0-100)',
        barmode='group',
        height=400,
        font=dict(family="Arial", size=12)
    )
    
    return fig

def create_sector_chart(top_stocks):
    """Create a pie chart showing sector distribution."""
    sector_counts = top_stocks['Sector'].value_counts()
    
    fig = px.pie(
        values=sector_counts.values,
        names=sector_counts.index,
        title='Sector Distribution of Top Picks'
    )
    
    fig.update_layout(
        height=400,
        font=dict(family="Arial", size=12)
    )
    
    return fig

def create_detailed_analysis(top_3):
    """Create detailed analysis for top 3 stocks."""
    details = []
    
    for idx, (_, row) in enumerate(top_3.iterrows(), 1):
        # Recommendation label computed by the ranker
        recommendation, rec_color = {
            'STRONG BUY': ("🟢 STRONG BUY", "#28A745"),
            'BUY': ("🟡 BUY", "#FFC107"),
            'HOLD/WATCH': ("🟠 HOLD/WATCH", "#FF6B35"),
        }.get(row['Recommendation'], ("🔴 AVOID", "#DC3545"))
        
        details.append(
            html.Div([
                html.H4(f"#{idx} - {row['Symbol']}: {row['Company_Name'][:40]}{'...' if len(row['Company_Name']) > 40 else ''}",
                        style={'color': '#2E86AB', 'marginBottom': '10px'}),
                
                html.Div([
                    html.Div([
                        html.P(f"Composite Score: {row['Composite_Score']:.1f}/100", style={'margin': '5px 0'}),
                        html.P(f"Current Price: ${row['Current_Price']:.2f}", style={'margin': '5px 0'}),
                        html.P(f"Daily Change: {row['Daily_Change_Pct']:+.2f}%", style={'margin': '5px 0'}),
                        html.P(f"Sector: {row['Sector']}", style={'margin': '5px 0'})
                    ], style={'width': '50%', 'display': 'inline-block'}),
                    
                    html.Div([
                        html.P(f"ML Confidence: {row['ML_Confidence']:.2f}", style={'margin': '5px 0'}),
                        html.P(f"Volume: {row['Volume']:,.0f}", style={'margin': '5px 0'}),
                        html.P(f"RSI: {row.get('RSI', 'N/A'):.1f}" if not pd.isna(row.get('RSI', np.nan)) else "RSI: N/A", 
                               style={'margin': '5px 0'}),
                        html.P(f"Recommendation: {recommendation}", 
                               style={'margin': '5px 0', 'fontWeight': 'bold', 'color': rec_color})
                    ], style={'width': '50%', 'display': 'inline-block'})
                ])
            ], style={'backgroundColor': '#F8F9FA', 'padding': '15px', 'marginBottom': '15px',
                      'borderRadius': '8px', 'border': '1px solid #DEE2E6'})
        )
    
    return html.Div([
        html.H3("🔍 Detailed Analysis - Top 3 Picks", style={'color': '#2E86AB'}),
        html.Div(details)
    ], style={'backgroundColor': '#FFFFFF', 'padding': '20px', 'borderRadius': '8px',
              'boxShadow': '0 2px 4px rgba(0,0,0,0.1)'})

@app.callback(
    Output('backtest-container', 'children'),
    [Input('backtest-button', 'n_clicks')],
    [State('symbols-input', 'value'),
     State('top-n-dropdown', 'value'),
     State('demo-mode', 'value')]
)
def run_backtest(n_clicks, symbols_input, top_n, demo_value):
    """Backtest the daily top-N picks over the configured window."""
    if not n_clicks:
        return ""
    try:
        demo = 'demo' in (demo_value or [])
        ranker = get_ranker(demo)
        symbols = parse_symbols(symbols_input, demo) or ranker.config.get('stock_config', {}).get('symbols', [])
        tester = Backtester.from_config(ranker, top_n=min(top_n, max(1, len(symbols) - 1)))
        result = tester.run_symbols(symbols)
        return create_backtest_view(result)
    except Exception as e:
        logger.error(f"Backtest error: {e}", exc_info=True)
        return html.Div(f"Backtest failed: {e}", style={'color': 'red', 'textAlign': 'center'})


def create_backtest_view(result):
    """Cumulative-return chart and metrics table for a backtest result."""
    labels = {'composite_net': 'Composite after costs', 'universe': 'Equal-weight universe',
              'ml_prediction': 'ML only', 'technical_score': 'Technical only',
              'momentum_score': 'Momentum only', 'volume_score': 'Volume only'}
    fig = go.Figure()
    for col, label in labels.items():
        if col in result.daily.columns and result.daily[col].notna().any():
            equity = (1 + result.daily[col].fillna(0)).cumprod() - 1
            fig.add_trace(go.Scatter(x=equity.index, y=equity, name=label, mode='lines',
                                     visible=True if col in ('composite_net', 'universe') else 'legendonly'))
    fig.update_layout(title='Cumulative return of daily top picks vs. equal-weight universe',
                      yaxis_tickformat='.0%', height=420, hovermode='x unified')

    metrics = result.metrics.reset_index().rename(columns={'index': 'Strategy'})
    rows = []
    for _, m in metrics.iterrows():
        rows.append({
            'Strategy': m['Strategy'],
            'Annualized': f"{m['annualized_return']:+.1%}",
            'Sharpe': f"{m['sharpe']:.2f}" if pd.notna(m['sharpe']) else '',
            'Max DD': f"{m['max_drawdown']:.1%}",
            'Excess/day': '' if m['Strategy'].startswith('Equal') else f"{m['avg_daily_excess_bps']:+.1f} bp",
            't-stat': f"{m['excess_t_stat']:+.2f}" if pd.notna(m['excess_t_stat']) else '',
        })
    settings = result.settings
    return html.Div([
        html.H3("📈 Backtest", style={'color': '#2E86AB'}),
        html.P(f"{settings['start']} to {settings['end']} · {settings['days']} trading days · "
               f"{settings['universe_size']} stocks · top {settings['top_n']} · "
               f"{settings['cost_bps']} bp cost · sentiment excluded (no historical data)",
               style={'color': '#6C757D'}),
        dcc.Graph(figure=fig),
        dash_table.DataTable(data=rows, columns=[{'name': c, 'id': c} for c in rows[0]] if rows else [],
                             style_cell={'textAlign': 'left', 'padding': '8px', 'fontFamily': 'Arial'},
                             style_header={'backgroundColor': '#2E86AB', 'color': 'white', 'fontWeight': 'bold'}),
        html.P("t-stat measures whether the daily excess return over the universe is distinguishable "
               "from luck: between -2 and 2 it is not.", style={'color': '#6C757D', 'fontSize': '12px'}),
    ], style={'backgroundColor': '#FFFFFF', 'padding': '20px', 'borderRadius': '8px',
              'boxShadow': '0 2px 4px rgba(0,0,0,0.1)'})


@app.callback(
    Output('market-overview', 'children'),
    [Input('analyze-button', 'n_clicks')],
    [State('demo-mode', 'value')]
)
def update_market_overview(n_clicks, demo_value):
    """Update market overview section."""
    try:
        ranker = get_ranker('demo' in (demo_value or []))
        market_data = ranker.data_collector.fetch_market_data()
        
        if not market_data:
            return html.P("Unable to fetch market data", style={'color': 'red'})
        
        # Create market overview cards
        market_cards = []
        for symbol, data in market_data.items():
            change_pct = data['change_pct']
            
            if change_pct > 0:
                color = "#28A745"
                arrow = "↗️"
            else:
                color = "#DC3545"
                arrow = "↘️"
            
            card = html.Div([
                html.H5(f"{symbol}", style={'margin': '0', 'color': '#2E86AB'}),
                html.P(f"${data['price']:.2f}", style={'margin': '0', 'fontSize': '18px', 'fontWeight': 'bold'}),
                html.P(f"{arrow} {change_pct:+.2f}%", style={'margin': '0', 'color': color, 'fontWeight': 'bold'}),
                html.P(f"{data['name']}", style={'margin': '0', 'fontSize': '12px', 'color': '#6C757D'})
            ], style={'textAlign': 'center', 'padding': '15px', 'backgroundColor': '#F8F9FA',
                      'borderRadius': '8px', 'width': '15%', 'display': 'inline-block', 'margin': '1%',
                      'border': '1px solid #DEE2E6'})
            
            market_cards.append(card)
        
        return html.Div(market_cards)
        
    except Exception as e:
        return html.P(f"Error fetching market data: {str(e)}", style={'color': 'red'})

if __name__ == '__main__':
    print("🚀 Starting Stock Prediction Dashboard...")
    print("📊 Navigate to http://127.0.0.1:8050 to view the dashboard")
    app.run(debug=True, host='127.0.0.1', port=8050)