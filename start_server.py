import subprocess
import sys
import os

os.chdir(r"c:\Users\ext.lanbo6\PycharmProjects\ui-automation-platform")

print("Python version:", sys.version)
print("Starting server...")

# Try running the server
try:
    result = subprocess.run(
        [sys.executable, "-m", "backend.app"],
        capture_output=True,
        text=True,
        timeout=5
    )
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
except subprocess.TimeoutExpired:
    print("Server started successfully (timeout as expected)")
except Exception as e:
    print("Error:", e)