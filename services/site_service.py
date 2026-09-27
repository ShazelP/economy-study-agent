from __future__ import annotations

import html
from datetime import date
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
WEEKS_DIR = DOCS_DIR / "weeks"


def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def _render_story(story: dict) -> str:
    return f"""
        <article class="story">
          <h3>▶ {_esc(story.get('title', ''))} <span class="story-type">{_esc(story.get('type', ''))}</span></h3>
          <p><strong>무슨 일</strong> {_esc(story.get('what', ''))}</p>
          <p><strong>배경/논의 내용</strong> {_esc(story.get('why', ''))}</p>
          <p><strong>효과/시사점</strong> {_esc(story.get('effect', ''))}</p>
        </article>"""


def _render_day(day: dict) -> str:
    stories_html = "".join(_render_story(s) for s in day.get("stories", []))
    terms = day.get("term_explanations", [])
    terms_html = ""
    if terms:
        items = "".join(
            f"<li><strong>{_esc(t.get('term', ''))}</strong> — {_esc(t.get('explanation', ''))}</li>"
            for t in terms
        )
        terms_html = f'<div class="terms"><h4>📖 용어 정리</h4><ul>{items}</ul></div>'

    return f"""
      <details class="day">
        <summary>{_esc(day.get('date_label', ''))}</summary>
        {stories_html}
        {terms_html}
      </details>"""


def _render_quiz(quiz: list[dict] | None) -> str:
    if not quiz:
        return ""
    items = []
    for i, q in enumerate(quiz, 1):
        choices_html = "".join(f"<li>{_esc(c)}</li>" for c in q.get("choices", []))
        items.append(f"""
        <div class="quiz-item">
          <p class="quiz-question">Q{i}. {_esc(q.get('question', ''))}</p>
          <ul class="quiz-choices">{choices_html}</ul>
          <details>
            <summary>정답 보기</summary>
            <p><strong>정답: {_esc(q.get('answer', ''))}</strong></p>
            <p>{_esc(q.get('explanation', ''))}</p>
          </details>
        </div>""")
    return f"""
      <section class="quiz">
        <h1>❓ 이번 주 퀴즈</h1>
        {''.join(items)}
      </section>"""


def _render_archive_list() -> str:
    if not WEEKS_DIR.exists():
        return ""
    weeks = sorted((p.stem for p in WEEKS_DIR.glob("*.html")), reverse=True)
    if not weeks:
        return ""
    items = "".join(f'<li><a href="weeks/{w}.html">{w}</a></li>' for w in weeks)
    return f'<section class="archive"><h2>지난 주 정리</h2><ul>{items}</ul></section>'


def render_weekly_page(
    week_label: str,
    week_start: date,
    week_end: date,
    daily_analyses: list[dict],
    insights: dict,
    quiz: list[dict] | None,
    *,
    include_archive: bool,
) -> str:
    """참여자 통계는 의도적으로 인자에 없음 — 공개 웹사이트에는 노출하지 않음."""
    days_html = "".join(_render_day(d) for d in daily_analyses)
    themes_html = "".join(f"<li>{_esc(t)}</li>" for t in insights.get("key_themes", []))
    quiz_html = _render_quiz(quiz)
    archive_html = _render_archive_list() if include_archive else ""

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(week_label)} 경제 공부 주간정리</title>
<link rel="stylesheet" href="{'style.css' if include_archive else '../style.css'}">
</head>
<body>
  <header>
    <p class="site-name">경제 공부 주간정리</p>
    <h1>{_esc(week_label)}</h1>
    <p class="period">{week_start.isoformat()} ~ {week_end.isoformat()}</p>
  </header>

  <section class="next-watch">
    <h2>👀 다음 주 주목 포인트</h2>
    <p>{_esc(insights.get('next_watch', ''))}</p>
  </section>

  <section class="insights">
    <h1>🤖 주간 AI 인사이트</h1>
    <h2>📊 이번 주 종합 요약</h2>
    <p>{_esc(insights.get('summary', ''))}</p>
    <h2>🎯 핵심 테마</h2>
    <ul>{themes_html}</ul>
    <h2>🌐 거시경제 맥락</h2>
    <p>{_esc(insights.get('macro_context', ''))}</p>
    <h2>💰 투자 인사이트</h2>
    <p>{_esc(insights.get('investment_insight', ''))}</p>
    <h2>🏠 생활 인사이트</h2>
    <p>{_esc(insights.get('life_insight', ''))}</p>
  </section>

  <section class="daily">
    <h1>📰 일별 기사 정리</h1>
    {days_html}
  </section>

  {quiz_html}

  {archive_html}
</body>
</html>
"""


def build_and_save(
    week_label: str,
    week_start: date,
    week_end: date,
    daily_analyses: list[dict],
    insights: dict,
    quiz: list[dict] | None,
) -> None:
    """docs/index.html(최신 주)과 docs/weeks/{week_label}.html(아카이브)을 로컬에 생성. git 작업은 하지 않음."""
    WEEKS_DIR.mkdir(parents=True, exist_ok=True)

    archive_page = render_weekly_page(
        week_label, week_start, week_end, daily_analyses, insights, quiz, include_archive=False
    )
    (WEEKS_DIR / f"{week_label}.html").write_text(archive_page, encoding="utf-8")

    index_page = render_weekly_page(
        week_label, week_start, week_end, daily_analyses, insights, quiz, include_archive=True
    )
    (DOCS_DIR / "index.html").write_text(index_page, encoding="utf-8")
