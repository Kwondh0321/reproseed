"""FastAPI application powering the ReproSeed browser experience."""

import json
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .analyzer import ReproducibilityAnalyzer
from .source import materialize_source


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
WEB_ROOT = Path(__file__).with_name("web")

app = FastAPI(
    title="ReproSeed API",
    description="Research repository and Jupyter Notebook reproducibility checks",
    version="0.1.0",
)


class GitHubAnalysisRequest(BaseModel):
    url: str


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> HTMLResponse:
    return HTMLResponse((WEB_ROOT / "index.html").read_text(encoding="utf-8"))


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "reproseed"}


@app.post("/api/analyze/github")
def analyze_github(payload: GitHubAnalysisRequest) -> dict:
    if not payload.url.strip():
        raise HTTPException(status_code=422, detail="GitHub 저장소 URL을 입력하세요.")
    try:
        with materialize_source(payload.url) as (path, label):
            report = ReproducibilityAnalyzer().analyze(path, display_source=label)
            return report.to_dict()
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/analyze/notebook")
async def analyze_notebook(file: UploadFile = File(...)) -> dict:
    filename = Path(file.filename or "notebook.ipynb").name
    if not filename.lower().endswith(".ipynb"):
        raise HTTPException(status_code=422, detail=".ipynb 파일만 업로드할 수 있습니다.")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Notebook은 최대 10MB까지 업로드할 수 있습니다.")
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=422, detail="올바른 Jupyter Notebook JSON이 아닙니다.") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("cells"), list):
        raise HTTPException(status_code=422, detail="Notebook에 cells 배열이 없습니다.")

    with tempfile.TemporaryDirectory(prefix="reproseed-upload-") as temporary:
        path = Path(temporary) / filename
        path.write_bytes(content)
        report = ReproducibilityAnalyzer().analyze(path, display_source=filename)
        return report.to_dict()

