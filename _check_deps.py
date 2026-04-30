import ast, sys, traceback
files = ['backend/app.py','backend/core/actions.py','backend/core/parser.py','backend/core/locators.py','backend/core/executor.py']
for f in files:
    try:
        ast.parse(open(f, encoding='utf-8').read(), f)
        print('OK', f)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
print('ALL_SYNTAX_OK')
try:
    import backend.app  # noqa
    print('IMPORT_OK')
except Exception:
    traceback.print_exc()
    sys.exit(2)