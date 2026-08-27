"""Command-line interface for ReproSeed."""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from .analyzer import ReproducibilityAnalyzer
from .source import materialize_source


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reproseed",
        description="GitHub 연구 저장소와 Jupyter Notebook의 재현 가능성을 검사합니다.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="저장소 또는 Notebook을 분석합니다.")
    analyze.add_argument("source", help="로컬 경로, owner/repository 또는 GitHub URL")
    analyze.add_argument("--json", action="store_true", help="JSON 결과를 출력합니다.")
    analyze.add_argument("--generate", action="store_true", help="환경 파일 초안을 저장합니다.")
    analyze.add_argument(
        "--output-dir",
        default="reproducibility",
        help="생성 파일 디렉터리(기본값: reproducibility)",
    )

    serve = subparsers.add_parser("serve", help="웹 UI를 실행합니다.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        return _serve(args.host, args.port)
    try:
        with materialize_source(args.source) as (path, label):
            report = ReproducibilityAnalyzer().analyze(path, display_source=label)
    except (FileNotFoundError, ValueError) as error:
        print("오류: {}".format(error), file=sys.stderr)
        return 2

    if args.generate:
        output = Path(args.output_dir)
        output.mkdir(parents=True, exist_ok=True)
        for name, content in report.generated_files.items():
            (output / name).write_text(content, encoding="utf-8")

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_report(report, generated=args.output_dir if args.generate else None)
    return 0


def _print_report(report, generated: Optional[str]) -> None:
    print("\nReproSeed Reproducibility Score: {}/100 ({})".format(report.score, report.grade))
    print("Source: {}".format(report.source))
    print("Scanned: {files_scanned} files · {notebooks} notebooks · {code_cells} code cells".format(**report.stats))
    if report.findings:
        print("\nFindings")
        for finding in report.findings:
            location = ""
            if finding.file:
                location = " [{}{}]".format(
                    finding.file, ":{}".format(finding.line) if finding.line else ""
                )
            print("- [{}] {} (-{}){}".format(finding.severity.upper(), finding.title, finding.penalty, location))
            print("  {}".format(finding.message))
            print("  → {}".format(finding.remediation))
    else:
        print("\n발견된 재현성 위험이 없습니다.")
    if generated:
        print("\n환경 파일 초안: {}".format(Path(generated).resolve()))


def _serve(host: str, port: int) -> int:
    try:
        import uvicorn
    except ImportError:
        print("웹 UI 의존성이 없습니다. pip install -e '.[web]'을 실행하세요.", file=sys.stderr)
        return 2
    uvicorn.run("reproseed.webapp:app", host=host, port=port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

