"""room-companion entry point: python -m room_companion"""
from __future__ import annotations

import signal
import sys
import threading

from .app import App, load_config
from .web import serve


def main():
    cfg = load_config()
    app = App(cfg)
    app.start()
    srv = serve(app)
    done = threading.Event()

    def stop(signum, frame):
        if done.is_set():
            return
        done.set()
        app.shutdown()  # release camera and mic before exiting
        threading.Thread(target=srv.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f"room-companion listening on {cfg['listen']}:{cfg['port']}", flush=True)
    srv.serve_forever()
    app.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    main()
