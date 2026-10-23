"""python3 -m helpdesk serve [--port 8766] [--secondlook http://127.0.0.1:8765]"""
import argparse

from .app import serve


def main() -> None:
    ap = argparse.ArgumentParser(prog="python3 -m helpdesk", description="Ticketbook, a made-up helpdesk with Second Look inside.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run Ticketbook in the browser")
    s.add_argument("--port", type=int, default=8766)
    s.add_argument("--secondlook", default="http://127.0.0.1:8765", help="where Second Look runs")
    args = ap.parse_args()
    if args.cmd == "serve":
        serve(args.port, args.secondlook)


if __name__ == "__main__":
    main()
