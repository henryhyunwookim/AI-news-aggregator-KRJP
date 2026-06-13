import os
import sys
from flask import Flask, jsonify, request
from src.main import main

app = Flask(__name__)

@app.route("/", methods=["POST", "GET"])
def run_aggregator():
    """Triggers the news aggregator execution."""
    try:
        # Allow specifying lookback window via query parameter or JSON request
        hours = request.args.get('hours', default=24, type=int)
        
        # Check for JSON request body override
        if request.is_json:
            data = request.get_json()
            if data and 'hours' in data:
                hours = int(data['hours'])
                
        print(f"Received trigger request. Starting news aggregator (lookback: {hours} hours)...")
        result = main(hours_back=hours)
        
        if result and result.get('success'):
            return jsonify({
                'status': 'success',
                'message': 'News aggregator ran successfully',
                'stats': result.get('stats', {})
            }), 200
        else:
            return jsonify({
                'status': 'error',
                'message': f"Aggregator encountered an error: {result.get('error', 'Unknown error')}",
                'stats': result.get('stats', {})
            }), 500
            
    except Exception as e:
        print(f"Error running aggregator web service: {e}")
        return jsonify({
            'status': 'error',
            'message': f"Error: {e}"
        }), 500

if __name__ == "__main__":
    # Cloud Run sets PORT environment variable automatically
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
