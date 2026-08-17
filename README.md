# FinanceBot — 국내주식 모니터링 봇

보유 종목과 평단을 등록하면, 장 전/중/후로 시장을 모니터링하고 Telegram으로 알려주는 봇.
Claude API 대신 로컬 `claude -p` (Claude Code CLI, 구독 기반)를 subprocess로 호출한다.
맥미니에서 tmux로 상시 구동을 전제로 설계.

## 하루 흐름 (KST, 거래일만)

| 시간 | 작업 | 내용 |
|------|------|------|
| 08:00 | **프리마켓 브리핑** | 밤사이 미장 지수/섹터 데이터(yfinance) + claude 웹검색으로 보유 종목 관련 섹터·신규 섹터 이슈 분석 → Telegram |
| 09:00~15:30 (5분) | **장중 모니터링** | 시세 스냅샷 저장 + DART 신규 공시 체크 + 트리거 감지. 트리거 발생 시에만 claude가 수급/공시/맥락을 종합해 물타기·손절·홀드 판단 보조 → Telegram |
| 16:00 | **마감 정리** | 오늘 국장 전체 이슈(claude 웹검색) + 보유 종목별 등락/수급(확정치)/공시 요약 → Telegram |

### 장중 트리거 (룰 기반 → claude 호출 절약)
- 신규 공시 발생
- 당일 등락률 절대값 ≥ 임계치 (기본 3%)
- 5분 사이 급변 ≥ 임계치 (기본 1.5%)
- 평단 대비 손실률이 임계선(-5%, -10%, -15%) 최초 하향 돌파
- 누적 거래량이 전일 총거래량 초과 (거래 폭발)
- 종목별 쿨다운(기본 30분)으로 알림 스팸 방지

## 아키텍처

```
financebot/
├── server.py            # FastAPI admin (port 8010) + APScheduler 스케줄러
├── main.py              # CLI 수동 실행: python main.py premarket|intraday|postmarket
├── config.py            # .env 로드, 경로/상수
├── db.py                # SQLite (holdings/snapshots/flows/disclosures/alerts/analyses/settings)
├── market_calendar.py   # KRX 거래일/장중 판정 (exchange_calendars XKRX)
├── collectors/
│   ├── naver_price.py   # 네이버 금융 실시간 시세
│   ├── naver_flow.py    # 수급: 네이버 trend API (일별 외인/기관/개인 순매수량)
│   ├── dart.py          # DART 공시 (corp_code 매핑 자동 캐시)
│   └── us_market.py     # yfinance 미장 지수/섹터 ETF/환율
├── analyzer/
│   ├── claude_cli.py    # `claude -p` subprocess 래퍼 (stdin 프롬프트, 웹검색 허용 옵션)
│   └── prompts.py       # 프리마켓/장중/마감 프롬프트 빌더
├── notifier/
│   └── telegram.py      # Telegram Bot API (4096자 분할 전송)
├── jobs/
│   ├── premarket.py
│   ├── intraday.py
│   └── postmarket.py
├── templates/           # admin 페이지 (대시보드/종목관리/설정/로그)
└── scripts/
    ├── start_tmux.sh    # tmux 세션으로 서버 기동
    └── com.example.financebot.plist  # 부팅 시 자동 시작 (launchd, 경로는 본인 계정명으로 수정)
```

## 설치

```bash
cd ~/financebot
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 값 채우기
```

### 필요한 키 (.env)
| 키 | 발급처 | 용도 |
|----|--------|------|
| `DART_API_KEY` | https://opendart.fss.or.kr (무료, 즉시 발급) | 공시 조회 |
| `TELEGRAM_BOT_TOKEN` | @BotFather | 알림 전송 |
| `TELEGRAM_CHAT_ID` | 봇에게 말 걸고 `https://api.telegram.org/bot<token>/getUpdates`에서 확인 | 알림 대상 |

Claude는 API 키 불필요 — 맥미니에 로그인된 Claude Code CLI(`claude`)를 그대로 사용.

## 실행

```bash
./scripts/start_tmux.sh          # tmux 세션 'financebot'으로 서버 기동
tmux attach -t financebot        # 로그 보기
open http://localhost:8010      # admin 페이지
```

수동 테스트:
```bash
python main.py premarket    # 프리마켓 브리핑 즉시 실행
python main.py intraday     # 장중 1회 실행
python main.py postmarket   # 마감 정리 즉시 실행
```

부팅 자동 시작(선택):
```bash
# plist 안의 /Users/YOUR_USERNAME 경로를 본인 계정명으로 바꾼 뒤 복사
cp scripts/com.example.financebot.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.example.financebot.plist
```

## Admin 페이지 (http://localhost:8010)
- **대시보드**: 보유 종목 현재가/평가손익, 최근 알림
- **종목 관리**: 종목코드/수량/평단 등록·수정·삭제
- **프로필**: 여러 계좌/사람을 분리해서 각자 다른 Telegram으로 알림 발송
- **설정**: 트리거 임계치, 쿨다운, 장중 claude 사용 여부, Telegram 테스트 발송, 로그인 요구 여부
- **로그**: 알림 이력, claude 분석 이력

### 로그인 (선택)
기본값은 로그인 없음(로컬 전용 사용을 가정). `/settings`에서 "관리 화면 로그인 요구"를 켜면, 접속 시 "코드 받기"를 눌러
Telegram(설정된 챗ID, 없으면 서버 콘솔)으로 6자리 코드를 받고 입력해야 들어갈 수 있습니다. 비밀번호를 따로 저장하지 않고
본인 Telegram 계정 소유를 인증 수단으로 씁니다. Telegram이 설정돼 있지 않으면 켤 수 없습니다(콘솔 접근자만 코드 확인 가능해 잠길 위험 방지).
`127.0.0.1` 밖으로 노출할 계획이면 반드시 켜두세요.

## 주의
- 투자 판단 보조 도구일 뿐, 모든 분석은 참고용. 매매 책임은 본인에게 있음.
- 네이버/DART 무료 소스 기반이라 장중 수급은 잠정치 또는 일별 확정치 중심. 실시간 수급이 필요해지면 한국투자증권 OpenAPI로 collector만 교체하면 됨.
- **서버는 기본값으로 `127.0.0.1`(로컬호스트)에만 열립니다.** 휴대폰 등 다른 기기에서 보고 싶다고 `host="0.0.0.0"`으로 바꾸거나
  포트를 그대로 공유기/ngrok으로 열면, 로그인 기능이 꺼져 있는 한 보유 종목·Telegram 챗ID가 인증 없이 노출됩니다.
  원격 접속이 필요하면 포트를 직접 여는 대신 Tailscale 등 사설 네트워크를 쓰고, 로그인은 켜둔 채로 사용하세요.
- `financebot.db`에는 실제 보유 종목·평단가·Telegram chat_id가 저장됩니다. `.gitignore`에 이미 걸려 있지만,
  포크/배포 시 이 파일이나 `*.db.bak*` 백업이 실수로 커밋되지 않는지 한 번 더 확인하세요.
