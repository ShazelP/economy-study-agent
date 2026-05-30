from __future__ import annotations

import time
from datetime import date
from typing import Any

from notion_client import Client

import config


def _get_entry_title(entry: dict) -> str:
    try:
        title_prop = entry["properties"].get("제목") or entry["properties"].get("Name") or {}
        rich_text = title_prop.get("title", [])
        if rich_text:
            return rich_text[0]["plain_text"]
    except (KeyError, IndexError):
        pass
    return ""


def _parse_date_from_title(title: str) -> date | None:
    """'20260526_화' → date(2026, 5, 26). 파싱 실패 시 None."""
    try:
        digits = title[:8]
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except (ValueError, IndexError):
        return None


class NotionService:
    def __init__(self):
        self.client = Client(auth=config.NOTION_TOKEN)

    # ── 일일 학습 DB ───────────────────────────────────────────────────────

    def get_weekly_entries(self, week_start: date, week_end: date) -> list[dict]:
        """AI 첨언 미완료 항목 중 제목(YYYYMMDD_요일)을 파싱해 해당 주 항목을 반환."""
        response = self.client.databases.query(
            database_id=config.DAILY_DB_ID,
            filter={
                "property": config.DAILY_PROP_AI_DONE,
                "checkbox": {"equals": False},
            },
            sorts=[{"property": "제목", "direction": "ascending"}],
        )
        results = []
        for entry in response.get("results", []):
            title = _get_entry_title(entry)
            entry_date = _parse_date_from_title(title)
            if entry_date and week_start <= entry_date <= week_end:
                results.append(entry)
        return results

    def get_page_content(self, page_id: str) -> dict:
        """페이지 본문 블록을 순회하여 이미지 URL 목록과 사용자 텍스트 메모를 반환."""
        image_urls: list[str] = []
        text_notes: list[str] = []
        cursor = None

        while True:
            kwargs: dict[str, Any] = {"block_id": page_id}
            if cursor:
                kwargs["start_cursor"] = cursor

            response = self.client.blocks.children.list(**kwargs)

            for block in response.get("results", []):
                btype = block["type"]

                if btype == "image":
                    img = block["image"]
                    if img["type"] == "file":
                        image_urls.append(img["file"]["url"])
                    elif img["type"] == "external":
                        image_urls.append(img["external"]["url"])

                # 사용자가 직접 입력한 텍스트 블록 수집
                elif btype in ("paragraph", "bulleted_list_item", "numbered_list_item", "quote"):
                    rich_text = block.get(btype, {}).get("rich_text", [])
                    text = "".join(t.get("plain_text", "") for t in rich_text).strip()
                    if text:
                        text_notes.append(text)

            if not response.get("has_more"):
                break
            cursor = response["next_cursor"]

        return {"image_urls": image_urls, "text_notes": text_notes}

    def get_attendance_stats(self, reference_date: date) -> dict:
        """스트릭(연속 출석일)과 이번 달 출석률을 계산해 반환."""
        # 전체 출석 항목 조회 (날짜 내림차순)
        response = self.client.databases.query(
            database_id=config.DAILY_DB_ID,
            filter={"property": config.DAILY_PROP_ATTENDANCE, "checkbox": {"equals": True}},
            sorts=[{"property": config.DAILY_PROP_DATE, "direction": "descending"}],
        )
        attended_pages = response.get("results", [])

        # 출석한 날짜 집합
        attended_dates: set[date] = set()
        for page in attended_pages:
            date_val = page["properties"].get(config.DAILY_PROP_DATE, {}).get("date")
            if date_val and date_val.get("start"):
                attended_dates.add(date.fromisoformat(date_val["start"]))

        # ── 스트릭 계산 ───────────────────────────────────────────────────
        # reference_date 기준으로 가장 최근 출석일부터 연속 체크
        streak = 0
        check = reference_date
        from datetime import timedelta
        while check in attended_dates:
            streak += 1
            check -= timedelta(days=1)

        # ── 월별 출석률 ───────────────────────────────────────────────────
        year, month = reference_date.year, reference_date.month
        # 이번 달 전체 항목 수 조회 (출석 여부 무관)
        month_start = date(year, month, 1)
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        month_end = date(year, month, last_day)

        total_resp = self.client.databases.query(
            database_id=config.DAILY_DB_ID,
            filter={
                "and": [
                    {"property": config.DAILY_PROP_DATE, "date": {"on_or_after": month_start.isoformat()}},
                    {"property": config.DAILY_PROP_DATE, "date": {"on_or_before": month_end.isoformat()}},
                ]
            },
        )
        total_days = len(total_resp.get("results", []))
        monthly_attended = sum(
            1 for d in attended_dates
            if d.year == year and d.month == month
        )
        rate = round(monthly_attended / total_days * 100) if total_days > 0 else 0

        return {
            "streak": streak,
            "monthly_attended": monthly_attended,
            "monthly_total": total_days,
            "monthly_rate": rate,
            "month_label": f"{year}년 {month}월",
        }

    def update_daily_page(
        self,
        page_id: str,
        keywords: list[str],
        entry_date: date | None = None,
        day_of_week: str | None = None,
    ) -> None:
        """일별 페이지의 날짜·요일·키워드·출석/AI 완료 체크박스를 업데이트한다."""
        properties: dict[str, Any] = {
            config.DAILY_PROP_KEYWORDS: {
                "multi_select": [{"name": kw} for kw in keywords]
            },
            config.DAILY_PROP_AI_DONE: {"checkbox": True},
            config.DAILY_PROP_ATTENDANCE: {"checkbox": True},
        }
        if entry_date:
            properties[config.DAILY_PROP_DATE] = {"date": {"start": entry_date.isoformat()}}
        if day_of_week:
            properties[config.DAILY_PROP_DAY] = {"select": {"name": day_of_week}}
        self.client.pages.update(page_id=page_id, properties=properties)

    # ── 주간 정리 DB ───────────────────────────────────────────────────────

    def create_weekly_summary(
        self,
        week_label: str,
        period_start: date,
        period_end: date,
        attendance_count: int,
        daily_analyses: list[dict],
        insights: dict,
        stats: dict | None = None,
        quiz: list[dict] | None = None,
    ) -> str:
        """주간 정리 DB에 새 페이지를 생성하고 page_id 반환."""
        keywords = insights.get("keywords", [])
        properties: dict[str, Any] = {
            "제목": {"title": [{"text": {"content": week_label}}]},
            config.WEEKLY_PROP_PERIOD: {
                "date": {
                    "start": period_start.isoformat(),
                    "end": period_end.isoformat(),
                }
            },
            config.WEEKLY_PROP_KEYWORDS: {
                "multi_select": [{"name": kw} for kw in keywords]
            },
            config.WEEKLY_PROP_ATTENDANCE_COUNT: {"number": attendance_count},
            config.WEEKLY_PROP_DONE: {"checkbox": True},
        }

        response = self.client.pages.create(
            parent={"database_id": config.WEEKLY_DB_ID},
            properties=properties,
        )
        page_id: str = response["id"]

        # 페이지 본문 작성
        blocks = self._build_weekly_blocks(daily_analyses, insights, stats, quiz)
        # Notion API는 한 번에 최대 100개 블록만 허용
        for i in range(0, len(blocks), 100):
            self.client.blocks.children.append(
                block_id=page_id, children=blocks[i : i + 100]
            )
            if i + 100 < len(blocks):
                time.sleep(0.3)

        return page_id

    def _build_weekly_blocks(self, daily_analyses: list[dict], insights: dict, stats: dict | None = None, quiz: list[dict] | None = None) -> list[dict]:
        def h1(text: str) -> dict:
            return {
                "type": "heading_1",
                "heading_1": {"rich_text": [{"type": "text", "text": {"content": text}}]},
            }

        def h2(text: str) -> dict:
            return {
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]},
            }

        def h3(text: str) -> dict:
            return {
                "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": text}}]},
            }

        def paragraph(text: str) -> dict:
            return {
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": text or "—"}}]},
            }

        def bullet(text: str) -> dict:
            return {
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]},
            }

        def divider() -> dict:
            return {"type": "divider", "divider": {}}

        def callout(text: str, emoji: str) -> dict:
            return {
                "type": "callout",
                "callout": {
                    "rich_text": [{"type": "text", "text": {"content": text}}],
                    "icon": {"type": "emoji", "emoji": emoji},
                    "color": "gray_background",
                },
            }

        blocks: list[dict] = []

        # ── 0. 스트릭 & 출석률 ─────────────────────────────────────────────
        if stats:
            streak = stats.get("streak", 0)
            streak_fire = "🔥" * min(streak, 5) if streak > 0 else "💤"
            blocks.append(callout(
                f"연속 출석  {streak_fire}  {streak}일 연속",
                "🔥",
            ))
            blocks.append(callout(
                f"{stats.get('month_label', '')} 출석률  "
                f"{stats.get('monthly_attended', 0)}/{stats.get('monthly_total', 0)}일  "
                f"({stats.get('monthly_rate', 0)}%)",
                "📅",
            ))
            blocks.append({"type": "divider", "divider": {}})

        # ── 1. 일별 기사 정리 ──────────────────────────────────────────────
        blocks.append(h1("📰 일별 기사 정리"))
        for day in daily_analyses:
            date_label = day.get("date_label", "")
            blocks.append(h2(date_label))
            for story in day.get("stories", []):
                title = story.get("title", "")
                blocks.append(h3(f"▶ {title}"))
                blocks.append(bullet(f"무슨 일: {story.get('what', '')}"))
                blocks.append(bullet(f"원인/배경: {story.get('why', '')}"))
                blocks.append(bullet(f"파급 효과: {story.get('effect', '')}"))
            # 용어 설명 (사용자 메모 기반)
            terms = day.get("term_explanations", [])
            if terms:
                blocks.append(h3("📖 용어 정리"))
                for t in terms:
                    blocks.append(bullet(f"{t.get('term', '')}: {t.get('explanation', '')}"))
            blocks.append(divider())

        # ── 2. 주간 AI 인사이트 ────────────────────────────────────────────
        blocks.append(h1("🤖 주간 AI 인사이트"))
        blocks.append(h2("📊 이번 주 종합 요약"))
        blocks.append(paragraph(insights.get("summary", "")))
        blocks.append(divider())
        blocks.append(h2("🎯 핵심 테마"))
        for theme in insights.get("key_themes", []):
            blocks.append(bullet(theme))
        blocks.append(divider())
        blocks.append(h2("🌐 거시경제 맥락"))
        blocks.append(paragraph(insights.get("macro_context", "")))
        blocks.append(divider())
        blocks.append(h2("💰 투자 인사이트"))
        blocks.append(paragraph(insights.get("investment_insight", "")))
        blocks.append(divider())
        blocks.append(h2("🏠 생활 인사이트"))
        blocks.append(paragraph(insights.get("life_insight", "")))
        blocks.append(divider())
        blocks.append(h2("👀 다음 주 주목 포인트"))
        blocks.append(paragraph(insights.get("next_watch", "")))

        # ── 3. 주간 퀴즈 ───────────────────────────────────────────────────
        if quiz:
            blocks.append(divider())
            blocks.append(h1("❓ 이번 주 퀴즈"))
            for i, q in enumerate(quiz, 1):
                blocks.append(h2(f"Q{i}. {q.get('question', '')}"))
                for choice in q.get("choices", []):
                    blocks.append(bullet(choice))
                # 정답+해설은 토글로 숨김
                blocks.append({
                    "type": "toggle",
                    "toggle": {
                        "rich_text": [{"type": "text", "text": {"content": "▶ 정답 보기"}}],
                        "children": [
                            paragraph(f"정답: {q.get('answer', '')}"),
                            paragraph(f"해설: {q.get('explanation', '')}"),
                        ],
                    },
                })

        return blocks
