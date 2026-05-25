from __future__ import annotations

import time
from datetime import date, timedelta

from services.claude_service import ClaudeService
from services.notion_service import NotionService


def _get_week_range(reference: date | None = None) -> tuple[date, date]:
    """기준일 기준 해당 주 월요일~토요일 반환. 기본값은 오늘."""
    today = reference or date.today()
    monday = today - timedelta(days=today.weekday())
    saturday = monday + timedelta(days=5)
    return monday, saturday


def _week_label(monday: date) -> str:
    iso_year, iso_week, _ = monday.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def run(reference_date: date | None = None) -> None:
    notion = NotionService()
    claude = ClaudeService()

    week_start, week_end = _get_week_range(reference_date)
    week_label = _week_label(week_start)

    print(f"\n{'='*50}")
    print(f"주간 에이전트 시작: {week_label} ({week_start} ~ {week_end})")
    print(f"{'='*50}\n")

    # 1. 해당 주 미처리 항목 조회
    entries = notion.get_weekly_entries(week_start, week_end)
    print(f"처리 대상 항목: {len(entries)}개\n")

    if not entries:
        print("처리할 항목이 없습니다. (모두 완료되었거나 업로드된 사진이 없음)")
        return

    # 2. 각 항목 이미지 분석 (본문은 건드리지 않음)
    daily_analyses: list[dict] = []
    processed_count = 0

    for entry in entries:
        page_id = entry["id"]
        title = _get_title(entry)
        print(f"[{title}] 처리 중...")

        page_content = notion.get_page_content(page_id)
        image_urls = page_content["image_urls"]
        user_notes = page_content["text_notes"]

        if not image_urls:
            print(f"  ⚠ 이미지 없음 — 건너뜀\n")
            continue

        # 날짜 문자열 추출 (제목 YYYYMMDD_요일 → "YYYY년 MM월 DD일")
        date_str = _parse_date_str(title)
        if user_notes:
            print(f"  사용자 메모 {len(user_notes)}개 발견")
        print(f"  이미지 + 웹 검색으로 분석 중...")
        analysis = claude.analyze_newspaper_image(image_urls[0], date_str, user_notes or None)
        if not analysis or not analysis.get("stories"):
            print(f"  ⚠ 분석 실패 — 건너뜀\n")
            continue

        # 날짜 레이블 추가 (주간 정리 블록에서 날짜별로 구분하기 위해)
        analysis["date_label"] = title

        # 일별 페이지: 키워드 + 체크박스만 업데이트 (본문 작성 없음)
        notion.update_daily_page(page_id, analysis.get("keywords", []))
        daily_analyses.append(analysis)
        processed_count += 1

        stories_count = len(analysis.get("stories", []))
        print(f"  ✓ 완료 (기사 {stories_count}건, 키워드: {', '.join(analysis.get('keywords', []))})\n")

        time.sleep(1)

    print(f"일별 분석 완료: {processed_count}/{len(entries)}개")

    if processed_count == 0:
        print("분석된 항목이 없어 주간 정리를 건너뜁니다.")
        return

    # 3. 주간 인사이트 생성
    print("\n주간 인사이트 생성 중...")
    insights = claude.generate_weekly_insights(week_label, daily_analyses)
    if not insights:
        print("⚠ 주간 인사이트 생성 실패")
        return

    # 4. 주간 정리 DB에 저장
    print("주간 정리 DB에 저장 중...")
    page_id = notion.create_weekly_summary(
        week_label=week_label,
        period_start=week_start,
        period_end=week_end,
        attendance_count=processed_count,
        daily_analyses=daily_analyses,
        insights=insights,
    )

    print(f"\n{'='*50}")
    print(f"주간 에이전트 완료! 주간 정리 페이지 생성됨 (ID: {page_id})")
    print(f"{'='*50}\n")


def _get_title(entry: dict) -> str:
    try:
        title_prop = entry["properties"].get("제목") or entry["properties"].get("Name") or {}
        rich_text = title_prop.get("title", [])
        if rich_text:
            return rich_text[0]["plain_text"]
    except (KeyError, IndexError):
        pass
    return entry.get("id", "unknown")[:8]


def _parse_date_str(title: str) -> str:
    """'20260522_금' → '2026년 5월 22일'"""
    try:
        digits = title[:8]
        return f"{digits[:4]}년 {int(digits[4:6])}월 {int(digits[6:8])}일"
    except Exception:
        return title
