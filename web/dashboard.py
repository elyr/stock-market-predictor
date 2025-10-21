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

# Add src to Python path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

# Import modules directly with absolute path
import importlib.util
import sys

# Load StockRanker module
spec = importlib.util.spec_from_file_location(
    "stock_ranker", 
    os.path.join(os.path.dirname(__file__), '..', 'src', 'prediction', 'stock_ranker.py')
)
stock_ranker_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stock_ranker_module)
StockRanker = stock_ranker_module.StockRanker

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Dash app
app = dash.Dash(__name__)
app.title = "Stock Prediction Dashboard"

# Global variables for caching
ranker = None
last_analysis = None
last_analysis_time = None

def get_ranker():
    """Get or initialize the stock ranker."""
    global ranker
    if ranker is None:
        ranker = StockRanker()
    return ranker

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
            html.Button('🔍 Analyze Stocks', id='analyze-button', n_clicks=0,
                       style={'backgroundColor': '#28A745', 'color': 'white', 'border': 'none',
                              'padding': '10px 20px', 'fontSize': '16px', 'borderRadius': '5px',
                              'cursor': 'pointer', 'marginTop': '25px', 'width': '100%'})
        ], style={'marginTop': '20px'})
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
     State('top-n-dropdown', 'value')]
)
def update_analysis(n_clicks, symbols_input, top_n):
    if n_clicks == 0:
        # Return empty components on initial load
        return "", "", "", {}, {}, ""
    
    try:
        # Parse symbols
        if symbols_input:
            symbols = [s.strip().upper() for s in symbols_input.split(',') if s.strip()]
        else:
            symbols = None
        
        # Get analysis
        ranker = get_ranker()
        recommendations = ranker.get_top_10_recommendations(symbols)
        
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
        # Determine recommendation
        score = row['Composite_Score']
        confidence = row['ML_Confidence']
        
        if score >= 75 and confidence >= 0.7:
            recommendation = "🟢 STRONG BUY"
            rec_color = "#28A745"
        elif score >= 65 and confidence >= 0.6:
            recommendation = "🟡 BUY"
            rec_color = "#FFC107"
        elif score >= 55:
            recommendation = "🟠 HOLD/WATCH"
            rec_color = "#FF6B35"
        else:
            recommendation = "🔴 AVOID"
            rec_color = "#DC3545"
        
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
    Output('market-overview', 'children'),
    [Input('analyze-button', 'n_clicks')]
)
def update_market_overview(n_clicks):
    """Update market overview section."""
    try:
        ranker = get_ranker()
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
    app.run_server(debug=True, host='127.0.0.1', port=8050)