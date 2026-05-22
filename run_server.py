import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("Python path:", sys.path)
print("Current directory:", os.getcwd())

try:
    from backend.app import app
    print("App imported successfully")
    
    # Run the server
    app.run(host='0.0.0.0', port=5050, debug=False)
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()