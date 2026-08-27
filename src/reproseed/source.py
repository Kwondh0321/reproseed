"""Safely materialize local paths or public GitHub repositories for analysis."""

import os
import re
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Tuple
from urllib.parse import urlparse


GITHUB_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def normalize_github_url(value: str) -> str:
    value = value.strip()
    if GITHUB_REPOSITORY.fullmatch(value):
        value = "https://github.com/{}".format(value)
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
        raise ValueError("GitHub HTTPS URL(https://github.com/owner/repository)만 지원합니다.")
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not GITHUB_REPOSITORY.fullmatch(path):
        raise ValueError("올바른 GitHub 저장소 URL이 아닙니다.")
    owner, repository = path.split("/", 1)
    return "https://github.com/{}/{}.git".format(owner, repository)


@contextmanager
def materialize_source(value: str) -> Iterator[Tuple[Path, str]]:
    """Yield a local analyzable path and a stable display label."""

    if value.startswith(("https://", "http://")) or GITHUB_REPOSITORY.fullmatch(value.strip()):
        url = normalize_github_url(value)
        with tempfile.TemporaryDirectory(prefix="reproseed-") as temporary:
            destination = Path(temporary) / "repository"
            environment = dict(os.environ)
            environment["GIT_TERMINAL_PROMPT"] = "0"
            try:
                completed = subprocess.run(
                    [
                        "git",
                        "clone",
                        "--depth",
                        "1",
                        "--filter=blob:none",
                        "--single-branch",
                        url,
                        str(destination),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env=environment,
                )
            except subprocess.TimeoutExpired as error:
                raise ValueError("GitHub 저장소 복제가 60초 안에 끝나지 않았습니다.") from error
            if completed.returncode != 0:
                detail = (completed.stderr or "저장소를 복제할 수 없습니다.").strip().splitlines()[-1]
                raise ValueError("GitHub 저장소를 가져오지 못했습니다: {}".format(detail))
            yield destination, url.removesuffix(".git") if hasattr(str, "removesuffix") else url[:-4]
        return

    path = Path(value).expanduser()
    if not path.exists():
        raise FileNotFoundError("분석할 경로를 찾을 수 없습니다: {}".format(path))
    yield path, str(path.resolve())

