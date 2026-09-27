#!/usr/bin/env python3
"""경제 공부 에이전트 CLI 진입점.

사용법:
    python main.py weekly              # 이번 주 처리
    python main.py weekly 2026-05-24   # 특정 날짜가 속한 주 처리
    python main.py publish             # docs/ 웹사이트 변경사항을 git push로 배포
"""
import subprocess
import sys
from datetime import date


def main() -> None:
    args = sys.argv[1:]

    if not args:
        print("사용법: python main.py weekly [YYYY-MM-DD] [--force] [--append] [--quiz]")
        sys.exit(1)

    command = args[0].lower()

    if command == "weekly":
        reference_date: date | None = None
        force = "--force" in args
        append = "--append" in args
        quiz_only = "--quiz" in args
        date_args = [a for a in args[1:] if not a.startswith("--")]
        if date_args:
            try:
                reference_date = date.fromisoformat(date_args[0])
            except ValueError:
                print(f"날짜 형식 오류: '{date_args[0]}' (올바른 형식: YYYY-MM-DD)")
                sys.exit(1)

        if quiz_only:
            from agents.weekly_agent import run_quiz_only
            run_quiz_only(reference_date)
        else:
            from agents.weekly_agent import run
            run(reference_date, force=force, append=append)

    elif command == "publish":
        result = subprocess.run(["git", "status", "--porcelain", "docs"], capture_output=True, text=True)
        if not result.stdout.strip():
            print("docs/ 변경사항이 없습니다. 배포할 내용이 없습니다.")
            sys.exit(0)
        print("docs/ 변경사항:")
        print(result.stdout)
        subprocess.run(["git", "add", "docs"], check=True)
        subprocess.run(["git", "commit", "-m", "docs: 주간 정리 웹사이트 갱신"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("배포 완료.")

    else:
        print(f"알 수 없는 명령어: '{command}'")
        print("사용 가능한 명령어: weekly, publish")
        sys.exit(1)


if __name__ == "__main__":
    main()
