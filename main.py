# -*- coding: utf-8 -*-
"""「药鉴」入口：起 Flask 后端线程 + 打开桌面窗口（Windows: Edge WebView2 / macOS: WKWebView）。"""
import os
import socket
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
from backend import kb as kb_mod  # noqa: E402
from backend.server import create_app  # noqa: E402


def find_free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def show_error_box(msg):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, config.APP_NAME, 0x10)
    except Exception:
        print(msg)


def main():
    kb_mod.ensure_data_dirs()
    from backend import events
    events.record("app_launch", first_run=not os.path.exists(os.path.join(config.DATA_DIR, "settings.json")))
    port = find_free_port()
    app = create_app()
    threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False),
        daemon=True,
    ).start()

    import webview
    try:
        webview.create_window(
            config.APP_NAME,
            f"http://127.0.0.1:{port}",
            width=1200,
            height=800,
            min_size=(960, 640),
        )
        webview.start()
    except Exception as e:
        err = str(e)
        if "WebView2" in err or "webview" in err.lower():
            show_error_box(
                "启动失败：系统缺少 Edge WebView2 运行库。\n\n"
                "请到微软官网下载并安装（选 Evergreen Bootstrapper）：\n"
                "https://developer.microsoft.com/microsoft-edge/webview2/\n\n"
                "安装后重新启动本程序即可。\n\n错误详情：%s" % err
            )
        else:
            show_error_box("启动失败：%s" % err)


if __name__ == "__main__":
    main()
