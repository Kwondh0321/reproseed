# ReproSeed 🌱

[![CI](https://github.com/Kwondh0321/reproseed/actions/workflows/ci.yml/badge.svg)](https://github.com/Kwondh0321/reproseed/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-1f7a4c)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-c9f44f)](LICENSE)

> GitHub 연구 저장소와 Jupyter Notebook의 재현 가능성을 자동으로 검사합니다.

ReproSeed는 제3자가 연구 결과를 다시 실행할 때 자주 마주치는 문제를 찾아
`0–100`점의 재현성 점수, 문제의 근거 위치, 바로 적용할 수 있는 수정 방법을
제공하는 오픈소스 도구입니다. 연구 코드를 실행하지 않는 정적 분석 방식이라
빠르고 안전하게 첫 번째 재현성 감사를 시작할 수 있습니다.

```text
ReproSeed Reproducibility Score: 62/100 (D)

- [HIGH] Random seed가 설정되지 않았습니다 (-12) [analysis.ipynb:18]
- [MEDIUM] 패키지 버전이 고정되지 않았습니다 (-7) [requirements.txt]
- [HIGH] 참조한 데이터 파일이 없습니다 (-12) [analysis.ipynb:7]
```

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

Docker로도 바로 실행할 수 있습니다.

```bash
docker build -t reproseed .
docker run --rm -p 8000:8000 reproseed
```

## 어떻게 검사하나요?

| 영역 | 검사 예시 | 기본 감점 |
| --- | --- | ---: |
| 환경 | 의존성 파일 누락, 버전 미고정, Python 버전 누락 | -3 ~ -12 |
| 결정성 | NumPy·PyTorch·모델을 쓰지만 seed 또는 `random_state` 없음 | -12 |
| 이식성 | `/Users/...`, `/home/...`, 로컬 드라이브 절대 경로 | -12 |
| 데이터 | 참조 파일 누락, URL·DOI·라이선스·출처 문서 부족 | -7 ~ -12 |
| 실행 | Notebook 실행 번호 역전, 뒤쪽 셀의 변수를 먼저 사용 | -12 |
| 문서 | README, 실행 안내, 라이선스 누락 | -3 ~ -7 |

점수는 100점에서 각 발견 사항의 감점을 빼서 계산합니다. 모든 발견 사항에는
사람이 읽을 수 있는 설명과 수정 제안이 포함됩니다. 같은 결과에서
`Dockerfile`과 `environment.yml` 초안도 내려받을 수 있습니다.

## CLI

```bash
# GitHub 공개 저장소 또는 로컬 인증으로 접근 가능한 저장소
reproseed analyze https://github.com/owner/research

# JSON 출력은 CI, bot, 대시보드 연동에 사용
reproseed analyze ./analysis.ipynb --json > report.json

# 환경 파일 초안을 reproducibility/에 저장
reproseed analyze ./research --generate
```

GitHub 입력은 `https://github.com/owner/repository` 형식만 허용하고 임시 폴더에
shallow clone한 뒤 분석이 끝나면 삭제합니다. Notebook 업로드는 10MB로 제한하며
서버에서 코드를 실행하지 않습니다.

## 구조

```text
src/reproseed/
├── analyzer.py   # 검사 orchestration과 점수 계산
├── generator.py  # Dockerfile/environment.yml 초안
├── source.py     # 로컬·GitHub 입력 처리
├── cli.py        # reproseed analyze / serve
├── webapp.py     # FastAPI API
└── web/          # 의존성 없는 반응형 UI
```

## 현재 한계와 로드맵

정적 분석은 빠른 위험 탐지에 적합하지만 연구 결과 자체를 검증하지는 않습니다.
다음 단계에서는 격리된 컨테이너에서 Notebook을 실제 실행하고, 출력 해시와 데이터
체크섬을 검증하며, GitHub App으로 Pull Request에 자동 코멘트하는 기능을 계획하고
있습니다.

## 프로젝트 상태

ReproSeed는 현재 대회 시연과 사용자 피드백을 위한 MVP 단계입니다. 이슈와 PR을
환영합니다.

## 개발

```bash
pip install -e '.[web,dev]'
pytest
```

MIT License
