"""python3 -m bookbox serve [--port 8767]"""
import argparse

from .app import serve


def main() -> None:
    ap = argparse.ArgumentParser(prog="python3 -m bookbox", description="Bookbox, a made-up bookkeeping stand-in.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run Bookbox in the browser")
    s.add_argument("--port", type=int, default=8767)
    args = ap.parse_args()
    if args.cmd == "serve":
        serve(args.port)


if __name__ == "__main__":
    main()
