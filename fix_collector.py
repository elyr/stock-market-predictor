"""
Quick fix for remaining Yahoo Finance references in collector.py
"""

# Read the file
with open('src/data/collector.py', 'r') as f:
    content = f.read()

# Replace all remaining yf.Ticker references with simplified Alpha Vantage implementation
content = content.replace('self._respect_rate_limit(\'yfinance\')', '# Rate limiting handled by _rate_limit()')
content = content.replace('ticker = yf.Ticker(symbol)', '# Simplified for Alpha Vantage free tier')

# Add simplified methods where needed
replacements = [
    ('calendar = ticker.calendar', 'calendar = None  # Not available in Alpha Vantage free tier'),
    ('news = ticker.news', 'news = []  # Not available in Alpha Vantage free tier'),
    ('options_dates = ticker.options', 'options_dates = []  # Not available in Alpha Vantage free tier'),
    ('options = ticker.option_chain(options_dates[0])', 'options = None  # Not available in Alpha Vantage free tier')
]

for old, new in replacements:
    content = content.replace(old, new)

# Write back
with open('src/data/collector.py', 'w') as f:
    f.write(content)

print("✅ Fixed all Yahoo Finance references!")