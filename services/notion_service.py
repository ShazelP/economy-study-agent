from __future__ import annotations

import calendar
import time
from datetime import date, timedelta
from typing import Any

from notion_client import Client

import config


def _motivational_msg(rate: int) -> str:
    if rate >= 90:
        return "이달 완주 확정! 정말 대단해요 🏆"
    if rate >= 70:
        return "이 페이스라면 이번 달도 완주할 수 있어요 💪"
    if rate >= 50:
        return "절반 넘겼어요! 조금만 더 화이팅 🙌"
    if rate >= 30:
        return "다음 주엔 더 자주 참여해 봐요!"
    return "함께하면 더 즐거워요, 얼굴 보여주세요 😊"


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

    def get_weekly_entries(self, week_start: date, week_end: date, force: bool = False) -> list[dict]:
        """해당 주 항목을 반환. force=True 이면 AI 첨언 완료 여부 무시."""
        kwargs: dict[str, Any] = {
            "database_id": config.DAILY_DB_ID,
            "sorts": [{"property": "제목", "direction": "ascending"}],
        }
        if not force:
            kwargs["filter"] = {
                "property": config.DAILY_PROP_AI_DONE,
                "checkbox": {"equals": False},
            }
        response = self.client.databases.query(**kwargs)
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

                elif btype in ("paragraph", "bulleted_list_item", "numbered_list_item", "quote"):
                    rich_text = block.get(btype, {}).get("rich_text", [])
                    text = "".join(t.get("plain_text", "") for t in rich_text).strip()
                    if text:
                        text_notes.append(text)

            if not response.get("has_more"):
                break
            cursor = response["next_cursor"]

        return {"image_urls": image_urls, "text_notes": text_notes}

    def get_attendance_stats(self, reference_date: date, user_id: str | None = None) -> dict:
        """스트릭(연속 출석일)과 이번 달 출석률을 계산해 반환. user_id 지정 시 해당 참여자 기준."""
        attend_filter: dict[str, Any] = {
            "property": config.DAILY_PROP_ATTENDANCE,
            "checkbox": {"equals": True},
        }
        if user_id:
            attend_filter = {
                "and": [
                    attend_filter,
                    {"property": "작성자", "people": {"contains": user_id}},
                ]
            }

        response = self.client.databases.query(
            database_id=config.DAILY_DB_ID,
            filter=attend_filter,
            sorts=[{"property": config.DAILY_PROP_DATE, "direction": "descending"}],
        )
        attended_pages = response.get("results", [])

        attended_dates: set[date] = set()
        for page in attended_pages:
            date_val = page["properties"].get(config.DAILY_PROP_DATE, {}).get("date")
            if date_val and date_val.get("start"):
                attended_dates.add(date.fromisoformat(date_val["start"]))
            else:
                # 날짜 속성이 없으면 제목에서 파싱 (속성 미설정 항목 대비)
                title = _get_entry_title(page)
                parsed = _parse_date_from_title(title)
                if parsed:
                    attended_dates.add(parsed)

        # 스트릭 계산
        streak = 0
        check = reference_date
        while check in attended_dates:
            streak += 1
            check -= timedelta(days=1)

        # 월별 출석률
        year, month = reference_date.year, reference_date.month
        month_start = date(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        month_end = date(year, month, last_day)

        # 분모: reference_date까지 이번 달의 일요일 제외 날수 (DB 무관, 순수 달력 계산)
        effective_end = min(month_end, reference_date)
        total_days = sum(
            1 for i in range((effective_end - month_start).days + 1)
            if (month_start + timedelta(days=i)).weekday() != 6  # 일요일(6) 제외
        )

        monthly_attended = sum(
            1 for d in attended_dates
            if d.year == year and d.month == month and d <= reference_date
        )
        rate = round(monthly_attended / total_days * 100) if total_days > 0 else 0

        return {
            "streak": streak,
            "monthly_attended": monthly_attended,
            "monthly_total": total_days,
            "monthly_rate": rate,
            "month_label": f"{year}년 {month}월",
        }

    def get_all_participant_stats(self, reference_date: date) -> list[dict]:
        """DB 전체 항목을 스캔해 참여자를 자동 발견하고 각자의 출석 통계를 반환."""
        response = self.client.databases.query(database_id=config.DAILY_DB_ID)
        participants: dict[str, str] = {}  # user_id → name
        for page in response.get("results", []):
            people = page["properties"].get("작성자", {}).get("people", [])
            for person in people:
                uid = person["id"]
                if uid not in participants:
                    participants[uid] = person.get("name", f"참여자{len(participants) + 1}")

        result = []
        for uid, name in participants.items():
            stats = self.get_attendance_stats(reference_date, user_id=uid)
            stats["name"] = name
            stats["user_id"] = uid
            result.append(stats)
        return result

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

    def get_weekly_summary_content(self, page_id: str) -> str:
        """주간 정리 페이지의 텍스트 블록을 모두 읽어 문자열로 반환."""
        text_types = {
            "heading_1", "heading_2", "heading_3",
            "paragraph", "bulleted_list_item", "numbered_list_item", "callout",
        }
        lines: list[str] = []
        cursor = None

        while True:
            kwargs: dict[str, Any] = {"block_id": page_id}
            if cursor:
                kwargs["start_cursor"] = cursor
            response = self.client.blocks.children.list(**kwargs)

            for block in response.get("results", []):
                btype = block["type"]
                if btype not in text_types:
                    continue
                rich_text = block.get(btype, {}).get("rich_text", [])
                text = "".join(t.get("plain_text", "") for t in rich_text).strip()
                if text:
                    lines.append(text)

            if not response.get("has_more"):
                break
            cursor = response["next_cursor"]

        return "\n".join(lines)

    def append_quiz_to_weekly(self, page_id: str, quiz: list[dict]) -> None:
        """기존 주간 정리 페이지에 퀴즈 섹션을 추가."""
        def h1(text: str) -> dict:
            return {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": text}}]}}

        def h2(text: str) -> dict:
            return {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]}}

        def bullet(text: str) -> dict:
            return {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]}}

        def paragraph(text: str) -> dict:
            return {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": text or "—"}}]}}

        blocks: list[dict] = [
            {"type": "divider", "divider": {}},
            h1("❓ 이번 주 퀴즈"),
        ]
        for i, q in enumerate(quiz, 1):
            blocks.append(h2(f"Q{i}. {q.get('question', '')}"))
            for choice in q.get("choices", []):
                blocks.append(bullet(choice))
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

        for i in range(0, len(blocks), 100):
            self.client.blocks.children.append(block_id=page_id, children=blocks[i : i + 100])

    def find_weekly_summary(self, week_label: str) -> str | None:
        """주간 정리 DB에서 해당 주차 페이지 ID 반환. 없으면 None."""
        response = self.client.databases.query(
            database_id=config.WEEKLY_DB_ID,
            filter={"property": "제목", "title": {"equals": week_label}},
        )
        results = response.get("results", [])
        return results[0]["id"] if results else None

    def append_daily_to_weekly(
        self,
        page_id: str,
        daily_analyses: list[dict],
        participant_stats: list[dict] | None = None,
    ) -> None:
        """기존 주간 정리 페이지에 누락된 일별 분석을 추가하고 출석 횟수를 갱신."""
        blocks = self._build_additional_daily_blocks(daily_analyses, participant_stats)
        for i in range(0, len(blocks), 100):
            self.client.blocks.children.append(block_id=page_id, children=blocks[i : i + 100])
            if i + 100 < len(blocks):
                time.sleep(0.3)

        # 출석 횟수 누적
        page = self.client.pages.retrieve(page_id=page_id)
        current = page["properties"].get(config.WEEKLY_PROP_ATTENDANCE_COUNT, {}).get("number") or 0
        self.client.pages.update(
            page_id=page_id,
            properties={config.WEEKLY_PROP_ATTENDANCE_COUNT: {"number": current + len(daily_analyses)}},
        )

    def _build_additional_daily_blocks(
        self,
        daily_analyses: list[dict],
        participant_stats: list[dict] | None = None,
    ) -> list[dict]:
        """추가 일별 분석 블록."""
        def h2(text: str) -> dict:
            return {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]}}

        def h3(text: str) -> dict:
            return {"type": "heading_3", "heading_3": {"rich_text": [{"type": "text", "text": {"content": text}}]}}

        def bullet(text: str) -> dict:
            return {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]}}

        def divider() -> dict:
            return {"type": "divider", "divider": {}}

        def callout(text: str, emoji: str, color: str = "blue_background") -> dict:
            return {"type": "callout", "callout": {
                "rich_text": [{"type": "text", "text": {"content": text}}],
                "icon": {"type": "emoji", "emoji": emoji},
                "color": color,
            }}

        labels = ", ".join(d.get("date_label", "") for d in daily_analyses)
        blocks: list[dict] = [
            divider(),
            callout(f"📎 추가 분석 — {labels} (초기 실행 시 503 오류로 누락됐던 날)", "📎"),
        ]

        for day in daily_analyses:
            blocks.append(h2(day.get("date_label", "")))
            for story in day.get("stories", []):
                blocks.append(h3(f"▶ {story.get('title', '')}"))
                blocks.append(bullet(f"무슨 일: {story.get('what', '')}"))
                blocks.append(bullet(f"원인/배경: {story.get('why', '')}"))
                blocks.append(bullet(f"파급 효과: {story.get('effect', '')}"))
            terms = day.get("term_explanations", [])
            if terms:
                blocks.append(h3("📖 용어 정리"))
                for t in terms:
                    blocks.append(bullet(f"{t.get('term', '')}: {t.get('explanation', '')}"))
            blocks.append(divider())

        if participant_stats:
            medals = ["🥇", "🥈", "🥉"]
            sorted_stats = sorted(participant_stats, key=lambda p: p.get("monthly_rate", 0), reverse=True)
            blocks.append(callout("👥 업데이트된 참여자 출석 현황", "👥", "gray_background"))
            for i, p in enumerate(sorted_stats):
                medal = medals[i] if i < len(medals) else "🏅"
                streak = p.get("streak", 0)
                streak_str = f"🔥 {streak}일 연속" if streak > 0 else "💤 연속 없음"
                rate = p.get("monthly_rate", 0)
                msg = _motivational_msg(rate)
                line = (
                    f"{medal} {p['name']}  |  "
                    f"{p.get('month_label', '')} {p.get('monthly_attended', 0)}/{p.get('monthly_total', 0)}일 ({rate}%)  |  "
                    f"{streak_str}  |  {msg}"
                )
                blocks.append(callout(line, medal, "gray_background"))

        return blocks

    def create_weekly_summary(
        self,
        week_label: str,
        period_start: date,
        period_end: date,
        attendance_count: int,
        daily_analyses: list[dict],
        insights: dict,
        participant_stats: list[dict] | None = None,
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

        blocks = self._build_weekly_blocks(daily_analyses, insights, participant_stats, quiz)
        for i in range(0, len(blocks), 100):
            self.client.blocks.children.append(
                block_id=page_id, children=blocks[i : i + 100]
            )
            if i + 100 < len(blocks):
                time.sleep(0.3)

        return page_id

    def _build_weekly_blocks(
        self,
        daily_analyses: list[dict],
        insights: dict,
        participant_stats: list[dict] | None = None,
        quiz: list[dict] | None = None,
    ) -> list[dict]:
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

        # ── 0. 참여자별 출석 현황 ──────────────────────────────────────────
        if participant_stats:
            blocks.append(h1("👥 이번 달 참여자 출석"))
            medals = ["🥇", "🥈", "🥉"]
            sorted_stats = sorted(participant_stats, key=lambda p: p.get("monthly_rate", 0), reverse=True)
            for i, p in enumerate(sorted_stats):
                medal = medals[i] if i < len(medals) else "🏅"
                streak = p.get("streak", 0)
                streak_str = f"🔥 {streak}일 연속" if streak > 0 else "💤 연속 없음"
                rate = p.get("monthly_rate", 0)
                msg = _motivational_msg(rate)
                line = (
                    f"{medal} {p['name']}  |  "
                    f"{p.get('month_label', '')} {p.get('monthly_attended', 0)}/{p.get('monthly_total', 0)}일 ({rate}%)  |  "
                    f"{streak_str}  |  {msg}"
                )
                blocks.append(callout(line, medal))
            blocks.append(divider())

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
