#!/bin/bash
# tmux 세션 'financebot'으로 서버 상시 구동
SESSION=financebot
DIR="$(cd "$(dirname "$0")/.." && pwd)"

if tmux has-session -t $SESSION 2>/dev/null; then
  echo "이미 실행 중입니다. tmux attach -t $SESSION 으로 확인하세요."
  exit 0
fi

tmux new-session -d -s $SESSION -c "$DIR" "source venv/bin/activate && python server.py"
echo "시작됨: tmux attach -t $SESSION | admin: http://localhost:8010"
