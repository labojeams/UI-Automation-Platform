import sys
import os
import traceback

log_file = open(os.path.join(os.path.dirname(__file__), '_startup.log'), 'w', encoding='utf-8')
sys.stdout = log_file
sys.stderr = log_file

print("=" * 50, flush=True)
print("Starting UI Automation Platform...", flush=True)
print(f"Python: {sys.version}", flush=True)
print(f"Working dir: {os.getcwd()}", flush=True)
print(f"File location: {__file__}", flush=True)

try:
    print("\nImporting backend.app...", flush=True)
    from backend.app import app, main
    print("Import successful!", flush=True)
    print(f"App: {app}", flush=True)
    print(f"Static folder: {app.static_folder}", flush=True)
    
    print("\nStarting server on http://127.0.0.1:5050", flush=True)
    print("=" * 50, flush=True)
    log_file.flush()
    
    app.run(host='0.0.0.0', port=5050, debug=False, threaded=True)
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}", flush=True)
    print(traceback.format_exc(), flush=True)
    log_file.flush()
    sys.exit(1)
