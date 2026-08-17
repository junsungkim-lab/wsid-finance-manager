#!/bin/bash
# 서버 헬스체크 — 응답 없으면 tmux 세션 재시작. cron 5분 간격 권장.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG="/tmp/financebot.watchdog.log"
PORT=8010

if curl -s -o /dev/null -m 8 "http://localhost:$PORT/"; then
  exit 0  # 정상
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') 서버 무응답 — 재시작" >> "$LOG"
tmux kill-session -t financebot 2>/dev/null
sleep 2
"$DIR/scripts/start_tmux.sh" >> "$LOG" 2>&1
