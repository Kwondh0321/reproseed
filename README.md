# ReproSeed

> GitHub 연구 저장소와 Jupyter Notebook의 재현 가능성을 자동으로 검사합니다.

ReproSeed는 제3자가 연구 결과를 다시 실행할 때 자주 마주치는 문제를 찾아
`0–100`점의 재현성 점수와 바로 적용할 수 있는 수정 방법을 제공합니다.

현재 MVP가 검사하는 항목:

- 의존성 파일 누락과 패키지 버전 미고정
- 확률적 코드를 사용하면서 random seed를 설정하지 않은 경우
- 사용자 컴퓨터에 종속된 절대 경로
- 로컬 데이터 파일 누락과 데이터 출처 문서화 부족
- Notebook 실행 순서와 셀 의존성 오류
- 실행 방법, Python 버전, 라이선스 문서화
- 분석 결과를 바탕으로 한 `Dockerfile`, `environment.yml` 초안 생성

## 빠른 시작

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[web]'

# 로컬 저장소 또는 Notebook 검사
reproseed analyze ./my-research --generate
reproseed analyze ./analysis.ipynb --json

# 웹 UI 실행
reproseed serve
```

브라우저에서 `http://127.0.0.1:8000`을 열고 GitHub URL을 붙여 넣거나
`.ipynb` 파일을 업로드합니다.

## 프로젝트 상태

ReproSeed는 현재 대회 시연과 사용자 피드백을 위한 MVP 단계입니다. 정적 분석은
재현성 위험을 빠르게 찾는 데 도움을 주지만, 실제 격리 환경에서 논문 결과를
완전히 재실행하는 것을 대체하지는 않습니다.

## 개발

```bash
pip install -e '.[web,dev]'
pytest
```

MIT License

