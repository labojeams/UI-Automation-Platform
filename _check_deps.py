import importlib, sys
mods = ["flask", "flask_cors", "flask_sock", "playwright", "requests"]
for m in mods:
    try:
        importlib.import_module(m)
        print(f"OK   {m}")
    except Exception as e:
        print(f"MISS {m}: {e}")
print("python:", sys.version)