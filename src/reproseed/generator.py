"""Generate reproducibility environment drafts from discovered project metadata."""

import ast
import re
import sys
from pathlib import Path
from typing import Iterable, List, Sequence, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from .analyzer import CodeDocument


IMPORT_TO_PACKAGE = {
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "yaml": "PyYAML",
}
STDLIB = set(getattr(sys, "stdlib_module_names", set())) | {
    "argparse",
    "ast",
    "collections",
    "contextlib",
    "csv",
    "dataclasses",
    "datetime",
    "functools",
    "hashlib",
    "io",
    "itertools",
    "json",
    "logging",
    "math",
    "os",
    "pathlib",
    "pickle",
    "random",
    "re",
    "shutil",
    "statistics",
    "subprocess",
    "sys",
    "tempfile",
    "time",
    "typing",
    "urllib",
    "uuid",
}


def build_dockerfile(root: Path, files: Sequence[Path]) -> str:
    names = {path.name.lower() for path in files}
    requirements = next(
        (path.name for path in files if path.name.lower() == "requirements.txt"), None
    )
    has_pyproject = "pyproject.toml" in names
    lines = [
        "FROM python:3.11.11-slim",
        "",
        "ENV PYTHONDONTWRITEBYTECODE=1 \\",
        "    PYTHONUNBUFFERED=1 \\",
        "    PIP_NO_CACHE_DIR=1",
        "",
        "WORKDIR /workspace",
    ]
    if requirements:
        lines.extend(
            [
                "COPY requirements.txt ./",
                "RUN python -m pip install --upgrade pip==25.0.1 \\",
                "    && python -m pip install -r requirements.txt",
            ]
        )
    elif has_pyproject:
        lines.extend(
            [
                "COPY pyproject.toml ./",
                "COPY src ./src",
                "RUN python -m pip install --upgrade pip==25.0.1 \\",
                "    && python -m pip install .",
            ]
        )
    else:
        lines.extend(
            [
                "# TODO: 검증된 의존성 파일을 만든 뒤 아래 줄을 활성화하세요.",
                "# COPY requirements.txt ./",
                "# RUN python -m pip install -r requirements.txt",
                "RUN python -m pip install jupyterlab==4.3.5",
            ]
        )
    lines.extend(
        [
            "",
            "COPY . .",
            "",
            "EXPOSE 8888",
            'CMD ["python", "-m", "jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root"]',
            "",
        ]
    )
    return "\n".join(lines)


def build_environment_yml(root: Path, files: Sequence[Path], documents: Sequence["CodeDocument"]) -> str:
    requirements = next(
        (path for path in files if path.name.lower() == "requirements.txt"), None
    )
    lines = [
        "name: reproseed-research",
        "channels:",
        "  - conda-forge",
        "dependencies:",
        "  - python=3.11.11",
        "  - pip=25.0.1",
        "  - pip:",
    ]
    if requirements:
        lines.append("      - -r requirements.txt")
    else:
        packages = _infer_packages(document.code for document in documents)
        if packages:
            lines.append("      # TODO: 성공적으로 실행한 버전으로 각각 고정하세요.")
            lines.extend("      - {}".format(package) for package in packages)
        else:
            lines.extend(
                [
                    "      # TODO: 연구 코드에 필요한 패키지를 정확한 버전과 함께 추가하세요.",
                    "      - jupyterlab==4.3.5",
                ]
            )
    lines.append("")
    return "\n".join(lines)


def _infer_packages(code_blocks: Iterable[str]) -> List[str]:
    modules: Set[str] = set()
    for code in code_blocks:
        cleaned = "\n".join(
            "" if line.lstrip().startswith(("%", "!")) else line for line in code.splitlines()
        )
        try:
            tree = ast.parse(cleaned)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[0])
    packages = []
    for module in sorted(modules):
        if module in STDLIB or module.startswith("_"):
            continue
        packages.append(IMPORT_TO_PACKAGE.get(module, module))
    return packages

