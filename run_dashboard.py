"""
Launcher script for the web dashboard.
"""

import sys
import os

# Get the root directory (parent of web directory)
root_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(root_dir, 'src')

# Add both to Python path
sys.path.insert(0, root_dir)
sys.path.insert(0, src_dir)

# Now import and run the dashboard
if __name__ == "__main__":
    from web.dashboard import app
    print("🌐 Starting Stock Prediction Dashboard...")
    print("📊 Dashboard will be available at: http://127.0.0.1:8050")
    print("🚀 Loading interface...")
    app.run(debug=True, host='127.0.0.1', port=8050)