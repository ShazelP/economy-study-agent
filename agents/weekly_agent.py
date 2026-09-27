from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, timedelta

from services import site_service
from services.claude_service import ClaudeService
from services.notion_service import NotionService, _parse_date_from_title


def _get_week_range(reference: date | None = None) -> tuple[date, date]:
    """기준일 기준 해당 주 월요일~토요일 반환. 기본값은 오늘."""
    today = reference or date.today()
    monday = today - timedelta(days=today.weekday())
    saturday = monday + timedelta(days=5)
    return monday, saturday


def _week_label(monday: date) -> str:
    iso_year, iso_week, _ = monday.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def run(reference_date: date | None = None, force: bool = False, append: bool = False) -> None:
    notion = NotionService()
    claude = ClaudeService()

    week_start, week_end = _get_week_range(reference_date)
    week_label = _week_label(week_start)

    print(f"\n{'='*50}")
    print(f"주간 에이전트 시작: {week_label} ({week_start} ~ {week_end})")
    print(f"{'='*50}\n")

    # 1. 해당 주 미처리 항목 조회 및 날짜별 그룹화
    entries = notion.get_weekly_entries(week_start, week_end, force=force)
    if force:
        print("⚡ force 모드: AI 첨언 완료 항목 포함해서 재처리\n")
    if append:
        print("➕ append 모드: 누락된 날만 처리 후 기존 주간 정리에 추가\n")

    entries_by_title: dict[str, list] = defaultdict(list)
    for entry in entries:
        title = _get_title(entry)
        entries_by_title[title].append(entry)

    unique_days = len(entries_by_title)
    print(f"처리 대상: {unique_days}일 ({len(entries)}개 항목)\n")

    if not entries:
        print("처리할 항목이 없습니다. (모두 완료되었거나 업로드된 사진이 없음)")
        return

    # 2. 날짜별 분석 (대표 항목 1개로 콘텐츠 분석, 전 참여자 항목에 완료 처리)
    daily_analyses: list[dict] = []
    processed_count = 0

    for title, title_entries in sorted(entries_by_title.items()):
        participant_count = len(title_entries)
        print(f"[{title}] 처리 중... ({participant_count}명 제출)")

        # 이미지는 첫 번째로 찾은 항목에서, 텍스트 메모는 전 참여자 항목에서 통합
        image_urls: list[str] = []
        merged_notes: list[str] = []

        for entry in title_entries:
            content = notion.get_page_content(entry["id"])
            if not image_urls:
                image_urls = content["image_urls"]
            merged_notes.extend(content["text_notes"])

        if not image_urls:
            print(f"  ⚠ 이미지 없음 — 건너뜀\n")
            continue

        # 중복 제거 (순서 유지)
        seen: set[str] = set()
        user_notes: list[str] = []
        for note in merged_notes:
            if note not in seen:
                seen.add(note)
                user_notes.append(note)

        date_str = _parse_date_str(title)
        if user_notes:
            print(f"  참여자 메모 {len(user_notes)}개 통합 ({participant_count}명분)")
        print(f"  이미지 + 웹 검색으로 분석 중...")
        analysis = None
        for attempt in range(3):
            try:
                analysis = claude.analyze_newspaper_image(image_urls[0], date_str, user_notes or None)
                if analysis and analysis.get("stories"):
                    break
                analysis = None
            except Exception as e:
                if attempt < 2:
                    wait = 2 ** (attempt + 1)  # 2초, 4초
                    print(f"  ⚠ {e.__class__.__name__} — {wait}초 후 재시도 ({attempt + 1}/2)...")
                    time.sleep(wait)
                else:
                    print(f"  ⚠ 분석 3회 모두 실패 — 건너뜀\n")
        if not analysis:
            continue

        analysis["date_label"] = title

        entry_date = _parse_date_from_title(title)
        day_of_week = title.split("_")[1] if "_" in title else None
        keywords = analysis.get("keywords", [])

        # 해당 날짜의 모든 참여자 항목에 AI 완료 + 출석 처리
        for entry in title_entries:
            notion.update_daily_page(entry["id"], keywords, entry_date, day_of_week)

        daily_analyses.append(analysis)
        processed_count += 1

        stories_count = len(analysis.get("stories", []))
        print(f"  ✓ 완료 (기사 {stories_count}건, 키워드: {', '.join(keywords)}, 참여자 {participant_count}명)\n")

        time.sleep(1)

    print(f"일별 분석 완료: {processed_count}/{unique_days}일")

    if processed_count == 0:
        print("분석된 항목이 없어 주간 정리를 건너뜁니다.")
        return

    # 3. 분석 결과 검토
    print(f"\n{'─'*50}")
    print("분석 결과 검토 중...")
    issues = _review_analyses(daily_analyses)
    if issues:
        print(f"  → 이슈 {len(issues)}건 발견 (위 항목 확인 후 계속 진행)")
    else:
        print("  → 전체 이상 없음, 주간 정리 생성 진행")
    print(f"{'─'*50}\n")

    insights = None
    quiz = None

    if not append:
        # 4. 주간 인사이트 생성 (503 대비 재시도)
        print("주간 인사이트 생성 중...")
        for attempt in range(3):
            try:
                insights = claude.generate_weekly_insights(week_label, daily_analyses)
                if insights:
                    break
            except Exception as e:
                wait = 2 ** (attempt + 3)  # 8초, 16초
                if attempt < 2:
                    print(f"  ⚠ {e.__class__.__name__} — {wait}초 후 재시도 ({attempt + 1}/2)...")
                    time.sleep(wait)
                else:
                    print(f"  ⚠ 인사이트 생성 3회 모두 실패: {e.__class__.__name__}")
        if not insights:
            print("⚠ 주간 인사이트 생성 실패")
            return

        # 5. 주간 퀴즈 생성 (503 대비 재시도)
        print("주간 퀴즈 생성 중...")
        for attempt in range(3):
            try:
                quiz = claude.generate_weekly_quiz(week_label, daily_analyses)
                if quiz:
                    break
            except Exception as e:
                wait = 2 ** (attempt + 3)  # 8초, 16초
                if attempt < 2:
                    print(f"  ⚠ {e.__class__.__name__} — {wait}초 후 재시도 ({attempt + 1}/2)...")
                    time.sleep(wait)
                else:
                    print(f"  ⚠ 퀴즈 생성 3회 모두 실패 — 퀴즈 없이 저장")
        if quiz:
            print(f"  ✓ 퀴즈 {len(quiz)}문제 생성 완료")
        else:
            print("  ⚠ 퀴즈 없이 저장")

    # 6. 참여자별 출석 통계 계산
    print("참여자별 출석 통계 계산 중...")
    participant_stats = notion.get_all_participant_stats(week_end)
    for ps in participant_stats:
        streak = ps["streak"]
        print(
            f"  {ps['name']}: {ps['month_label']} "
            f"{ps['monthly_attended']}/{ps['monthly_total']}일 ({ps['monthly_rate']}%) "
            f"| {'🔥' if streak > 0 else '💤'} {streak}일 연속"
        )

    # 7. 저장: append 모드면 기존 페이지에 추가, 아니면 새 페이지 생성
    if append:
        print("기존 주간 정리 페이지에 추가 중...")
        existing_id = notion.find_weekly_summary(week_label)
        if existing_id:
            notion.append_daily_to_weekly(existing_id, daily_analyses, participant_stats)
            print(f"\n{'='*50}")
            print(f"추가 완료! 기존 페이지에 {processed_count}일치 분석 추가됨 (ID: {existing_id})")
            print(f"{'='*50}\n")
        else:
            print("⚠ 기존 주간 정리 페이지를 찾지 못했습니다. 새 페이지를 생성합니다.")
            append = False

    if not append:
        print("주간 정리 DB에 저장 중...")
        page_id = notion.create_weekly_summary(
            week_label=week_label,
            period_start=week_start,
            period_end=week_end,
            attendance_count=processed_count,
            daily_analyses=daily_analyses,
            insights=insights,
            participant_stats=participant_stats,
            quiz=quiz or None,
        )
        print(f"\n{'='*50}")
        print(f"주간 에이전트 완료! 주간 정리 페이지 생성됨 (ID: {page_id})")
        print(f"{'='*50}\n")

        print("웹사이트 페이지 생성 중 (docs/)...")
        site_service.build_and_save(
            week_label=week_label,
            week_start=week_start,
            week_end=week_end,
            daily_analyses=daily_analyses,
            insights=insights,
            quiz=quiz,
        )
        print("  ✓ docs/index.html, docs/weeks/ 갱신 완료 — 확인 후 'python main.py publish'로 배포하세요.\n")


def run_quiz_only(reference_date: date | None = None) -> None:
    """기존 주간 정리 페이지 내용을 읽어 퀴즈를 생성하고 추가."""
    notion = NotionService()
    claude = ClaudeService()

    week_start, week_end = _get_week_range(reference_date)
    week_label = _week_label(week_start)

    print(f"\n{'='*50}")
    print(f"퀴즈 생성: {week_label}")
    print(f"{'='*50}\n")

    existing_id = notion.find_weekly_summary(week_label)
    if not existing_id:
        print("⚠ 주간 정리 페이지를 찾을 수 없습니다.")
        return

    print("주간 정리 페이지 내용 읽는 중...")
    content_text = notion.get_weekly_summary_content(existing_id)
    if not content_text.strip():
        print("⚠ 페이지 내용을 읽을 수 없습니다.")
        return
    print(f"  ✓ 내용 읽기 완료 ({len(content_text)}자)")

    print("퀴즈 생성 중...")
    quiz = None
    for attempt in range(3):
        try:
            quiz = claude.generate_quiz_from_page_content(week_label, content_text)
            if quiz:
                break
        except Exception as e:
            wait = 2 ** (attempt + 3)
            if attempt < 2:
                print(f"  ⚠ {e.__class__.__name__}: {str(e)[:120]} — {wait}초 후 재시도 ({attempt + 1}/2)...")
                time.sleep(wait)
            else:
                print(f"  ⚠ 퀴즈 생성 3회 모두 실패: {e.__class__.__name__}: {str(e)[:120]}")

    if not quiz:
        print("⚠ 퀴즈 생성 실패")
        return

    print(f"  ✓ 퀴즈 {len(quiz)}문제 생성 완료")
    print("기존 주간 정리 페이지에 추가 중...")
    notion.append_quiz_to_weekly(existing_id, quiz)

    print(f"\n{'='*50}")
    print(f"퀴즈 추가 완료! (ID: {existing_id})")
    print(f"{'='*50}\n")


_HEDGE_WORDS = ("불분명", "추정", "정확한 의미", "판단하기 어렵", "알려지지 않")


def _review_analyses(daily_analyses: list[dict]) -> list[dict]:
    """일별 분석 결과 품질 검토. 이슈 목록 반환."""
    issues = []
    for a in daily_analyses:
        label = a.get("date_label", "?")
        stories = a.get("stories", [])
        keywords = a.get("keywords", [])
        terms = a.get("term_explanations", [])
        day_issues = []

        if not stories:
            day_issues.append("기사 없음")
        else:
            for s in stories:
                for field in ("what", "why", "effect"):
                    if len(s.get(field, "")) < 20:
                        day_issues.append(f"'{s.get('title', '?')}' {field} 내용 부족")
                        break

        if not keywords:
            day_issues.append("키워드 없음")

        for t in terms:
            explanation = t.get("explanation", "")
            if any(hedge in explanation for hedge in _HEDGE_WORDS):
                day_issues.append(f"용어 '{t.get('term', '?')}' 설명이 불확실함 — 사진에 실제 ?표시가 있었는지 확인 필요")

        if day_issues:
            print(f"  ⚠ [{label}]: {', '.join(day_issues)}")
            issues.append({"date": label, "issues": day_issues})
        else:
            print(f"  ✓ [{label}]: 정상")

    return issues


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
