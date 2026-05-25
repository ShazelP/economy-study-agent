#!/usr/bin/env python3
"""경제 공부 에이전트 CLI 진입점.

사용법:
    python main.py weekly              # 이번 주 처리
    python main.py weekly 2026-05-24   # 특정 날짜가 속한 주 처리
"""
import sys
from datetime import date


def main() -> None:
    args = sys.argv[1:]

    if not args:
        print("사용법: python main.py weekly [YYYY-MM-DD]")
        sys.exit(1)

    command = args[0].lower()

    if command == "weekly":
        reference_date: date | None = None
        if len(args) >= 2:
            try:
                reference_date = date.fromisoformat(args[1])
            except ValueError:
                print(f"날짜 형식 오류: '{args[1]}' (올바른 형식: YYYY-MM-DD)")
                sys.exit(1)

        from agents.weekly_agent import run
        run(reference_date)

    else:
        print(f"알 수 없는 명령어: '{command}'")
        print("사용 가능한 명령어: weekly")
        sys.exit(1)


if __name__ == "__main__":
    main()
