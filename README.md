# 경제 공부 에이전트

매일경제 1면 신문 사진을 노션에 업로드하면, 에이전트가 자동으로 기사를 분석하고 주간 정리를 생성합니다.

---

## 목적

- 매일 신문을 보는 루틴을 **수동 정리 없이** 자동화
- 이미지로 올린 신문 + 웹 검색을 결합해 정확한 분석 제공
- 사용자가 모르는 경제 용어를 자동으로 설명
- 주간 단위로 한 주의 경제 흐름을 종합 인사이트로 정리
- 주간 복습 퀴즈 3문제 자동 생성 (정답은 토글로 숨김)
- 연속 출석 스트릭 및 월별 출석률 자동 집계

---

## 노션 DB 구조

| DB | 역할 |
|----|------|
| 📅 일일 학습 (매경 1면) | 매일 신문 사진 업로드. 에이전트가 키워드·체크박스 업데이트 |
| 📊 주간 정리 | 에이전트가 자동 생성. 일별 기사 정리 + AI 인사이트 포함 |

### 일일 학습 DB 속성
- **제목**: `YYYYMMDD_요일` (예: `20260522_금`)
- **날짜**: 날짜
- **요일**: 월~토
- **핵심 키워드**: 에이전트가 자동 입력
- **AI 첨언 완료**: 에이전트 처리 완료 시 자동 체크
- **출석**: 에이전트 처리 완료 시 자동 체크

### 사용자가 할 일 (매일)
1. 매경 1면 사진 촬영
2. 노션 일일 학습 DB에 해당 날짜 페이지 열기
3. 사진을 페이지 본문에 붙여넣기
4. (선택) 모르는 용어나 궁금한 점을 텍스트로 같은 페이지에 메모
   - 예: "양도세가 뭔지 모르겠음", "QE란?"
   - 에이전트가 메모를 읽어 용어 설명을 자동 생성

---

## 에이전트 동작 방식

### 주간 에이전트
1. 해당 주 일일 학습 항목 중 **AI 첨언 완료 = False** 항목만 조회
2. 각 페이지에서 이미지 추출 + 사용자 메모 수집
3. **Gemini Vision + Google 검색** 으로 신문 기사 분석
   - 이미지가 흐려도 웹 검색으로 실제 기사 내용 보완
   - 사용자가 메모한 용어는 별도 설명 생성
4. 일별 페이지: 키워드·체크박스만 업데이트 (본문은 건드리지 않음)
5. 주간 정리 DB에 새 페이지 자동 생성

### 주간 정리 페이지 구성
```
🔥 연속 출석 N일 연속
📅 YYYY년 M월 출석률 N/M일 (X%)

📰 일별 기사 정리
  └ 날짜별
      └ ▶ 기사 제목
          - 무슨 일
          - 원인/배경
          - 파급 효과
      └ 📖 용어 정리 (사용자 메모 기반)

🤖 주간 AI 인사이트
  └ 이번 주 종합 요약
  └ 핵심 테마
  └ 거시경제 맥락
  └ 투자 인사이트
  └ 생활 인사이트
  └ 다음 주 주목 포인트

❓ 이번 주 퀴즈
  └ Q1. [인과관계 문제]  A/B/C/D 선택지
      └ ▶ 정답 보기 (토글 — 클릭하면 정답·해설 표시)
  └ Q2. ...
  └ Q3. ...
```

---

## 설치 및 환경 설정

### 1. 의존성 설치
```bash
pip install -r requirements.txt
```

### 2. .env 파일 설정
```bash
cp .env.example .env
```

`.env`에 아래 값 입력:
```
NOTION_TOKEN=secret_...          # 노션 Integration 토큰
GEMINI_API_KEY=AIza...           # Google AI Studio API 키
DAILY_DB_ID=...                  # 일일 학습 DB ID
WEEKLY_DB_ID=...                 # 주간 정리 DB ID
```

**노션 DB ID 찾는 법**: 브라우저에서 DB를 열면 URL이
`notion.so/.../xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx?v=...` 형태.
`?v=` 앞의 32자리가 DB ID.

**노션 Integration 연결**: 각 DB 페이지 우상단 `...` → Connections → 생성한 Integration 추가 필요

---

## 사용 방법

### 터미널 실행 방법

1. Mac에서 **터미널** 앱 열기 (Spotlight에서 "터미널" 검색)
2. 아래 명령어로 프로젝트 폴더로 이동
```bash
cd /Users/soyeonpark/Desktop/economy_study-agent
```
3. 실행 명령어 입력

> Claude Code 대화창에서도 실행 가능 — 명령어 앞에 `!`를 붙이면 됩니다.
> 예: `! python main.py weekly`

---

### 주간 정리 (매주 토요일 이후 실행)
```bash
# 이번 주 정리
python main.py weekly

# 특정 날짜가 속한 주 정리 (지난주 재실행 등)
python main.py weekly 2026-05-22
```

### 자주 쓰는 시나리오

**토요일에 한 주 마무리**
```bash
python main.py weekly
```

**지난주 처리를 놓쳤을 때**
```bash
python main.py weekly 2026-05-22   # 해당 주에 속한 날짜 아무거나
```

**특정 날만 다시 처리하고 싶을 때**
1. 노션에서 해당 날짜 페이지의 **AI 첨언 완료** 체크박스 해제
2. 해당 날짜로 재실행
```bash
python main.py weekly 2026-05-22
```

---

## 파일 구조

```
economy_study-agent/
├── .env                    # API 키 (git에 올리지 말 것)
├── .env.example            # 환경변수 템플릿
├── requirements.txt        # 패키지 목록
├── config.py               # 설정값, 프롬프트 상수
├── main.py                 # CLI 진입점
├── agents/
│   └── weekly_agent.py     # 주간 에이전트 오케스트레이션
└── services/
    ├── notion_service.py   # Notion API 래퍼
    └── claude_service.py   # Gemini API 래퍼 (Vision + Search)
```

---

## 주의사항

- `.env` 파일은 절대 git에 커밋하지 마세요 (API 키 노출)
- Gemini API는 Google AI Studio 무료 티어 사용 (aistudio.google.com)
- 노션 Integration이 두 DB 모두에 연결되어 있어야 함
- 이미 처리된 항목(AI 첨언 완료 = True)은 재실행해도 건너뜀
