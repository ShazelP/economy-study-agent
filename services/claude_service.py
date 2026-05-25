from __future__ import annotations

import json
import re

import httpx
from google import genai
from google.genai import types

import config

_client = genai.Client(api_key=config.GEMINI_API_KEY)

# Google Search 도구 (이미지 분석 + 웹 검색 교차 확인용)
_SEARCH_TOOL = types.Tool(google_search=types.GoogleSearch())


class ClaudeService:
    def analyze_newspaper_image(
        self,
        image_url: str,
        date_str: str,
        user_notes: list[str] | None = None,
    ) -> dict:
        """신문 이미지 + Google 검색으로 기사 분석. date_str 예: '2026년 5월 22일'"""
        image_bytes, mime_type = self._download_image(image_url)

        # 사용자 메모 섹션 구성
        if user_notes:
            notes_text = "\n".join(f"- {n}" for n in user_notes)
            user_notes_section = (
                f"사용자가 이 날 페이지에 직접 적어둔 메모 (모르는 용어, 궁금한 점 등):\n{notes_text}\n"
                "→ term_explanations 항목에서 위 용어들을 반드시 포함해서 설명해주세요."
            )
        else:
            user_notes_section = ""

        prompt = (
            config.DAILY_ANALYSIS_PROMPT
            .replace("{{date_str}}", date_str)
            .replace("{{user_notes_section}}", user_notes_section)
        )

        response = _client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                prompt,
            ],
            config=types.GenerateContentConfig(
                system_instruction=config.SYSTEM_PROMPT,
                max_output_tokens=8192,
                temperature=0.3,
                tools=[_SEARCH_TOOL],
            ),
        )

        return self._parse_json_response(response.text)

    def generate_weekly_insights(
        self, week_label: str, daily_analyses: list[dict]
    ) -> dict:
        """일별 분석 결과를 종합해 주간 인사이트 생성."""
        daily_summaries = self._format_daily_summaries(daily_analyses)

        prompt = config.WEEKLY_INSIGHT_PROMPT.replace(
            "{{week_label}}", week_label
        ).replace("{{daily_summaries}}", daily_summaries)

        response = _client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=config.SYSTEM_PROMPT,
                max_output_tokens=8192,
                temperature=0.3,
                response_mime_type="application/json",
            ),
        )

        return self._parse_json_response(response.text)

    # ── 내부 유틸 ──────────────────────────────────────────────────────────

    def _download_image(self, url: str) -> tuple[bytes, str]:
        with httpx.Client(timeout=30, follow_redirects=True) as http:
            resp = http.get(url)
            resp.raise_for_status()

        mime_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        if mime_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
            mime_type = "image/jpeg"

        return resp.content, mime_type

    def _parse_json_response(self, text: str) -> dict:
        cleaned = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
        print(f"[경고] JSON 파싱 실패. 원본 응답:\n{text[:300]}")
        return {}

    def _format_daily_summaries(self, analyses: list[dict]) -> str:
        lines: list[str] = []
        for a in analyses:
            lines.append(f"### {a.get('date_label', '')}")
            for story in a.get("stories", []):
                lines.append(f"#### {story.get('title', '')}")
                lines.append(f"- 무슨 일: {story.get('what', '')}")
                lines.append(f"- 원인: {story.get('why', '')}")
                lines.append(f"- 효과: {story.get('effect', '')}")
            terms = a.get("term_explanations", [])
            if terms:
                lines.append(f"- 용어 메모: {', '.join(t['term'] for t in terms)}")
            lines.append(f"- 키워드: {', '.join(a.get('keywords', []))}")
            lines.append("")
        return "\n".join(lines)
