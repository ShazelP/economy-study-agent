from __future__ import annotations

import time
from datetime import date
from typing import Any

from notion_client import Client

import config


class NotionService:
    def __init__(self):
        self.client = Client(auth=config.NOTION_TOKEN)

    # ── 일일 학습 DB ───────────────────────────────────────────────────────

    def get_weekly_entries(self, week_start: date, week_end: date) -> list[dict]:
        """주간 날짜 범위에 해당하는 일일 학습 항목 조회 (AI 첨언 미완료 항목만)."""
        response = self.client.databases.query(
            database_id=config.DAILY_DB_ID,
            filter={
                "and": [
                    {
                        "property": config.DAILY_PROP_DATE,
                        "date": {"on_or_after": week_start.isoformat()},
                    },
                    {
                        "property": config.DAILY_PROP_DATE,
                        "date": {"on_or_before": week_end.isoformat()},
                    },
                    {
                        "property": config.DAILY_PROP_AI_DONE,
                        "checkbox": {"equals": False},
                    },
                ]
            },
            sorts=[{"property": config.DAILY_PROP_DATE, "direction": "ascending"}],
        )
        return response.get("results", [])

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

    def update_daily_page(self, page_id: str, keywords: list[str]) -> None:
        """일별 페이지의 키워드, 출석/AI 완료 체크박스만 업데이트한다. 본문은 건드리지 않음."""
        self.client.pages.update(
            page_id=page_id,
            properties={
                config.DAILY_PROP_KEYWORDS: {
                    "multi_select": [{"name": kw} for kw in keywords]
                },
                config.DAILY_PROP_AI_DONE: {"checkbox": True},
                config.DAILY_PROP_ATTENDANCE: {"checkbox": True},
            },
        )

    # ── 주간 정리 DB ───────────────────────────────────────────────────────

    def create_weekly_summary(
        self,
        week_label: str,
        period_start: date,
        period_end: date,
        attendance_count: int,
        daily_analyses: list[dict],
        insights: dict,
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
        blocks = self._build_weekly_blocks(daily_analyses, insights)
        # Notion API는 한 번에 최대 100개 블록만 허용
        for i in range(0, len(blocks), 100):
            self.client.blocks.children.append(
                block_id=page_id, children=blocks[i : i + 100]
            )
            if i + 100 < len(blocks):
                time.sleep(0.3)

        return page_id

    def _build_weekly_blocks(self, daily_analyses: list[dict], insights: dict) -> list[dict]:
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

        blocks: list[dict] = []

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

        return blocks
