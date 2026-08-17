"""수동 실행 CLI: python main.py premarket|intraday|postmarket"""
import sys

import db


def main():
    db.init_db()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "premarket":
        from jobs import premarket
        premarket.run(force=True)
    elif cmd == "intraday":
        from jobs import intraday
        intraday.run(force=True)
    elif cmd == "postmarket":
        from jobs import postmarket
        postmarket.run(force=True)
    else:
        print("사용법: python main.py premarket|intraday|postmarket")
        sys.exit(1)


if __name__ == "__main__":
    main()
