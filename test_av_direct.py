"""
Quick Alpha Vantage Test
"""

import requests
import os
from dotenv import load_dotenv

load_dotenv()

def test_alpha_vantage():
    api_key = os.getenv('ALPHA_VANTAGE_API_KEY')
    print(f"🔑 API Key: {api_key[:8]}***")
    
    url = "https://www.alphavantage.co/query"
    params = {
        'function': 'GLOBAL_QUOTE',
        'symbol': 'AAPL',
        'apikey': api_key
    }
    
    response = requests.get(url, params=params, timeout=15)
    data = response.json()
    
    print(f"📊 Response for AAPL:")
    print(data)

if __name__ == "__main__":
    test_alpha_vantage()