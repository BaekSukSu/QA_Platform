# QA Platform

QA Platform은 프로그래밍·인공지능 분야 교재의 PDF에서 Python 코드 예제를 추출하고, 실행 가능한 표준 코드 블록으로 정규화한 뒤, Docker 컨테이너에서 실행하여 예상 출력과 실제 출력을 비교하는 CLI 기반 검수 도구다.

현재 제품의 주 실행 환경은 Apple Silicon 기반 macOS이며, 소스 설치와 macOS ARM64용 `.pkg` 설치 방식을 지원한다. macOS에서는 PDF를 입력으로 사용한다.

## 현재 구현 범위

- PDF의 페이지별 텍스트와 embedded image 추출
- Tesseract OCR을 이용한 코드 후보 이미지 사전 필터링
- Gemini API를 이용한 코드, 입력값, 예상 출력 및 패키지 정보 구조화
- `[META]`, `[PACKAGES]`, `[SETUP]`, `[CODE]`, `[INPUT]`, `[OUTPUT]` 표준 block 생성
- 문맥 정의 복원, 물리 block 병합 및 실행 가능성 사전 판정
- 코드 block별 Docker 컨테이너 격리 실행
- Python 버전과 외부 패키지에 맞는 Docker image 자동 준비
- 표준 출력 비교와 `passed`, `failed`, `skipped` 판정
- JSON, JSONL 및 Markdown 결과보고서 생성
- `run`, `init-config`, `doctor` CLI 제공
- macOS ARM64용 실행 파일과 `.pkg` 패키지 생성

## 전체 처리 흐름

```mermaid
flowchart LR
    A[교재 PDF] --> B[텍스트·이미지 추출]
    B --> C[Tesseract OCR 필터]
    C --> D[Gemini 구조화]
    D --> E[표준 block 정규화]
    E --> F[Docker 격리 실행]
    F --> G[예상·실제 출력 비교]
    G --> H[JSON·Markdown 보고서]
```

애플리케이션은 로컬 파일 시스템을 단계 간 계약과 영속 저장소로 사용하는 동기식 CLI 배치 프로그램이다. 데이터베이스, 웹 API, 메시지 큐와 GUI는 현재 구현 범위에 포함되지 않는다.

## 주요 디렉터리

```text
qa_platform/
├── pipeline/       CLI, 설정, 환경 점검, 전체 파이프라인 조정
├── extraction/     PDF/HWP 추출, OCR, Gemini 구조화, 후처리
├── contract/       block 계약, 파서, 패키지 및 skip 정책
├── execution/      Docker 실행, 출력 비교, 결과 판정
├── chapter/        챕터 단위 실행 수명주기
├── reporting/      JSON 및 Markdown 보고서 생성
└── shared/         경로, 환경변수, 리소스와 세션 공통 기능

config/              사용자 설정 예제
docker/              Docker 실행 환경 자료
distribution/macos/  PyInstaller CLI 진입점
tools/macos/         macOS 실행 파일 및 pkg 생성 도구
tests/               단위·계약·통합 테스트
```

## 실행 전 준비사항

| 항목 | 용도 | 확인 방법 |
| --- | --- | --- |
| macOS | 현재 배포 패키지의 대상 운영체제 | Apple Silicon ARM64 기준 |
| Python 3.11 이상 | 소스에서 설치할 때 필요 | `python3 --version` |
| Docker Desktop | 추출된 코드를 격리 실행하고 실행 image를 준비 | Docker Desktop 실행 후 `docker version` |
| Tesseract OCR | PDF embedded image의 코드 가능성 판정 | `tesseract --version` |
| Gemini API key | 문서와 이미지에서 코드 예제를 구조화 | `.env`의 `GEMINI_API_KEY` |
| 네트워크 연결 | Gemini API 호출과 최초 Docker image 준비 | API 및 Docker registry 접근 가능 상태 |

macOS에서 Tesseract를 Homebrew로 설치할 경우 다음 명령을 사용할 수 있다.

```bash
brew install tesseract
```

Docker Desktop은 설치만으로 충분하지 않으며, `qa-platform run`을 실행하기 전에 Docker daemon이 동작 중이어야 한다.

## 빠른 시작: macOS 설치 패키지

내부 배포용 `.pkg`가 준비된 경우 다음과 같이 설치한다.

```bash
sudo installer -pkg qa-platform-macos-arm64.pkg -target /
qa-platform --help
```

설치 위치는 다음과 같다.

- CLI wrapper: `/usr/local/bin/qa-platform`
- 프로그램: `/Library/Application Support/QA Platform/app/qa-platform/`

현재 생성 도구는 서명 identity를 지정하지 않으면 미서명 패키지를 만든다. 외부 공식 배포에는 Developer ID 서명과 Apple 공증 절차가 추가로 필요하다.

### 1. 사용자 workspace 생성

```bash
qa-platform init-config
```

기본 workspace는 다음 경로다.

```text
~/Documents/QA Platform
```

생성되는 주요 파일과 디렉터리는 다음과 같다.

```text
~/Documents/QA Platform/
├── .env
├── config/
│   └── qa_pipeline.local.json
├── input/
├── extracted_blocks/
├── run/
└── logs/
```

다른 workspace를 사용하려면 명시적으로 지정한다.

```bash
qa-platform init-config --workspace-root "/path/to/qa-workspace"
```

### 2. Gemini API key 설정

workspace의 `.env`에 실제 API key를 입력한다.

```dotenv
GEMINI_API_KEY=your_api_key_here
```

API key는 `config.json`에 넣지 않는다. `.env` 역시 Git에 커밋하지 않는다.

### 3. 입력 PDF와 설정 준비

검수할 PDF를 workspace의 `input/`에 넣고 `config/qa_pipeline.local.json`을 수정한다. 현재 설정 양식은 [`config/qa_pipeline.example.json`](config/qa_pipeline.example.json)을 기준으로 한다.

macOS에서는 다음 설정을 사용한다.

```json
{
  "project": {
    "book_id": "sample_book",
    "chapter_number": 1,
    "python_version": "3.11",
    "extractor_engine": "pdf",
    "keep_temp_images": false
  },
  "paths": {
    "workspace_root": "..",
    "env_file": ".env",
    "input_pdf": "input/chapter01.pdf",
    "output_root": "extracted_blocks",
    "work_root": "run/document_extraction",
    "run_root": "run/qa_pipeline",
    "tesseract_cmd": "tesseract"
  },
  "execution": {
    "backend": "docker",
    "docker": {
      "docker_cmd": "docker",
      "timeout_seconds": 5,
      "output_limit_chars": 20000,
      "memory_limit": "256m",
      "cpu_limit": 0.5,
      "pids_limit": 64,
      "work_tmpfs_size": "64m",
      "temp_tmpfs_size": "64m",
      "user": "10001:10001",
      "image_build_timeout_seconds": 300
    }
  }
}
```

`workspace_root`가 상대 경로이면 config 파일이 있는 디렉터리를 기준으로 해석한다. 위 예제는 파일이 `workspace/config/`에 있다는 전제이므로 `..`가 workspace를 가리킨다. 그 밖의 상대 경로는 결정된 workspace 아래에서 해석된다.

### 4. 실행 환경 점검

```bash
qa-platform doctor
```

별도 workspace나 config를 사용하는 경우 다음과 같이 실행한다.

```bash
qa-platform doctor \
  --workspace-root "/path/to/qa-workspace" \
  --config "/path/to/qa-workspace/config/qa_pipeline.local.json"
```

`doctor`는 다음 항목을 확인한다.

- workspace와 config 파일
- `.env` 파일
- `/usr/local/bin`의 PATH 포함 여부
- Tesseract 실행 파일
- Docker CLI와 Docker daemon
- 선택적 resource directory

### 5. 전체 QA 파이프라인 실행

기본 workspace를 사용하는 경우 다음 명령만 실행하면 된다.

```bash
qa-platform run
```

config를 직접 지정할 수도 있다.

```bash
qa-platform run --config config/qa_pipeline.local.json
```

호환성을 위해 다음 형식도 `run` 명령으로 처리한다.

```bash
qa-platform --config config/qa_pipeline.local.json
```

완료되면 CLI가 block 디렉터리, 실행 디렉터리, Markdown 보고서와 요약 JSON 경로를 출력한다.

## 빠른 시작: 소스에서 실행

### 1. Python 환경 설치

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

### 2. 로컬 설정 생성

```bash
mkdir -p input
cp config/qa_pipeline.example.json config/qa_pipeline.local.json
cp .env.example .env
```

`.env`에 Gemini API key를 입력하고 `input/chapter01.pdf`에 검수할 PDF를 배치한다.

### 3. 환경 점검과 실행

```bash
qa-platform doctor \
  --workspace-root . \
  --config config/qa_pipeline.local.json

qa-platform run --config config/qa_pipeline.local.json
```

## 설정 항목

### `project`

| 항목 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `book_id` | 아니요 | `default` | 출력 디렉터리를 구분하는 영문 식별자 |
| `chapter_number` | 예 | 없음 | 검수 대상 장 번호 |
| `python_version` | 아니요 | `3.11` | Docker에서 사용할 Python 버전 문자열 |
| `extractor_engine` | 아니요 | `auto` | `auto`, `pdf`, `windows_com` 중 선택 |
| `keep_temp_images` | 아니요 | `false` | 추출 중간 이미지를 보존할지 여부 |
| `session_id` | 아니요 | 자동 생성 | 실행 디렉터리 이름을 직접 지정할 때 사용 |
| `security_module_name` | 아니요 | `SecurityModule` | Windows HWP COM 보안 모듈 이름 |

`python_version`은 반드시 `"3.11"`처럼 문자열로 작성한다. 숫자 `3.11`이나 `"latest"`는 허용되지 않는다.

### `paths`

| 항목 | 기본값 | 설명 |
| --- | --- | --- |
| `workspace_root` | `~/Documents/QA Platform` | 모든 상대 입력·출력 경로의 기준 |
| `env_file` | `<workspace>/.env` | Gemini API key를 읽을 env 파일 |
| `input_pdf` | 없음 | macOS 및 PDF 엔진의 입력 문서 |
| `input_hwp` | 없음 | Windows COM 엔진의 HWP 입력 문서 |
| `output_root` | `extracted_blocks` | 정규화된 block 저장 루트 |
| `work_root` | `run/document_extraction` | 추출 중간 산출물 루트 |
| `run_root` | `run` | Docker 실행과 보고서 저장 루트 |
| `tesseract_cmd` | PATH 탐색 | Tesseract 명령명 또는 실행 파일 경로 |
| `resource_root` | 자동 탐색 | 선택적 bundled resource 디렉터리 |

macOS에서 `extractor_engine=auto`를 사용하면 PDF 엔진이 선택된다. macOS에서 HWP를 직접 입력하는 엔진은 없으므로 HWP 문서는 PDF로 변환한 후 `input_pdf`로 지정한다.

### `execution`

`execution.backend`는 현재 `docker`만 허용한다. 로컬 Python fallback은 제공하지 않는다.

| Docker 항목 | 기본값 | 설명 |
| --- | --- | --- |
| `docker_cmd` | PATH 탐색 | Docker CLI 명령명 또는 실행 파일 경로 |
| `image` | 자동 결정 | 명시적인 사용자 Docker image |
| `install_requirements` | 빈 목록 | 모든 block image에 추가할 공통 pip requirement |
| `dependency_image_repository` | `qa-platform-python` | 패키지 조합별 image 저장소 이름 |
| `timeout_seconds` | `5` | block 실행 제한 시간 |
| `output_limit_chars` | `20000` | stdout와 stderr별 최대 보존 문자 수 |
| `memory_limit` | `256m` | 컨테이너 메모리 제한 |
| `cpu_limit` | `0.5` | 컨테이너 CPU 제한 |
| `pids_limit` | `64` | 컨테이너 PID 제한 |
| `work_tmpfs_size` | `64m` | `/work` tmpfs 크기 |
| `temp_tmpfs_size` | `64m` | `/tmp` tmpfs 크기 |
| `user` | `10001:10001` | 컨테이너 내부 비권한 사용자 |
| `image_build_context` | 없음 | 사용자 지정 Docker build context |
| `image_build_dockerfile` | 없음 | 사용자 지정 Dockerfile |
| `image_build_timeout_seconds` | `300` | Docker image build 제한 시간 |

`image_build_context`와 `image_build_dockerfile`은 반드시 함께 지정한다. `image`를 직접 지정한 경우에는 `install_requirements`를 동시에 사용할 수 없다. 기본 설정에서는 block의 `[PACKAGES]`와 import 분석 결과를 이용해 필요한 dependency image를 자동 생성한다.

## 결과 디렉터리

기본 예제 설정으로 실행하면 다음 구조가 생성된다.

```text
workspace/
├── extracted_blocks/
│   └── sample_book_ch1_<session_id>/
│       ├── block_001.txt
│       └── block_002.txt
└── run/
    ├── document_extraction/
    │   └── chap1_<session_id>/
    │       ├── extracted_text.txt
    │       └── temp_images/
    └── qa_pipeline/
        └── <session_id>/
            ├── run_manifest.json
            ├── results.jsonl
            ├── qa_pipeline.json
            ├── chapter_error_report.json
            ├── chapter_error_report.md
            └── blocks/
                └── block_001/
                    ├── block.txt
                    ├── block.json
                    ├── normalized.py
                    └── result.json
```

### 결과 상태

| 상태 | 의미 |
| --- | --- |
| `passed` | 실행이 정상 종료되고 비교 대상 출력이 일치함 |
| `failed` | 파싱, 실행, timeout, 누락 dependency 또는 출력 비교에 실패함 |
| `skipped` | 불완전 코드, GUI·환경 의존 코드, 미지원 패키지 등 자동 실행 대상이 아님 |

`output_determinism=nondeterministic`인 block은 정상 종료 여부만 판정하고 출력 문자열 비교는 생략한다. 이 값은 사용자 config가 아니라 추출된 block의 `[META]`에 기록된다.

## 테스트 실행

```bash
python -m pytest -q
```

Docker daemon이 필요한 테스트에는 `docker` marker가 사용된다. Docker 통합 테스트를 제외하려면 다음과 같이 실행한다.

```bash
python -m pytest -q -m "not docker"
```

## macOS `.pkg` 생성

```bash
python -m pip install -e '.[macos-pkg]'
python -m tools.macos.build_pkg --version 0.1.0
```

기본 결과 파일은 다음 경로에 생성된다.

```text
dist/qa-platform-macos-arm64.pkg
```

서명 identity가 준비된 경우 `--sign-identity`를 지정할 수 있다.

## 현재 제약사항

- macOS의 직접 입력 계약은 PDF이며 HWP 직접 자동 분석은 지원하지 않는다.
- Windows HWP 입력은 한컴오피스, `pywin32`와 보안 모듈 등록이 필요하다.
- DOCX 전용 추출 엔진은 구현되어 있지 않다.
- Gemini 응답과 OCR 결과에는 오인식 가능성이 있으므로 최종 편집 판단은 사람이 수행해야 한다.
- 플랫폼은 교재 원고를 자동 수정하지 않고 검수 결과와 수정 근거를 제공한다.
- 전체 파이프라인은 동기식 순차 처리이며 GUI와 웹 서비스는 제공하지 않는다.
- 미서명 `.pkg`는 내부 시험용이며 외부 공식 배포 완료 상태를 의미하지 않는다.

## 보안과 저장소 관리

다음 파일과 디렉터리는 Git 저장소에 올리지 않는다.

- `.env`와 실제 Gemini API key
- 원본 교재 PDF·HWP와 저작권이 있는 입력 자료
- `config/*.local.json`
- `extracted_blocks/`, `data/`, `run/`, `tmp/`
- `.venv/`, `build/`, `dist/`, `*.pkg`
- 코드 서명 인증서와 개인키

공개 예제에는 실제 API key, 사용자 절대경로, 교재 원문과 실제 운영 데이터 대신 placeholder와 합성 fixture만 사용한다.

## 관련 문서

- [QA Platform 기술·운영 통합 가이드](docs/QA_Platform_기술_운영_통합_가이드.md)

## 라이선스

이 프로젝트는 [MIT License](LICENSE)로 배포한다.
