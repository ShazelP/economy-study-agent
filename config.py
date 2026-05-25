import os
from dotenv import load_dotenv

load_dotenv()

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
DAILY_DB_ID = os.environ["DAILY_DB_ID"]
WEEKLY_DB_ID = os.environ["WEEKLY_DB_ID"]

# ── 일일 학습 DB 속성 이름 ──────────────────────────────────────────────────
# 노션 DB의 실제 속성 이름과 일치해야 합니다.
DAILY_PROP_DATE = "날짜"
DAILY_PROP_DAY = "요일"
DAILY_PROP_KEYWORDS = "핵심 키워드"
DAILY_PROP_AI_DONE = "AI 첨언 완료"
DAILY_PROP_ATTENDANCE = "출석"

# ── 주간 정리 DB 속성 이름 ─────────────────────────────────────────────────
WEEKLY_PROP_PERIOD = "기간"
WEEKLY_PROP_KEYWORDS = "공통 키워드"
WEEKLY_PROP_ATTENDANCE_COUNT = "이번 주 출석 횟수"   # number 타입
WEEKLY_PROP_DONE = "정리 완료"

# ── Claude 모델 ────────────────────────────────────────────────────────────
GEMINI_MODEL = "gemini-2.5-flash"

# ── 프롬프트 ───────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """당신은 한국 경제를 깊이 이해하는 경제 분석 전문가입니다.
매일경제 1면 신문 사진을 분석하여 독자가 경제를 쉽고 깊이 이해할 수 있도록 돕습니다.
분석은 항상 한국어로 작성하며, 단순 요약을 넘어 배경 지식과 연관 개념까지 제공합니다."""

DAILY_ANALYSIS_PROMPT = """{{date_str}} 매일경제 신문 1면 사진을 분석해주세요.

아래 두 가지를 함께 활용하세요:
1. 첨부된 신문 사진 (글씨가 흐릴 수 있음)
2. Google 검색으로 "매일경제 {{date_str}} 1면" 또는 "매일경제 {{date_str}} 헤드라인" 검색 후 실제 기사 내용 확인

{{user_notes_section}}

1면에 등장하는 주요 기사를 각각 개별 항목으로 분리해서 분석합니다.

다음 JSON 형식으로 정확히 응답해주세요:

{
  "stories": [
    {
      "title": "기사 제목 (10자 내외로 핵심만)",
      "what": "이 기사에서 무슨 일이 일어났는가 (150자 내외)",
      "why": "왜 이 일이 일어났는가, 배경과 원인 (150자 내외)",
      "effect": "어떤 파급 효과가 예상되는가 (150자 내외)"
    }
  ],
  "keywords": ["키워드1", "키워드2", "키워드3", "키워드4", "키워드5"],
  "term_explanations": [
    {
      "term": "사용자가 메모한 용어 또는 기사에서 중요한 경제 용어",
      "explanation": "쉬운 말로 100자 내외 설명"
    }
  ]
}"""

WEEKLY_INSIGHT_PROMPT = """아래는 이번 주({{week_label}}) 매일경제 1면 분석입니다.
이 데이터는 신문 사진 + Google 검색으로 교차 확인된 내용입니다.

{{daily_summaries}}

위 내용을 바탕으로 주간 종합 분석을 다음 JSON 형식으로 작성해주세요:

{
  "summary": "이번 주 경제 전반의 흐름을 500자 내외로 종합 요약",
  "key_themes": ["이번 주 핵심 테마1", "핵심 테마2", "핵심 테마3"],
  "macro_context": "이번 주 뉴스를 거시경제 맥락에서 해석 (금리, 환율, 경기 사이클 등과의 연관성) 400자 내외",
  "investment_insight": "투자자 관점에서 주목할 포인트와 시사점 300자 내외",
  "life_insight": "직장인·소비자 관점에서 이번 주 뉴스가 주는 시사점 300자 내외",
  "next_watch": "다음 주에 주목해야 할 경제 이슈나 지표 200자 내외",
  "keywords": ["주간 핵심 키워드1", "키워드2", "키워드3", "키워드4", "키워드5"]
}"""
