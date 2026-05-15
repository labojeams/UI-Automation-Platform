import sys, traceback, socket
log = []
def w(msg):
    log.append(str(msg))
try:
    w("python_version=" + sys.version)
    w("cwd=" + __import__('os').getcwd())
    try:
        from flask import Flask
        w("flask=ok")
    except Exception as e:
        w("flask_err=" + repr(e))
    try:
        import backend.app as a
        w("backend.app=ok")
    except SystemExit as e:
        w("backend.app_sysexit=" + repr(e))
    except Exception as e:
        w("backend.app_err=" + repr(e))
        w(traceback.format_exc())
    # 端口测试
    try:
        s = socket.socket(); s.bind(("127.0.0.1", 5050)); s.close()
        w("port_5050=free")
    except Exception as e:
        w("port_5050=" + repr(e))
finally:
    open('_diag.txt','w',encoding='utf-8').write("\n".join(log))