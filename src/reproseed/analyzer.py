"""Static reproducibility analysis for repositories and Jupyter notebooks."""

import ast
import builtins
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .generator import build_environment_yml, build_dockerfile
from .models import Finding, Report


IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "site-packages",
    "tests",
}
TEXT_SUFFIXES = {".py", ".md", ".rst", ".txt", ".toml", ".yaml", ".yml"}
LOCK_FILES = {"poetry.lock", "pdm.lock", "uv.lock", "pipfile.lock", "conda-lock.yml"}
MANIFEST_NAMES = {"pyproject.toml", "pipfile", "environment.yml", "environment.yaml"}
MAX_FILE_BYTES = 2_000_000
MAX_FILES = 2_000

SEVERITY_PENALTIES = {"critical": 20, "high": 12, "medium": 7, "low": 3}


@dataclass
class CodeDocument:
    path: Path
    relative_path: str
    code: str
    cell_sources: List[str]
    execution_counts: List[Optional[int]]


class _CellNames(ast.NodeVisitor):
    """Collect global-ish names without treating function internals as cell state."""

    def __init__(self) -> None:
        self.loads: Set[str] = set()
        self.stores: Set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        if isinstance(node.ctx, ast.Load):
            self.loads.add(node.id)
        elif isinstance(node.ctx, (ast.Store, ast.Param)):
            self.stores.add(node.id)

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            self.stores.add(alias.asname or alias.name.split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        for alias in node.names:
            if alias.name != "*":
                self.stores.add(alias.asname or alias.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self.stores.add(node.name)
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in list(node.args.defaults) + [item for item in node.args.kw_defaults if item]:
            self.visit(default)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.stores.add(node.name)
        for base in node.bases:
            self.visit(base)
        for decorator in node.decorator_list:
            self.visit(decorator)


class ReproducibilityAnalyzer:
    """Run deterministic, explainable checks against a local path."""

    def analyze(self, source: Path, display_source: Optional[str] = None) -> Report:
        source = source.expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError("분석할 경로를 찾을 수 없습니다: {}".format(source))
        if source.is_file() and source.suffix.lower() != ".ipynb":
            raise ValueError("현재 단일 파일 분석은 .ipynb 형식만 지원합니다.")

        root = source if source.is_dir() else source.parent
        all_files = self._discover_files(source)
        documents = self._load_code_documents(all_files, root)
        readable_text = self._read_text_files(all_files, root)

        findings: List[Finding] = []
        passed: List[str] = []
        self._check_dependency_manifests(root, all_files, readable_text, findings, passed)
        self._check_random_seed(documents, findings, passed)
        self._check_absolute_paths(documents, findings, passed)
        self._check_data_references(root, documents, readable_text, findings, passed)
        self._check_notebook_order(documents, findings, passed)
        self._check_project_documentation(root, all_files, readable_text, findings, passed)

        findings.sort(key=lambda item: (-item.penalty, item.category, item.code, item.file or ""))
        score = max(0, 100 - sum(item.penalty for item in findings))
        stats = {
            "files_scanned": len(all_files),
            "notebooks": sum(1 for item in documents if item.path.suffix.lower() == ".ipynb"),
            "code_cells": sum(len(item.cell_sources) for item in documents),
            "lines_of_code": sum(len(item.code.splitlines()) for item in documents),
            "finding_count": len(findings),
        }
        report = Report(
            source=display_source or str(source),
            score=score,
            grade=self._grade(score),
            findings=findings,
            passed_checks=passed,
            stats=stats,
        )
        report.generated_files = {
            "Dockerfile": build_dockerfile(root, all_files),
            "environment.yml": build_environment_yml(root, all_files, documents),
        }
        return report

    def _discover_files(self, source: Path) -> List[Path]:
        if source.is_file():
            siblings = [source]
            for candidate in source.parent.iterdir():
                lower_name = candidate.name.lower()
                if (
                    self._is_manifest(candidate)
                    or lower_name.startswith(("readme", "license", "copying", "citation"))
                    or lower_name in {".python-version", "runtime.txt", "dockerfile", "makefile"}
                ):
                    siblings.append(candidate)
            return sorted(set(siblings))

        files: List[Path] = []
        for path in source.rglob("*"):
            if len(files) >= MAX_FILES:
                break
            if not path.is_file() or any(part.lower() in IGNORED_DIRECTORIES for part in path.parts):
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            lower_name = path.name.lower()
            is_project_document = lower_name.startswith(("readme", "license", "copying", "citation"))
            is_runtime_document = lower_name in {".python-version", "runtime.txt", "dockerfile", "makefile"}
            if (
                path.suffix.lower() in TEXT_SUFFIXES | {".ipynb"}
                or self._is_manifest(path)
                or is_project_document
                or is_runtime_document
            ):
                files.append(path)
        return sorted(files)

    @staticmethod
    def _is_manifest(path: Path) -> bool:
        name = path.name.lower()
        return name in MANIFEST_NAMES | LOCK_FILES or (
            name.startswith("requirements") and name.endswith(".txt")
        )

    def _load_code_documents(self, files: Sequence[Path], root: Path) -> List[CodeDocument]:
        documents: List[CodeDocument] = []
        for path in files:
            relative = self._relative(path, root)
            if path.suffix.lower() == ".py":
                text = self._safe_read(path)
                if text is not None:
                    documents.append(CodeDocument(path, relative, text, [], []))
            elif path.suffix.lower() == ".ipynb":
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    continue
                cells = []
                counts: List[Optional[int]] = []
                for cell in payload.get("cells", []):
                    if cell.get("cell_type") != "code":
                        continue
                    source = cell.get("source", "")
                    if isinstance(source, list):
                        source = "".join(source)
                    cells.append(str(source))
                    count = cell.get("execution_count")
                    counts.append(count if isinstance(count, int) else None)
                documents.append(CodeDocument(path, relative, "\n\n".join(cells), cells, counts))
        return documents

    def _read_text_files(self, files: Sequence[Path], root: Path) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for path in files:
            if path.suffix.lower() == ".ipynb":
                continue
            text = self._safe_read(path)
            if text is not None:
                result[self._relative(path, root)] = text
        return result

    def _check_dependency_manifests(
        self,
        root: Path,
        files: Sequence[Path],
        texts: Dict[str, str],
        findings: List[Finding],
        passed: List[str],
    ) -> None:
        manifests = [path for path in files if self._is_manifest(path)]
        if not manifests:
            findings.append(
                self._finding(
                    "DEPENDENCY_MANIFEST_MISSING",
                    "의존성 파일이 없습니다",
                    "requirements.txt, pyproject.toml, environment.yml 또는 lock 파일을 찾지 못했습니다.",
                    "high",
                    "environment",
                    "실행에 필요한 패키지를 기록하고 정확한 버전 또는 lock 파일을 커밋하세요.",
                )
            )
            return

        passed.append("의존성 파일이 저장소에 포함되어 있습니다.")
        if any(path.name.lower() in LOCK_FILES for path in manifests):
            passed.append("재설치를 위한 lock 파일이 포함되어 있습니다.")
            return

        unpinned: List[Tuple[str, str]] = []
        for path in manifests:
            relative = self._relative(path, root)
            text = texts.get(relative, "")
            name = path.name.lower()
            if name.startswith("requirements") and name.endswith(".txt"):
                for line in text.splitlines():
                    item = line.strip()
                    if not item or item.startswith(("#", "-r", "--", "-e")):
                        continue
                    if not self._is_exact_requirement(item):
                        unpinned.append((item.split(";")[0], relative))
            elif name == "pyproject.toml":
                for item in self._pyproject_dependencies(text):
                    if not self._is_exact_requirement(item):
                        unpinned.append((item, relative))
            elif name in {"environment.yml", "environment.yaml"}:
                for item in self._environment_dependencies(text):
                    if not self._is_exact_conda_requirement(item):
                        unpinned.append((item, relative))

        if unpinned:
            labels = ", ".join(item[0] for item in unpinned[:5])
            if len(unpinned) > 5:
                labels += " 외 {}개".format(len(unpinned) - 5)
            findings.append(
                self._finding(
                    "DEPENDENCIES_UNPINNED",
                    "패키지 버전이 고정되지 않았습니다",
                    "정확한 버전이 없는 의존성: {}".format(labels),
                    "medium",
                    "environment",
                    "검증된 환경에서 lock 파일을 만들거나 패키지를 package==x.y.z 형식으로 고정하세요.",
                    file=unpinned[0][1],
                )
            )
        else:
            passed.append("선언된 패키지 버전이 고정되어 있습니다.")

    def _check_random_seed(
        self, documents: Sequence[CodeDocument], findings: List[Finding], passed: List[str]
    ) -> None:
        combined = "\n".join(document.code for document in documents)
        stochastic = re.search(
            r"\b(?:random\.|(?:np|numpy)\.random|torch\.(?:rand|randn|randint)|"
            r"train_test_split\s*\(|shuffle\s*\(|RandomForest\w*\s*\(|KMeans\s*\()",
            combined,
        )
        if not stochastic:
            passed.append("명시적인 확률 연산을 발견하지 않았습니다.")
            return
        seeded = re.search(
            r"\b(?:random\.seed|(?:np|numpy)\.random\.seed|torch\.manual_seed|"
            r"torch\.cuda\.manual_seed_all)\s*\(|\brandom_state\s*=\s*(?!None\b)[\w+-]+",
            combined,
        )
        if seeded:
            passed.append("확률 연산에 대한 seed 설정을 발견했습니다.")
            return
        document = next((item for item in documents if stochastic.group(0) in item.code), documents[0])
        findings.append(
            self._finding(
                "RANDOM_SEED_MISSING",
                "Random seed가 설정되지 않았습니다",
                "확률 연산을 사용하지만 재실행 결과를 고정할 seed 설정을 찾지 못했습니다.",
                "high",
                "determinism",
                "random, NumPy, PyTorch와 모델의 random_state를 한 곳에서 명시적으로 설정하세요.",
                file=document.relative_path,
                line=self._line_number(document.code, stochastic.start()),
            )
        )

    def _check_absolute_paths(
        self, documents: Sequence[CodeDocument], findings: List[Finding], passed: List[str]
    ) -> None:
        matches: List[Tuple[CodeDocument, re.Match[str]]] = []
        pattern = re.compile(
            r"(?<![A-Za-z0-9_])(?:/Users/[A-Za-z0-9_.-]+/|/home/[A-Za-z0-9_.-]+/|"
            r"/mnt/[A-Za-z]/|[A-Za-z]:[\\/](?:Users|Documents|data)[\\/])",
            re.IGNORECASE,
        )
        for document in documents:
            match = pattern.search(document.code)
            if match:
                matches.append((document, match))
        if not matches:
            passed.append("사용자 환경에 종속된 절대 경로가 없습니다.")
            return
        document, match = matches[0]
        findings.append(
            self._finding(
                "ABSOLUTE_PATH_USED",
                "컴퓨터에 종속된 절대 경로가 있습니다",
                "{}개 파일에서 /Users, /home 또는 드라이브 문자로 시작하는 경로를 발견했습니다.".format(
                    len(matches)
                ),
                "high",
                "portability",
                "저장소 루트 기준 상대 경로와 pathlib.Path를 사용하고 경로를 설정값으로 분리하세요.",
                file=document.relative_path,
                line=self._line_number(document.code, match.start()),
            )
        )

    def _check_data_references(
        self,
        root: Path,
        documents: Sequence[CodeDocument],
        texts: Dict[str, str],
        findings: List[Finding],
        passed: List[str],
    ) -> None:
        pattern = re.compile(
            r"(?:read_csv|read_excel|read_parquet|read_json|read_table|loadtxt|genfromtxt|open)"
            r"\s*\(\s*[rRuUbBfF]{0,2}['\"]([^'\"]+\.(?:csv|tsv|json|parquet|xlsx?|h5|hdf5|zip))['\"]",
            re.IGNORECASE,
        )
        references: List[Tuple[str, CodeDocument, re.Match[str]]] = []
        for document in documents:
            for match in pattern.finditer(document.code):
                references.append((match.group(1), document, match))
        if not references:
            passed.append("추적 가능한 로컬 데이터 파일 참조가 없습니다.")
            return

        missing = []
        undocumented = []
        documentation = "\n".join(
            value.lower()
            for key, value in texts.items()
            if Path(key).name.lower().startswith(("readme", "data", "citation"))
            or Path(key).suffix.lower() in {".md", ".rst"}
        )
        for reference, document, match in references:
            if reference.startswith(("http://", "https://")):
                continue
            candidate = (root / reference).resolve()
            try:
                inside_root = candidate == root or root in candidate.parents
            except OSError:
                inside_root = False
            if not inside_root or not candidate.exists():
                missing.append((reference, document, match))
            else:
                filename = Path(reference).name.lower()
                if filename not in documentation or not re.search(
                    r"\b(source|출처|dataset|데이터셋|download|다운로드|doi|kaggle|zenodo)\b",
                    documentation,
                    re.IGNORECASE,
                ):
                    undocumented.append((reference, document, match))

        if missing:
            labels = ", ".join(sorted({item[0] for item in missing})[:5])
            reference, document, match = missing[0]
            findings.append(
                self._finding(
                    "DATA_FILE_MISSING",
                    "참조한 데이터 파일이 없습니다",
                    "코드가 읽는 파일을 저장소에서 찾을 수 없습니다: {}".format(labels),
                    "high",
                    "data",
                    "작은 데이터는 저장소에 포함하고, 큰 데이터는 다운로드 URL·DOI·체크섬과 준비 명령을 문서화하세요.",
                    file=document.relative_path,
                    line=self._line_number(document.code, match.start()),
                )
            )
        else:
            passed.append("코드가 참조하는 로컬 데이터 파일이 존재합니다.")

        if undocumented:
            labels = ", ".join(sorted({item[0] for item in undocumented})[:5])
            reference, document, match = undocumented[0]
            findings.append(
                self._finding(
                    "DATA_PROVENANCE_MISSING",
                    "데이터 출처가 문서화되지 않았습니다",
                    "다음 데이터의 원본 출처나 버전을 문서에서 찾지 못했습니다: {}".format(labels),
                    "medium",
                    "data",
                    "README 또는 data/README에 출처 URL, 버전·수집일, 라이선스와 체크섬을 기록하세요.",
                    file=document.relative_path,
                    line=self._line_number(document.code, match.start()),
                )
            )
        elif references:
            passed.append("데이터 출처를 추적할 수 있는 문서가 있습니다.")

    def _check_notebook_order(
        self, documents: Sequence[CodeDocument], findings: List[Finding], passed: List[str]
    ) -> None:
        notebooks = [item for item in documents if item.cell_sources]
        if not notebooks:
            return
        order_problem = False
        dependency_problem = False
        builtin_names = set(dir(builtins)) | {"get_ipython", "display"}
        for document in notebooks:
            counts = [count for count in document.execution_counts if count is not None]
            if len(counts) >= 2 and any(left >= right for left, right in zip(counts, counts[1:])):
                findings.append(
                    self._finding(
                        "NOTEBOOK_EXECUTION_ORDER",
                        "Notebook 실행 순서가 뒤섞여 있습니다",
                        "셀 배치 순서와 execution_count가 일치하지 않습니다: {}".format(counts[:8]),
                        "high",
                        "execution",
                        "커널을 재시작한 뒤 Run All로 위에서 아래까지 실행하고 성공한 Notebook을 저장하세요.",
                        file=document.relative_path,
                    )
                )
                order_problem = True

            cell_names = [self._cell_names(source) for source in document.cell_sources]
            future_stores: List[Set[str]] = []
            for index in range(len(cell_names)):
                future_stores.append(set().union(*(stores for _, stores in cell_names[index + 1 :])))
            known = set(builtin_names)
            offenders: List[Tuple[int, str]] = []
            for index, (loads, stores) in enumerate(cell_names):
                for name in sorted((loads - known - stores) & future_stores[index]):
                    offenders.append((index + 1, name))
                known.update(stores)
            if offenders:
                preview = ", ".join("셀 {}의 {}".format(cell, name) for cell, name in offenders[:5])
                findings.append(
                    self._finding(
                        "NOTEBOOK_FORWARD_REFERENCE",
                        "뒤쪽 셀에서 정의되는 값을 먼저 사용합니다",
                        "위에서 아래로 실행하면 정의되기 전에 사용될 수 있습니다: {}".format(preview),
                        "high",
                        "execution",
                        "변수·함수·import를 처음 사용하는 셀보다 앞으로 옮기고 새 커널에서 Run All로 검증하세요.",
                        file=document.relative_path,
                    )
                )
                dependency_problem = True
        if not order_problem:
            passed.append("저장된 Notebook execution_count 순서가 일관됩니다.")
        if not dependency_problem:
            passed.append("Notebook 셀에서 뒤쪽 정의에 의존하는 패턴이 없습니다.")

    def _check_project_documentation(
        self,
        root: Path,
        files: Sequence[Path],
        texts: Dict[str, str],
        findings: List[Finding],
        passed: List[str],
    ) -> None:
        readme_entries = [(key, value) for key, value in texts.items() if Path(key).name.lower().startswith("readme")]
        if not readme_entries:
            findings.append(
                self._finding(
                    "README_MISSING",
                    "README가 없습니다",
                    "연구 목적과 재실행 방법을 설명하는 문서를 찾지 못했습니다.",
                    "medium",
                    "documentation",
                    "필요 환경, 설치, 데이터 준비, 실행 명령, 예상 결과를 README에 기록하세요.",
                )
            )
        else:
            passed.append("README가 포함되어 있습니다.")
            readme_path, readme = readme_entries[0]
            if not re.search(r"\b(install|usage|run|quickstart|setup|실행|설치|사용법)\b", readme, re.IGNORECASE):
                findings.append(
                    self._finding(
                        "RUN_INSTRUCTIONS_MISSING",
                        "실행 방법이 충분히 설명되지 않았습니다",
                        "README에서 설치 또는 실행 명령을 찾지 못했습니다.",
                        "low",
                        "documentation",
                        "깨끗한 환경에서 복사해 실행할 수 있는 설치·데이터 준비·실행 명령을 추가하세요.",
                        file=readme_path,
                    )
                )
            else:
                passed.append("README에 설치 또는 실행 안내가 있습니다.")

        file_names = {path.name.lower() for path in files}
        if any(name.startswith(("license", "copying")) for name in file_names):
            passed.append("재사용 조건을 설명하는 라이선스 파일이 있습니다.")
        else:
            findings.append(
                self._finding(
                    "LICENSE_MISSING",
                    "라이선스가 없습니다",
                    "제3자가 코드와 데이터를 재사용할 수 있는 조건이 명확하지 않습니다.",
                    "low",
                    "documentation",
                    "코드 라이선스와 데이터 라이선스를 확인해 저장소에 명시하세요.",
                )
            )

        runtime_markers = {".python-version", "runtime.txt"}
        has_runtime = bool(file_names & runtime_markers)
        has_runtime = has_runtime or any(
            re.search(r"python\s*(?:==|=|:|>=|~)\s*3\.\d+", text, re.IGNORECASE)
            for text in texts.values()
        )
        if has_runtime:
            passed.append("Python 런타임 버전이 명시되어 있습니다.")
        else:
            findings.append(
                self._finding(
                    "PYTHON_VERSION_MISSING",
                    "Python 버전이 명시되지 않았습니다",
                    "실행에 필요한 Python 주·부 버전을 찾지 못했습니다.",
                    "low",
                    "environment",
                    ".python-version, environment.yml 또는 README에 검증한 Python 버전을 기록하세요.",
                )
            )

    @staticmethod
    def _cell_names(source: str) -> Tuple[Set[str], Set[str]]:
        cleaned = "\n".join(
            "" if line.lstrip().startswith(("%", "!")) else line for line in source.splitlines()
        )
        try:
            tree = ast.parse(cleaned)
        except SyntaxError:
            return set(), set()
        collector = _CellNames()
        collector.visit(tree)
        return collector.loads, collector.stores

    @staticmethod
    def _pyproject_dependencies(text: str) -> List[str]:
        blocks = re.findall(r"(?:dependencies|requires)\s*=\s*\[(.*?)\]", text, re.DOTALL)
        dependencies = []
        for block in blocks:
            dependencies.extend(re.findall(r"['\"]([^'\"]+)['\"]", block))
        return dependencies

    @staticmethod
    def _environment_dependencies(text: str) -> List[str]:
        dependencies = []
        in_dependencies = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped == "dependencies:":
                in_dependencies = True
                continue
            if in_dependencies and stripped and not line.startswith((" ", "\t", "-")):
                break
            if in_dependencies and stripped.startswith("-"):
                value = stripped[1:].strip().strip("'\"")
                if value and value not in {"pip", "pip:"}:
                    dependencies.append(value)
        return dependencies

    @staticmethod
    def _is_exact_requirement(item: str) -> bool:
        item = item.split("#", 1)[0].strip()
        if re.search(r"===?\s*[^*\s,;]+", item):
            return True
        if " @ " in item and re.search(r"@[0-9a-f]{7,40}(?:#|$)", item, re.IGNORECASE):
            return True
        return False

    @staticmethod
    def _is_exact_conda_requirement(item: str) -> bool:
        return bool(re.search(r"(?<![<>!~])={1,2}\s*[^*\s,]+", item))

    @staticmethod
    def _finding(
        code: str,
        title: str,
        message: str,
        severity: str,
        category: str,
        remediation: str,
        file: Optional[str] = None,
        line: Optional[int] = None,
    ) -> Finding:
        return Finding(
            code=code,
            title=title,
            message=message,
            severity=severity,
            category=category,
            remediation=remediation,
            file=file,
            line=line,
            penalty=SEVERITY_PENALTIES[severity],
        )

    @staticmethod
    def _safe_read(path: Path) -> Optional[str]:
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    @staticmethod
    def _relative(path: Path, root: Path) -> str:
        try:
            return str(path.relative_to(root))
        except ValueError:
            return path.name

    @staticmethod
    def _line_number(text: str, offset: int) -> int:
        return text.count("\n", 0, offset) + 1

    @staticmethod
    def _grade(score: int) -> str:
        if score >= 90:
            return "A"
        if score >= 80:
            return "B"
        if score >= 70:
            return "C"
        if score >= 60:
            return "D"
        return "F"
