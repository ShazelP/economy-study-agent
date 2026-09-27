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
                f"【사용자 메모】\n{notes_text}\n\n"
                "→ 헤드라인·주요 내용 메모가 있으면 stories 분석의 핵심 근거로 활용하세요.\n"
                "→ ?(물음표) 표시된 용어나 궁금한 점은 term_explanations에 반드시 포함해서 설명해주세요."
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

        result = self._parse_json_response(response.text)
        self._attach_source_urls(response, result.get("stories", []))
        return result

    def _attach_source_urls(self, response, stories: list[dict]) -> None:
        """grounding_supports의 문자 오프셋을 이용해 각 story의 'what' 텍스트가
        raw 응답 텍스트 어디서 나왔는지 찾고, 겹치는 검색 출처가 있으면 story['source_url']에 매칭.
        확신 있는 매칭이 없으면 조용히 건너뜀 (틀린 링크보다 링크 없는 게 낫다)."""
        candidates = getattr(response, "candidates", None)
        if not candidates:
            return
        grounding_metadata = getattr(candidates[0], "grounding_metadata", None)
        if not grounding_metadata:
            return
        chunks = grounding_metadata.grounding_chunks or []
        supports = grounding_metadata.grounding_supports or []
        if not chunks or not supports:
            return

        raw_text = response.text
        for story in stories:
            what = story.get("what", "")
            if not what:
                continue
            needle = json.dumps(what, ensure_ascii=False)[1:-1]
            start = raw_text.find(needle)
            if start == -1:
                continue
            end = start + len(needle)

            for support in supports:
                seg = support.segment
                if seg is None:
                    continue
                if seg.start_index is None or seg.end_index is None:
                    continue
                if seg.start_index < end and seg.end_index > start:
                    indices = support.grounding_chunk_indices or []
                    if not indices:
                        continue
                    chunk = chunks[indices[0]]
                    if chunk.web and chunk.web.uri:
                        story["source_url"] = chunk.web.uri
                    break

    def generate_quiz_from_page_content(self, week_label: str, content_text: str) -> list[dict]:
        """주간 정리 페이지 텍스트를 직접 활용해 퀴즈 생성."""
        prompt = config.WEEKLY_QUIZ_PROMPT.replace(
            "{{week_label}}", week_label
        ).replace("{{daily_summaries}}", content_text)

        response = _client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=config.SYSTEM_PROMPT,
                max_output_tokens=8192,
                temperature=0.5,
                response_mime_type="application/json",
            ),
        )
        result = self._parse_json_response(response.text)
        return result if isinstance(result, list) else []

    def generate_weekly_quiz(
        self, week_label: str, daily_analyses: list[dict]
    ) -> list[dict]:
        """주간 내용 기반으로 퀴즈 3문제 생성."""
        daily_summaries = self._format_daily_summaries(daily_analyses)

        prompt = config.WEEKLY_QUIZ_PROMPT.replace(
            "{{week_label}}", week_label
        ).replace("{{daily_summaries}}", daily_summaries)

        response = _client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=config.SYSTEM_PROMPT,
                max_output_tokens=8192,
                temperature=0.5,
                response_mime_type="application/json",
            ),
        )

        result = self._parse_json_response(response.text)
        # 응답이 list이면 그대로, dict이면 빈 리스트
        return result if isinstance(result, list) else []

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
                tools=[_SEARCH_TOOL],
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
            extracted = self._extract_json_object(cleaned)
            if extracted:
                try:
                    return json.loads(extracted)
                except json.JSONDecodeError:
                    pass
        print(f"[경고] JSON 파싱 실패. 원본 응답:\n{text[:300]}")
        return {}

    def _extract_json_object(self, text: str) -> str | None:
        """첫 번째 { 부터 매칭되는 } 까지 깊이 기반으로 추출."""
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

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
