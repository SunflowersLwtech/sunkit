"""room-companion entry point: python -m room_companion"""
from __future__ import annotations

import signal
import sys
import threading

from .app import App, load_config
from .web import serve


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "pair":
        # python -m room_companion pair --code K7QM-2WXH [--name Bedroom]: uses the "hipimind" config section
        from .hipimind import pair_from_app_config
        sys.exit(pair_from_app_config(sys.argv[2:], load_config()))
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
