"""Domain models shared by the analyzer, CLI, and web API."""

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Finding:
    code: str
    title: str
    message: str
    severity: str
    category: str
    remediation: str
    file: Optional[str] = None
    line: Optional[int] = None
    penalty: int = 0

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class Report:
    source: str
    score: int
    grade: str
    findings: List[Finding] = field(default_factory=list)
    passed_checks: List[str] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)
    generated_files: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "source": self.source,
            "score": self.score,
            "grade": self.grade,
            "findings": [finding.to_dict() for finding in self.findings],
            "passed_checks": self.passed_checks,
            "stats": self.stats,
            "generated_files": self.generated_files,
        }

