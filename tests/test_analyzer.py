import json
from pathlib import Path

from reproseed.analyzer import ReproducibilityAnalyzer


def write_notebook(path: Path, cells) -> None:
    payload = {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": execution_count,
                "metadata": {},
                "outputs": [],
                "source": source.splitlines(keepends=True),
            }
            for source, execution_count in cells
        ],
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_problematic_notebook_surfaces_core_reproducibility_risks(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("pandas\nnumpy>=1.20\n", encoding="utf-8")
    write_notebook(
        tmp_path / "analysis.ipynb",
        [
            ('data = pd.read_csv("/Users/alice/research/data.csv")', 2),
            ("import pandas as pd\nimport numpy as np\nsample = np.random.rand(10)", 1),
        ],
    )

    report = ReproducibilityAnalyzer().analyze(tmp_path)
    codes = {finding.code for finding in report.findings}

    assert {
        "ABSOLUTE_PATH_USED",
        "DATA_FILE_MISSING",
        "DEPENDENCIES_UNPINNED",
        "NOTEBOOK_EXECUTION_ORDER",
        "NOTEBOOK_FORWARD_REFERENCE",
        "RANDOM_SEED_MISSING",
        "README_MISSING",
    } <= codes
    assert report.score < 50
    assert report.stats["notebooks"] == 1
    assert report.stats["code_cells"] == 2


def test_well_documented_project_can_reach_full_score(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("numpy==2.0.2\npandas==2.2.3\n", encoding="utf-8")
    (tmp_path / ".python-version").write_text("3.11.11\n", encoding="utf-8")
    (tmp_path / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    (tmp_path / "data.csv").write_text("value\n1\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "# Study\n\n## Install and run\n`pip install -r requirements.txt` then `python analysis.py`.\n\n"
        "## Dataset source\n`data.csv` was downloaded from https://example.org/dataset.\n",
        encoding="utf-8",
    )
    (tmp_path / "analysis.py").write_text(
        "import numpy as np\nimport pandas as pd\n\nnp.random.seed(42)\ndata = pd.read_csv('data.csv')\n",
        encoding="utf-8",
    )

    report = ReproducibilityAnalyzer().analyze(tmp_path)

    assert report.score == 100
    assert report.grade == "A"
    assert report.findings == []
    assert "Dockerfile" in report.generated_files
    assert "environment.yml" in report.generated_files


def test_single_notebook_uses_adjacent_project_metadata(tmp_path: Path) -> None:
    write_notebook(tmp_path / "analysis.ipynb", [("answer = 42", 1)])
    (tmp_path / "requirements.txt").write_text("jupyter==1.1.1\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Run\nPython==3.11.11; run all cells.\n", encoding="utf-8")
    (tmp_path / "LICENSE").write_text("MIT License\n", encoding="utf-8")

    report = ReproducibilityAnalyzer().analyze(tmp_path / "analysis.ipynb")

    assert report.score == 100
    assert report.stats["notebooks"] == 1

