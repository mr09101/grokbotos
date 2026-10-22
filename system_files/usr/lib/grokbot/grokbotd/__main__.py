"""grokbotd entry point: python3 -m grokbotd [--no-http]"""
import argparse
import os
import signal
import sys
import threading

from . import VERSION, audit, paths, rpc, schema, server, updates


def main(argv=None):
    ap = argparse.ArgumentParser(prog="grokbotd")
    ap.add_argument("--no-http", action="store_true", help="unix socket only")
    ap.add_argument("--version", action="version", version=VERSION)
    a = ap.parse_args(argv)
    disp = rpc.Dispatcher(schema.load())
    us, hs = server.serve(disp, http=not a.no_http)
    audit.record(event="start", version=VERSION, socket=paths.socket_path(),
                 http=None if hs is None else "127.0.0.1:%d" % paths.http_port())
    print("grokbotd %s: unix %s%s" % (VERSION, paths.socket_path(),
          "" if hs is None else ", http 127.0.0.1:%d" % paths.http_port()), flush=True)
    stop = threading.Event()
    if os.environ.get("GROKBOT_UPDATE_NOTIFY", "1") != "0":
        updates.watch(stop)
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, lambda *_: stop.set())
    stop.wait()
    us.shutdown()
    if hs:
        hs.shutdown()
    audit.record(event="stop")
    return 0


if __name__ == "__main__":
    sys.exit(main())
