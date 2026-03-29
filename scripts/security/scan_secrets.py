#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


APP_ID_REGEX = re.compile(r"\b(cli_[a-z0-9]{16})\b")
SECRET_ASSIGN_REGEX = re.compile(
    r"""(?ix)
    \b(?:FEISHU_APP_SECRET|OPENCLAW_FEISHU_APP_SECRET|app_secret)\b
    \s*[:=]\s*
    ["']([A-Za-z0-9_\-]{12,})["']
    """
)

ENV_REF_REGEX = re.compile(
    r"""(?ix)
    \b(?:FEISHU_APP_SECRET|OPENCLAW_FEISHU_APP_SECRET|app_secret)\b
    \s*[:=]\s*
    (?:
      \$[A-Za-z_][A-Za-z0-9_]*
      |\$\{[A-Za-z_][A-Za-z0-9_]*\}
    )
    """
)

ALLOW_VALUE_PARTS = (
    "your_app_secret",
    "your_feishu_app_secret",
    "your_app_id",
    "placeholder",
    "example",
    "xxxx",
    "redacted",
    "cli_xxxxxxxxxxxx",
    "cli_xxxxxxxxxxxxxxxx",
    "cli_redacted_",
    "feishu_secret_redacted",
)

ALLOW_LINE_PARTS = (
    "${{ secrets.",
    "$FEISHU_APP_SECRET",
    "${FEISHU_APP_SECRET}",
    "$OPENCLAW_FEISHU_APP_SECRET",
    "${OPENCLAW_FEISHU_APP_SECRET}",
    "app_secret_env",
    "bot_app_secret_env",
    "app_id_env",
    "bot_app_id_env",
)


@dataclass
class Finding:
    scope: str
    path: str
    line_no: int
    rule: str
    value_masked: str


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=check)


def _mask(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-2:]}"


def _allow_value(value: str) -> bool:
    v = value.lower()
    return any(part in v for part in ALLOW_VALUE_PARTS)


def _allow_line(line: str) -> bool:
    return any(part in line for part in ALLOW_LINE_PARTS)


def _scan_line(line: str, scope: str, path: str, line_no: int) -> list[Finding]:
    findings: list[Finding] = []

    if not _allow_line(line):
        for match in APP_ID_REGEX.finditer(line):
            value = match.group(1)
            if not _allow_value(value):
                findings.append(
                    Finding(
                        scope=scope,
                        path=path,
                        line_no=line_no,
                        rule="hardcoded_feishu_app_id",
                        value_masked=_mask(value),
                    )
                )

    if not ENV_REF_REGEX.search(line):
        for match in SECRET_ASSIGN_REGEX.finditer(line):
            value = match.group(1)
            if not _allow_value(value):
                findings.append(
                    Finding(
                        scope=scope,
                        path=path,
                        line_no=line_no,
                        rule="hardcoded_feishu_app_secret",
                        value_masked=_mask(value),
                    )
                )

    return findings


def _iter_text_lines(content: str):
    for idx, line in enumerate(content.splitlines(), start=1):
        yield idx, line


def _list_staged_files() -> list[str]:
    out = _run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"]).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def _get_staged_file_content(path: str) -> str:
    proc = _run(["git", "show", f":{path}"], check=False)
    if proc.returncode != 0:
        return ""
    return proc.stdout


def _list_repo_files() -> list[str]:
    out = _run(["git", "ls-files"]).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def _scan_staged() -> list[Finding]:
    findings: list[Finding] = []
    for path in _list_staged_files():
        content = _get_staged_file_content(path)
        if not content:
            continue
        for line_no, line in _iter_text_lines(content):
            findings.extend(_scan_line(line, "staged", path, line_no))
    return findings


def _scan_repo() -> list[Finding]:
    findings: list[Finding] = []
    for path in _list_repo_files():
        try:
            content = Path(path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_no, line in _iter_text_lines(content):
            findings.extend(_scan_line(line, "repo", path, line_no))
    return findings


def _scan_history() -> list[Finding]:
    findings: list[Finding] = []
    revs = _run(["git", "rev-list", "--all"]).stdout.splitlines()
    grep_pattern = r"cli_[a-z0-9]{16}|FEISHU_APP_SECRET|OPENCLAW_FEISHU_APP_SECRET|app_secret"
    seen: set[tuple[str, str, int, str, str]] = set()

    for rev in revs:
        proc = _run(["git", "grep", "-nI", "-E", grep_pattern, rev], check=False)
        if proc.returncode not in (0, 1):
            continue
        for raw in proc.stdout.splitlines():
            parts = raw.split(":", 3)
            if len(parts) != 4:
                continue
            _rev, path, line_no_str, line = parts
            try:
                line_no = int(line_no_str)
            except ValueError:
                continue
            hit_list = _scan_line(line, rev[:12], path, line_no)
            for hit in hit_list:
                key = (hit.scope, hit.path, hit.line_no, hit.rule, hit.value_masked)
                if key not in seen:
                    seen.add(key)
                    findings.append(hit)
    return findings


def _print_findings(findings: list[Finding]) -> None:
    print("Secret scan found potential leaks:\n")
    for item in findings:
        print(
            f"- [{item.scope}] {item.path}:{item.line_no} "
            f"{item.rule} value={item.value_masked}"
        )
    print("\nFix or redact these values before commit/push.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan repo for hardcoded Feishu credentials.")
    parser.add_argument(
        "--mode",
        choices=("staged", "repo", "history"),
        required=True,
        help="staged: pre-commit; repo: current files; history: all commits",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.mode == "staged":
        findings = _scan_staged()
    elif args.mode == "repo":
        findings = _scan_repo()
    else:
        findings = _scan_history()

    if findings:
        _print_findings(findings)
        return 1

    print(f"Secret scan passed ({args.mode}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
