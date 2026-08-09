# QA Platform 기술·운영 통합 가이드

## 문서 목적

이 문서는 QA Platform의 다음 네 가지 주제를 한곳에서 확인할 수 있도록 정리한 공개용 통합 문서다.

- 코드 블록 입출력 계약
- 전체 QA 파이프라인 실행 방법
- 현재 `config.json` 설정 항목과 경로 해석 규칙
- Docker 기반 코드 실행 구조와 결과 판정 방식

기존 설계 문서에 남아 있던 초기 아이디어나 미결정 항목은 현재 소스와 일치하는 내용으로 교정했다. 따라서 설치, 운영, 연동 구현 시에는 이 문서를 현재 기준으로 사용한다.

## 1. 시스템 개요

QA Platform은 프로그래밍·인공지능 교재의 PDF에서 Python 예제를 추출하고, 실행 가능한 표준 코드 블록으로 정규화한 뒤, 각 블록을 Docker 컨테이너에서 독립 실행하여 검수 결과를 만드는 CLI 애플리케이션이다.

```mermaid
flowchart LR
    A[교재 PDF] --> B[페이지 텍스트·이미지 추출]
    B --> C[Tesseract OCR 사전 필터]
    C --> D[Gemini 코드 구조화]
    D --> E[표준 코드 블록 생성]
    E --> F[파싱·실행 가능성 판정]
    F --> G[Docker 격리 실행]
    G --> H[예상 출력 비교]
    H --> I[JSON·Markdown 보고서]
```

현재 구현의 기본 원칙은 다음과 같다.

- macOS에서는 PDF를 입력 문서로 사용한다.
- 실행 backend는 Docker만 지원한다.
- 코드 블록은 서로 상태를 공유하지 않고 순차적으로 독립 실행한다.
- 플랫폼은 교재 원고를 자동 수정하지 않고 검수 근거를 제공한다.
- 데이터베이스나 웹 서버 없이 로컬 파일 시스템으로 단계별 산출물을 전달한다.
- 최종 판단은 Markdown 및 JSON 보고서를 검토하는 사람이 수행한다.

## 2. 지원 환경과 사전 준비

### 2.1 필수 구성 요소

| 항목 | 용도 | 확인 명령 |
| --- | --- | --- |
| macOS Apple Silicon | 현재 `.pkg` 배포 대상 | `uname -m` |
| Python 3.11 이상 | 소스 설치 및 개발 | `python3 --version` |
| Docker Desktop | 코드 격리 실행과 실행 image 준비 | `docker version` |
| Tesseract OCR | PDF 이미지의 코드 가능성 판정 | `tesseract --version` |
| Gemini API key | 코드·입력·출력 구조화 | `.env`의 `GEMINI_API_KEY` |
| 네트워크 | Gemini 호출과 최초 Docker image build | API 및 registry 연결 |

Docker Desktop과 Tesseract는 QA Platform `.pkg`에 포함되지 않는다. 사용자가 별도로 설치해야 하며, 파이프라인 실행 시 Docker daemon도 실행 중이어야 한다.

macOS에서 Tesseract는 Homebrew로 설치할 수 있다.

```bash
brew install tesseract
```

macOS에는 HWP 5.x를 직접 자동 분석하는 엔진이 없다. HWP 문서는 한컴오피스 등에서 PDF로 변환한 뒤 `input_pdf`로 지정한다. Windows의 HWP 직접 입력은 한컴오피스 COM, `pywin32`, 보안 모듈이 갖춰진 환경에서만 사용할 수 있다. DOCX 전용 추출 엔진은 현재 제공하지 않는다.

### 2.2 설치 방식

내부 배포용 `.pkg`가 있는 경우 다음과 같이 설치한다.

```bash
sudo installer -pkg qa-platform-macos-arm64.pkg -target /
qa-platform --help
```

기본 설치 위치는 다음과 같다.

```text
CLI wrapper: /usr/local/bin/qa-platform
애플리케이션: /Library/Application Support/QA Platform/app/qa-platform/
```

소스에서 실행하려면 다음과 같이 가상 환경과 프로젝트를 설치한다.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

## 3. 빠른 실행 절차

### 3.1 Workspace 생성

```bash
qa-platform init-config
```

기본 workspace는 `~/Documents/QA Platform`이며 다음 구조가 생성된다.

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

다른 위치를 사용하려면 명시적으로 지정한다.

```bash
qa-platform init-config --workspace-root "/path/to/qa-workspace"
```

이미 존재하는 설정을 다시 만들 때만 `--force`를 사용한다. 이 옵션은 기존 설정 파일을 덮어쓰므로 내용을 먼저 확인한다.

### 3.2 API key 설정

workspace의 `.env` 파일에 Gemini API key를 입력한다.

```dotenv
GEMINI_API_KEY=your_api_key_here
```

API key는 JSON config에 작성하지 않는다. 실제 `.env`도 Git에 커밋하지 않는다.

### 3.3 입력 문서 배치

PDF를 workspace의 `input/` 아래에 두고 config의 `paths.input_pdf`가 해당 파일을 가리키도록 설정한다.

```text
~/Documents/QA Platform/input/chapter01.pdf
```

### 3.4 실행 환경 점검

```bash
qa-platform doctor
```

`doctor`는 다음 항목을 비파괴적으로 점검한다.

- workspace와 config 파일
- `.env` 파일
- `/usr/local/bin`의 `PATH` 포함 여부
- Tesseract 실행 파일
- Docker CLI와 Docker daemon
- 선택적 resource directory

별도 workspace나 config를 사용할 수도 있다.

```bash
qa-platform doctor \
  --workspace-root "/path/to/qa-workspace" \
  --config "/path/to/qa-workspace/config/qa_pipeline.local.json"
```

`[FAIL] path: /usr/local/bin is not on PATH`가 표시되면 우선 절대 경로로 실행 가능 여부를 확인한다.

```bash
/usr/local/bin/qa-platform doctor
```

Docker 항목이 실패하면 Docker Desktop을 실행한 뒤 `docker version`과 `qa-platform doctor`를 다시 수행한다.

### 3.5 전체 파이프라인 실행

기본 workspace를 사용할 때는 다음 명령으로 실행한다.

```bash
qa-platform run
```

설정과 workspace를 직접 지정할 수도 있다.

```bash
qa-platform run \
  --workspace-root "/path/to/qa-workspace" \
  --config "/path/to/qa-workspace/config/qa_pipeline.local.json" \
  --env-file "/path/to/qa-workspace/.env"
```

다음 형식도 호환성을 위해 `run` 명령으로 처리한다.

```bash
qa-platform --config config/qa_pipeline.local.json
```

완료되면 CLI가 정규화된 block 디렉터리, 실행 디렉터리, Markdown 보고서와 요약 JSON 경로를 출력한다.

## 4. 현재 설정 파일

### 4.1 권장 기본 예제

현재 설정 기준 파일은 `config/qa_pipeline.example.json`이다. macOS PDF 검수에 사용할 수 있는 전체 예시는 다음과 같다.

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

`workspace_root`가 상대 경로이면 config 파일이 있는 디렉터리를 기준으로 해석한다. 위 파일을 `workspace/config/`에 둘 경우 `..`는 workspace를 뜻한다. 나머지 상대 경로는 결정된 workspace 아래에서 해석한다.

### 4.2 `project` 항목

| 항목 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `book_id` | 아니요 | `default` | 결과 경로를 구분하는 프로젝트 식별자 |
| `chapter_number` | 예 | 없음 | 대상 장 번호 |
| `python_version` | 아니요 | `3.11` | Docker 실행 Python 버전 |
| `extractor_engine` | 아니요 | `auto` | `auto`, `pdf`, `windows_com` 중 선택 |
| `keep_temp_images` | 아니요 | `false` | 추출 중간 이미지 보존 여부 |
| `session_id` | 아니요 | 자동 생성 | 동일한 추출·실행 세션 식별자를 직접 지정 |
| `security_module_name` | 아니요 | `SecurityModule` | Windows HWP COM 보안 모듈 이름 |

`python_version`은 반드시 `"3.11"` 또는 `"3.11.9"`처럼 문자열로 작성한다. 숫자 `3.11`이나 `"latest"`는 허용되지 않는다. Python 버전은 `execution.docker.python_version`이 아니라 `project.python_version`에만 작성한다.

### 4.3 `paths` 항목

| 항목 | 기본값 | 설명 |
| --- | --- | --- |
| `workspace_root` | `~/Documents/QA Platform` | 모든 상대 경로의 기준 |
| `env_file` | `<workspace>/.env` | 환경변수 파일 |
| `input_pdf` | 없음 | macOS 및 PDF 엔진 입력 |
| `input_hwp` | 없음 | Windows COM 엔진 입력 |
| `resource_root` | 자동 탐색 | 선택적 bundled resource 경로 |
| `tesseract_cmd` | PATH 탐색 | Tesseract 명령명 또는 경로 |
| `output_root` | `extracted_blocks` | 표준 block 출력 루트 |
| `work_root` | `run/document_extraction` | 추출 중간 산출물 루트 |
| `run_root` | `run` | 실행 결과와 보고서 루트 |

`docker`, `tesseract`처럼 path separator가 없는 값은 명령명으로 취급하여 `PATH`에서 찾는다. `bin/docker`, `bin/tesseract`처럼 경로 형태인 상대값은 workspace 기준으로 해석한다.

### 4.4 `execution` 항목

`execution.backend`는 현재 `docker`만 허용한다. 로컬 Python fallback은 제공하지 않는다.

| Docker 항목 | 기본값 | 설명 |
| --- | --- | --- |
| `docker_cmd` | PATH 탐색 | Docker CLI 명령명 또는 경로 |
| `image` | 자동 결정 | 직접 지정할 Docker image |
| `install_requirements` | 빈 목록 | 모든 block에 추가할 공통 pip requirement |
| `dependency_image_repository` | `qa-platform-python` | dependency image 저장소 이름 |
| `timeout_seconds` | `5` | block별 실행 제한 시간 |
| `output_limit_chars` | `20000` | stdout와 stderr별 최대 보존 문자 수 |
| `memory_limit` | `256m` | 컨테이너 메모리 제한 |
| `cpu_limit` | `0.5` | 컨테이너 CPU 제한 |
| `pids_limit` | `64` | 컨테이너 PID 제한 |
| `work_tmpfs_size` | `64m` | `/work` tmpfs 크기 |
| `temp_tmpfs_size` | `64m` | `/tmp` tmpfs 크기 |
| `user` | `10001:10001` | 컨테이너의 비권한 사용자 |
| `image_build_context` | 없음 | 사용자 지정 build context |
| `image_build_dockerfile` | 없음 | 사용자 지정 Dockerfile |
| `image_build_timeout_seconds` | `300` | image build 제한 시간 |

설정 제약은 다음과 같다.

- `image`와 `install_requirements`는 동시에 사용할 수 없다.
- `image_build_context`와 `image_build_dockerfile`은 반드시 함께 지정한다.
- 알 수 없는 `execution.docker` 항목은 설정 오류로 처리한다.
- `project.python_version`과 실제 image의 Python 버전이 맞아야 한다.

### 4.5 경로와 override 우선순위

Workspace는 다음 순서로 결정된다.

1. CLI `--workspace-root`
2. config `paths.workspace_root`
3. 환경변수 `QA_PLATFORM_WORKSPACE`
4. `~/Documents/QA Platform`

Env file은 다음 순서로 결정된다.

1. CLI `--env-file`
2. config `paths.env_file`
3. 환경변수 `QA_PLATFORM_ENV_FILE`
4. `<workspace_root>/.env`

Resource directory는 다음 후보를 순서대로 탐색한다.

1. config 또는 CLI의 `resource_root`
2. 환경변수 `QA_PLATFORM_RESOURCE_DIR`
3. 실행 파일 옆 `resources/`
4. `/Library/Application Support/QA Platform/resources`
5. 개발 저장소의 `resources/`

현재 macOS `.pkg`는 resource directory를 필수로 설치하지 않으므로, 해당 디렉터리가 없다는 이유만으로 `doctor`가 실패하지는 않는다.

## 5. 표준 코드 블록 계약

### 5.1 파일과 섹션 순서

추출 결과 파일은 다음 이름 규칙을 사용한다.

```text
block_001.txt
block_002.txt
block_003.txt
```

파일명은 `block_` 뒤에 3자리 숫자와 `.txt`가 오는 형식이어야 한다. 실행기는 파일명 오름차순으로 처리한다. 번호가 중간에 빠져 있으면 실행은 계속하지만 `missing_block_numbers` 경고를 manifest와 보고서에 남긴다.

표준 block은 다음 여섯 섹션으로 표현한다.

```text
[META]
[PACKAGES]
[SETUP]
[CODE]
[INPUT]
[OUTPUT]
```

`[META]`, `[PACKAGES]`, `[CODE]`, `[INPUT]`, `[OUTPUT]`은 필수다. `[SETUP]`은 선택 사항이며, 렌더링된 표준 block에는 일관성을 위해 빈 섹션으로 포함될 수 있다. `[CODE]`는 비어 있을 수 없다. 나머지 필수 섹션은 헤더가 존재한다면 내용은 비어 있어도 된다.

UTF-8 또는 UTF-8 BOM 파일을 읽을 수 있고, CRLF와 CR 줄바꿈은 내부에서 LF로 정규화한다. 알 수 없는 섹션, 중복 섹션, 첫 헤더 앞의 본문, 잘못된 META 형식은 파싱 오류다.

### 5.2 전체 예제

```text
[META]
page=12
source_kind=text
code_type=COMPLETE_CODE
execution_mode=script
input_source=generated_sample
output_source=generated_sample
output_determinism=deterministic
stdin_exhaustion=deny

[PACKAGES]
NONE

[SETUP]

[CODE]
a = int(input())
b = int(input())
print(a + b)

[INPUT]
10
20

[OUTPUT]
30
```

### 5.3 섹션별 의미

| 섹션 | 의미 |
| --- | --- |
| `[META]` | 페이지, 출처, 코드 유형, 실행 및 비교 정책 |
| `[PACKAGES]` | 외부 pip requirement 목록. 없으면 비우거나 `NONE` |
| `[SETUP]` | 예제를 독립 실행하기 위해 복원한 선행 정의 |
| `[CODE]` | 교재에서 검수할 주 코드 |
| `[INPUT]` | 코드 프로세스에 전달할 표준 입력 |
| `[OUTPUT]` | 비교할 예상 stdout 또는 기대 오류 텍스트 |

`[SETUP]`과 `[CODE]`는 실행 직전에 한 줄을 띄워 결합된다. `[SETUP]`은 실행 가능성을 위한 문맥이지만, 사용자가 검수해야 하는 핵심 예제는 `[CODE]`에 둔다.

`[PACKAGES]`는 한 줄에 하나의 requirement를 기록한다.

```text
numpy
pandas==2.2.2
scikit-learn>=1.5
```

파서는 각 값을 다음 구조로 보존한다.

```json
{
  "name": "pandas",
  "specifier": "==2.2.2",
  "raw": "pandas==2.2.2"
}
```

### 5.4 META 주요 항목

| 항목 | 허용값 또는 예 | 의미 |
| --- | --- | --- |
| `page` | `12` | 원문 페이지 |
| `source_kind` | `text`, `image` 등 | 추출 출처 |
| `code_type` | `COMPLETE_CODE` | 정상 실행 가능한 완성 코드 |
| `code_type` | `INCOMPLETE_SNIPPET` | 의도적으로 불완전한 조각 코드 |
| `code_type` | `ERROR_FINDING` | 오류 찾기 목적의 예제 |
| `execution_mode` | `script`, `repl` | 실행 표현 방식 |
| `input_source` | `textbook`, `generated_sample`, `empty` | 입력값 출처 |
| `output_source` | `textbook`, `generated_sample`, `empty` | 예상 출력 출처 |
| `output_determinism` | `deterministic`, `nondeterministic` | 출력 비교 여부 |
| `stdin_exhaustion` | `deny`, `accept` | 정확한 stdin 소진 EOF 허용 여부 |

`[META]`의 각 줄은 `key=value` 형식이어야 한다. 알려진 enum 항목에 허용되지 않은 값이 오면 `invalid_meta`로 처리한다. 알 수 없는 일반 metadata key는 후속 보고를 위해 문자열로 보존할 수 있다.

기본값은 다음과 같다.

- `code_type`: `COMPLETE_CODE`
- `output_determinism`: `deterministic`
- `stdin_exhaustion`: `deny`

`input_source`와 `output_source`는 교재에 있던 값과 시스템이 실행 검증을 위해 만든 샘플을 구분한다. 생성된 샘플은 `generated_sample`, 내용이 없으면 `empty`로 표시한다.

### 5.5 Script와 REPL 실행

`execution_mode=script`는 일반 Python 파일처럼 실행한다. 표현식 결과를 보려면 코드가 직접 `print()`를 호출해야 한다.

`execution_mode=repl`은 대화형 셸이나 노트북에서 마지막 표현식이 표시되는 교재 예제를 재현하기 위한 모드다. 실행기는 가능한 경우 `repl_executable.py`를 만들고 display hook을 적용한다. 변환이 안전하지 않으면 script 방식으로 fallback하며 실제 전략은 결과 metadata에 기록된다.

### 5.6 파싱 오류 유형

| 오류 | 의미 |
| --- | --- |
| `missing_section` | 필수 섹션이 없음 |
| `duplicate_section` | 같은 섹션이 둘 이상 존재 |
| `content_before_header` | 첫 섹션 앞에 본문이 존재 |
| `empty_code` | `[CODE]`가 비어 있음 |
| `invalid_meta` | META가 `key=value`가 아니거나 enum 값이 잘못됨 |
| `unknown_section` | 지원하지 않는 섹션 헤더 |
| `read_error` | 파일 읽기 또는 인코딩 오류 |

파싱에 실패해도 `block.json`을 생성하고, 컨테이너 실행은 생략한 채 `parse_error` 결과로 연결한다.

## 6. Parser 산출물 계약

각 block은 실행 디렉터리에 독립 작업 공간을 갖는다.

```text
blocks/block_001/
├── block.txt
├── block.json
├── normalized.py
├── stdin.txt
├── repl_executable.py  # REPL 변환 시에만 생성
└── result.json
```

파일 역할은 다음과 같다.

| 파일 | 생성 주체 | 역할 |
| --- | --- | --- |
| `block.txt` | ChapterRunner | 원본 표준 block의 실행용 사본 |
| `block.json` | BlockSpecParser | 구조화된 파싱 결과 또는 파싱 오류 |
| `normalized.py` | BlockSpecParser | SETUP과 CODE를 결합한 실행 파일 |
| `stdin.txt` | BlockSpecParser | 컨테이너 프로세스에 전달할 stdin |
| `repl_executable.py` | REPL artifact 준비 단계 | REPL 표시 동작을 반영한 선택적 실행 파일 |
| `result.json` | BlockExecutor | 실행·비교·skip 결과 |

성공한 `block.json`의 핵심 구조는 다음과 같다.

```json
{
  "parse_success": true,
  "block_id": "block_001",
  "spec": {
    "code": "a = int(input())\nb = int(input())\nprint(a + b)\n",
    "stdin": "10\n20\n",
    "packages": [],
    "expected_output": "30\n",
    "meta": {
      "page": "12",
      "execution_mode": "script"
    },
    "setup_code": ""
  }
}
```

파싱 실패 예시는 다음과 같다.

```json
{
  "parse_success": false,
  "block_id": "block_001",
  "error": {
    "type": "missing_section",
    "message": "Missing [CODE] section.",
    "line": null
  }
}
```

## 7. Docker 실행 설계

### 7.1 독립 실행 원칙

각 코드 블록은 새 컨테이너에서 실행한다. 이전 블록에서 만든 변수, import 상태, 파일 또는 프로세스를 다음 블록이 이어받지 않는다. 이는 독자가 해당 예제만 실행했을 때 재현 가능한지를 검수하기 위한 정책이다.

ChapterRunner는 다음 순서로 동작한다.

1. `block_###.txt` 파일을 오름차순으로 수집한다.
2. 모든 block을 독립 작업 디렉터리로 복사하고 파싱한다.
3. 챕터 전체의 지원 가능한 외부 package requirement를 집계한다.
4. Docker image를 준비한다.
5. block을 순차적으로 실행하거나 skip 처리한다.
6. `results.jsonl`과 manifest를 block마다 갱신한다.
7. 챕터 JSON 및 Markdown 보고서를 생성한다.

### 7.2 Image 자동 준비

외부 package가 없는 경우 기본 image tag는 다음 형식이다.

```text
qa-platform-python-stdlib:3.11
```

지원되는 외부 package가 있으면 Python 버전과 정렬된 requirement 집합으로 hash를 계산하여 다음 형태의 dependency image를 사용한다.

```text
qa-platform-python:3.11-deps-a1b2c3d4
```

같은 Python 버전과 같은 requirement 집합은 같은 tag를 사용하므로 기존 image를 재사용할 수 있다. image가 없으면 런타임이 임시 build context에 내장 Dockerfile과 `requirements.txt`를 만들고 자동으로 build한다. 매 block 실행 시 `pip install`하지 않으므로 반복 실행의 속도와 재현성을 확보한다.

표준 라이브러리는 dependency image 대상에서 제외한다. 지원하지 않는 외부 package는 `unsupported_package`, `tkinter`나 `turtle` 같은 headless 환경 의존 모듈은 `environment_dependent`로 판정한다.

### 7.3 컨테이너 보안과 자원 제한

개념적인 실행 명령은 다음과 같다.

```bash
docker run --rm \
  --network none \
  --memory 256m \
  --cpus 0.5 \
  --pids-limit 64 \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /work:rw,size=64m \
  --tmpfs /tmp:rw,size=64m \
  -v /host/run/blocks/block_001:/input:ro \
  -w /work \
  --user 10001:10001 \
  qa-platform-python-stdlib:3.11 \
  python /input/normalized.py
```

핵심 제한은 다음과 같다.

- `--network none`: 검수 코드의 네트워크 접근 차단
- `--read-only`: 컨테이너 루트 파일 시스템 쓰기 차단
- `/input:ro`: 원본 실행 산출물 읽기 전용 마운트
- `/work`, `/tmp`: 크기가 제한된 임시 쓰기 공간
- 비권한 사용자: root 권한으로 예제 코드를 실행하지 않음
- capability 제거와 `no-new-privileges`: 권한 상승 방지
- CPU, 메모리, PID 제한: 자원 폭주 방지
- block당 timeout: 무한 루프와 장시간 실행 차단
- stdout/stderr 길이 제한: 무한 출력으로부터 호스트 보호
- `--rm`: 실행 종료 후 컨테이너 삭제

상대 경로로 파일을 생성하는 정상 예제를 허용하기 위해 실행 작업 디렉터리 `/work`는 쓰기 가능하게 유지한다. 작업 결과는 tmpfs에만 남고 컨테이너 삭제 시 제거된다.

### 7.4 stdin과 출력 수집

`stdin.txt` 내용은 shell redirection이 아니라 호스트 실행기가 subprocess stdin으로 직접 전달한다. 실행기는 다음 값을 수집한다.

- exit code
- stdout와 stderr
- 실행 시간 `duration_ms`
- timeout 여부
- stdout/stderr 잘림 여부
- 실제 실행 전략과 metadata

기본 보존 한도는 stdout와 stderr 각각 20,000자다. 한도를 넘으면 앞부분만 저장하고 `stdout_truncated` 또는 `stderr_truncated`를 `true`로 기록한다.

## 8. 실행 결과 판정

### 8.1 상태

| 상태 | 의미 |
| --- | --- |
| `passed` | 실행 정책과 예상 결과를 만족 |
| `failed` | 파싱·실행·출력 비교 또는 실행 환경 준비 실패 |
| `skipped` | 자동 실행 대상이 아니거나 외부 조건이 필요한 코드 |

대표적인 skip 대상은 다음과 같다.

- `code_type=INCOMPLETE_SNIPPET`
- `code_type=ERROR_FINDING`
- 실행 전에 존재해야 하는 외부 파일을 읽는 코드
- `tkinter`, `turtle` 등 GUI 또는 headless 환경 의존 코드

### 8.2 출력 비교 규칙

정상 종료한 deterministic block에 `[OUTPUT]`이 있으면 stdout과 비교한다.

- 각 줄 끝의 공백 차이는 무시한다.
- 마지막 개행 유무는 무시한다.
- 줄 시작 공백과 의미 있는 전체 공백은 보존한다.
- `input("prompt")`가 만든 terminal prompt/입력 echo 차이를 제한적으로 정규화한다.
- REPL 표현 결과와 일부 pandas 표시 형식은 지원 범위 안에서 정규화한다.
- 예상 출력이 비어 있으면 실행 성공 여부만 판단하고 `output_matched=null`로 기록한다.
- `output_determinism=nondeterministic`이면 stdout 문자열 비교를 생략한다.

정상 종료했지만 deterministic 예상 출력과 다르면 `failed`와 `output_mismatch`가 된다.

`[OUTPUT]`에 의도된 예외의 타입과 메시지가 기록되어 있고 실제 마지막 예외와 일치하는 오류 찾기 형태는 정책에 따라 성공으로 판정될 수 있다. 또한 `stdin_exhaustion=accept`인 경우 실제 오류가 정확히 `EOFError: EOF when reading a line`일 때만 입력 소진을 허용한다. 임의로 발생시킨 다른 EOFError까지 허용하지 않는다.

### 8.3 오류 category

| Category | 의미 |
| --- | --- |
| `parse_error` | 표준 block 파싱 실패 |
| `syntax_error` | Python 문법 오류 |
| `name_error` | 정의되지 않은 이름 사용 |
| `module_not_found` | module import 실패 |
| `missing_required_file` | 실행에 필요한 외부 파일 없음 |
| `input_required_or_invalid` | stdin 부족 또는 입력 형식 오류 |
| `timeout` | 실행 제한 시간 초과 |
| `output_mismatch` | 예상 출력과 실제 stdout 불일치 |
| `runtime_error` | 그 밖의 Python 실행 오류 |
| `unsupported_package` | 지원하지 않는 외부 package |
| `environment_dependent` | GUI나 로컬 환경에 의존 |
| `executor_input_error` | Docker나 실행 산출물 준비 오류 |
| `incomplete_snippet` | 불완전 예제라 실행을 건너뜀 |
| `error_finding` | 오류 찾기 목적 예제라 실행을 건너뜀 |
| `runner_error` | 챕터 처리 중 예상하지 못한 내부 오류 |

### 8.4 `result.json` 예제

```json
{
  "block_id": "block_001",
  "status": "passed",
  "category": null,
  "exit_code": 0,
  "duration_ms": 120,
  "stdout": "30\n",
  "stderr": "",
  "stdout_truncated": false,
  "stderr_truncated": false,
  "error_type": null,
  "error_message": null,
  "expected_output": "30\n",
  "output_matched": true,
  "meta": {
    "page": "12",
    "execution_mode": "script"
  }
}
```

실패 예시는 다음과 같다.

```json
{
  "block_id": "block_002",
  "status": "failed",
  "category": "name_error",
  "exit_code": 1,
  "duration_ms": 90,
  "stdout": "",
  "stderr": "Traceback ... NameError: name 'a' is not defined",
  "stdout_truncated": false,
  "stderr_truncated": false,
  "error_type": "NameError",
  "error_message": "name 'a' is not defined",
  "expected_output": "30\n",
  "output_matched": null,
  "meta": {
    "page": "13"
  }
}
```

## 9. 결과 디렉터리와 보고서

기본 설정으로 실행하면 다음 구조가 만들어진다.

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
                    ├── stdin.txt
                    └── result.json
```

각 파일의 역할은 다음과 같다.

| 파일 | 역할 |
| --- | --- |
| `run_manifest.json` | 시작·완료 시각, 전체/처리/통과/실패/skip 수와 실행 상태 |
| `results.jsonl` | block ID, 상태, category, `result.json` 경로 색인 |
| `qa_pipeline.json` | 추출·챕터 실행·Docker image를 연결한 전체 요약 |
| `chapter_error_report.json` | 후처리와 UI 연동에 적합한 구조화 보고서 |
| `chapter_error_report.md` | 저자와 편집자가 읽는 검토 보고서 |
| `blocks/*/result.json` | 개별 block의 stdout, stderr, 오류, 비교 결과 |

Markdown 보고서에는 전체 실행 요약, category별 수, 입력 경고, 실패 및 skip 우선순위와 block 상세가 포함된다. 상세 항목에는 페이지, 코드, 입력, package, 예상 출력, 실제 출력, 오류 메시지와 원본 block 근거가 기록된다.

중간 산출물은 문제 재현과 감사 근거이므로 현재 실행에서는 자동 삭제하지 않는다. 운영자가 확인한 뒤 workspace의 `extracted_blocks/`와 `run/`을 별도로 정리할 수 있다.

## 10. macOS 패키지 빌드와 검증

GitHub에 공개된 소스만으로 Apple Silicon용 `.pkg`를 직접 만들 수 있다. 현재 저장소는 GitHub Actions를 이용한 자동 패키지 빌드를 제공하지 않으므로, 사용자가 Apple Silicon macOS에서 저장소를 clone한 뒤 로컬로 빌드해야 한다.

빌드 과정은 PyInstaller로 `qa-platform` 실행 파일을 만든 다음 macOS의 `pkgbuild`와 `productbuild`를 이용해 installer package로 묶는다.

### 10.1 빌드 환경 확인

필요한 환경은 다음과 같다.

- Apple Silicon 기반 macOS
- Python 3.11 이상
- Git
- macOS의 `pkgbuild`, `productbuild`
- Python package를 내려받기 위한 네트워크 연결

터미널에서 아키텍처와 명령을 확인한다.

```bash
uname -m
python3.11 --version
git --version
command -v pkgbuild
command -v productbuild
```

`uname -m`은 `arm64`를 출력해야 한다. `pkgbuild` 또는 `productbuild`가 없으면 macOS와 Xcode Command Line Tools 상태를 확인한다.

```bash
xcode-select --install
```

### 10.2 GitHub 소스 clone

```bash
git clone https://github.com/BaekSukSu/QA_Platform.git
cd QA_Platform
```

특정 공개 버전이나 tag를 빌드할 때는 해당 tag로 이동한 뒤 진행한다.

```bash
git fetch --tags
git checkout v0.1.0
```

`v0.1.0` tag가 실제로 만들어진 이후에만 위 checkout 명령을 사용할 수 있다. tag가 없다면 기본 `main` 브랜치의 현재 소스를 빌드한다.

### 10.3 Python 가상환경과 패키징 dependency 설치

프로젝트 루트에서 전용 가상환경을 만들고 packaging extra를 설치한다.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[macos-pkg]'
```

`macos-pkg` extra에는 PyInstaller가 포함된다. 애플리케이션 실행에 필요한 dependency도 함께 설치된다.

### 10.4 미서명 `.pkg` 생성

```bash
python -m tools.macos.build_pkg --version 0.1.0
```

빌드 과정에서 다음 중간 산출물이 생성된다.

```text
build/macos/executable/       PyInstaller 실행 파일
build/macos/pyinstaller-work/ PyInstaller 작업 파일
build/macos/pyinstaller-spec/ PyInstaller spec 파일
build/macos/payload/          pkg 설치 payload
build/macos/intermediate/     component pkg
```

최종 결과는 다음 경로에 생성된다.

```text
dist/qa-platform-macos-arm64.pkg
```

다른 출력 경로가 필요하면 `--output-pkg`를 지정한다.

```bash
python -m tools.macos.build_pkg \
  --version 0.1.0 \
  --output-pkg dist/qa-platform-0.1.0-macos-arm64.pkg
```

`--sign-identity`를 생략한 결과는 내부 시험용 미서명 package다.

### 10.5 생성 결과 확인

파일이 생성됐는지 확인한다.

```bash
ls -lh dist/qa-platform-macos-arm64.pkg
```

설치 payload에 CLI wrapper와 애플리케이션이 포함됐는지 확인한다.

```bash
pkgutil --payload-files dist/qa-platform-macos-arm64.pkg | rg "qa-platform|QA Platform"
```

정상적인 payload에는 `/usr/local/bin/qa-platform` wrapper와 `/Library/Application Support/QA Platform/app/qa-platform/` 아래의 애플리케이션 파일이 포함된다.

### 10.6 설치 smoke test

내부 시험용 미서명 패키지는 별도 테스트 머신에서 다음 smoke test를 수행한다. 설치 명령은 시스템 경로를 변경하므로 실행 대상에 주의한다.

```bash
sudo installer -pkg dist/qa-platform-macos-arm64.pkg -target /
pkgutil --pkg-info com.qa-platform.cli
command -v qa-platform
qa-platform --help
qa-platform init-config --workspace-root /tmp/qa-platform-installed-smoke
qa-platform doctor --workspace-root /tmp/qa-platform-installed-smoke
```

`command -v qa-platform`은 일반적인 설치 환경에서 `/usr/local/bin/qa-platform`을 출력해야 한다. `doctor`에서는 Docker Desktop, Docker daemon과 Tesseract가 별도 설치되어 있는지도 확인한다.

빌드된 `.pkg`에는 Docker Desktop, Tesseract와 Gemini API key가 포함되지 않는다. 설치 후 사용자가 각각 준비해야 한다.

### 10.7 서명된 package 생성

외부 배포에는 Developer ID Installer 인증서 서명과 Apple notarization 검증이 추가로 필요하다.

```bash
python -m tools.macos.build_pkg \
  --version 0.1.0 \
  --sign-identity "Developer ID Installer: YOUR TEAM NAME"
```

서명 결과는 다음 명령으로 확인할 수 있다.

```bash
pkgutil --check-signature dist/qa-platform-macos-arm64.pkg
```

`--sign-identity`는 macOS Keychain에 설치된 실제 Developer ID Installer identity와 정확히 일치해야 한다. 서명만으로 notarization이 완료되는 것은 아니므로 외부 배포 시 Apple 공증 절차를 별도로 수행한다.

### 10.8 GitHub 배포 방식

`.pkg`는 크기가 있는 빌드 산출물이므로 source tree에 commit하지 않는다. `.gitignore`도 `dist/`와 `*.pkg`를 제외한다.

공식 설치 파일을 제공하려면 다음 방식이 적합하다.

1. 검증된 commit에 `v0.1.0` 같은 version tag를 만든다.
2. 해당 tag의 소스로 `.pkg`를 다시 빌드한다.
3. 설치 및 `doctor` smoke test를 수행한다.
4. GitHub Release를 생성한다.
5. `.pkg`를 Release asset으로 첨부한다.

현재 저장소에는 `.github/workflows/` 기반 자동 빌드가 없다. 따라서 GitHub의 source code archive를 내려받는 것만으로 `.pkg`가 자동 생성되지는 않으며, 위 로컬 빌드 명령을 실행해야 한다.

## 11. 개발 테스트

전체 테스트는 다음과 같이 실행한다.

```bash
python -m pytest -q
```

Docker daemon이 필요하지 않은 단위·계약·통합 테스트만 실행하려면 다음 명령을 사용한다.

```bash
python -m pytest -q -m "not docker"
```

실제 Docker 수명주기까지 검증하려면 Docker Desktop을 실행한 상태에서 docker marker 테스트를 포함해야 한다. 테스트를 공개 저장소에 올릴 때는 실제 교재 원문, 실제 API key, 사용자 절대경로 대신 합성 fixture와 placeholder를 사용한다.

## 12. 문제 해결

### Docker CLI 또는 daemon 오류

```bash
docker version
qa-platform doctor
```

Docker Desktop이 설치되어 있어도 daemon이 시작되지 않았으면 실행할 수 없다. 별도 Docker CLI 위치를 사용하는 경우 `execution.docker.docker_cmd`에 경로를 지정한다.

### Tesseract를 찾지 못하는 경우

```bash
brew install tesseract
/opt/homebrew/bin/tesseract --version
```

필요하면 `paths.tesseract_cmd`에 절대경로를 지정한다.

### Gemini API key 오류

`.env` 파일 위치와 다음 형식을 확인한다.

```dotenv
GEMINI_API_KEY=your_api_key_here
```

공백뿐인 값, 잘못된 env file 경로, config JSON 안에 key를 넣은 경우는 해결되지 않는다.

### Docker image build 실패

- 최초 build에 필요한 네트워크 연결을 확인한다.
- `project.python_version` 형식을 확인한다.
- `[PACKAGES]` requirement가 pip에서 설치 가능한지 확인한다.
- custom build를 사용한다면 context와 Dockerfile을 모두 지정했는지 확인한다.
- `image_build_timeout_seconds`가 환경에 비해 지나치게 짧지 않은지 확인한다.

### 결과가 `skipped`인 경우

`chapter_error_report.md`의 skip category와 주요 근거를 확인한다. 불완전 코드나 오류 찾기 문제는 자동 실패로 다루지 않으며, 외부 파일과 GUI 의존 코드도 현재 격리 환경에서 실행하지 않는다.

## 13. 보안과 공개 저장소 정책

다음 항목은 GitHub에 올리지 않는다.

- `.env`와 실제 Gemini API key
- 원본 교재 PDF·HWP와 저작권이 있는 이미지 및 텍스트
- `config/*.local.json`
- 실제 운영 workspace와 사용자 절대경로
- `extracted_blocks/`, `data/`, `run/`, `tmp/`, `logs/`
- `.venv/`, `build/`, `dist/`, `*.pkg`
- 코드 서명 인증서, 개인키와 provisioning 자료

공개 가능한 항목은 다음과 같다.

- 애플리케이션 소스 코드
- `config/qa_pipeline.example.json`
- 실제 비밀값이 없는 `.env.example`
- 이 통합 가이드와 루트 `README.md`
- 합성 데이터만 사용하는 테스트와 fixture
- Dockerfile, 패키징 스크립트와 라이선스 파일

커밋 전에는 다음 명령으로 포함 대상을 확인한다.

```bash
git status --short
git diff --cached --stat
git diff --cached
```

비밀값 검사는 최소한 API key 패턴, 개인 이메일, 절대경로와 원문 데이터가 staged diff에 없는지 확인한다. 이미 과거 commit에 비밀값이 들어갔다면 현재 파일만 삭제하는 것으로는 충분하지 않으며, key 폐기·재발급과 Git history 정리가 필요하다.

## 14. 현재 제약사항

- macOS 직접 입력 계약은 PDF다.
- HWP 직접 자동 분석은 Windows COM 환경에서만 제한적으로 가능하다.
- DOCX 전용 추출 엔진은 없다.
- Docker 이외 실행 backend는 없다.
- 전체 파이프라인과 ChapterRunner는 동기식 순차 처리다.
- GUI와 웹 서비스는 제공하지 않는다.
- OCR과 Gemini 구조화에는 오인식 가능성이 있다.
- 코드 블록은 기본적으로 서로의 실행 상태를 공유하지 않는다.
- 자동 결과는 편집 결정을 대신하지 않으며 사람이 최종 검토해야 한다.
- 미서명 `.pkg`는 내부 시험용이며 외부 공식 배포 상태를 뜻하지 않는다.

## 15. 운영 체크리스트

실행 전:

- [ ] Docker Desktop 설치 및 daemon 실행
- [ ] Tesseract 설치 및 경로 확인
- [ ] `.env`에 Gemini API key 설정
- [ ] 입력 PDF와 chapter 번호 확인
- [ ] `qa-platform doctor` 통과

실행 후:

- [ ] `qa_pipeline.json`에서 추출·실행 경로와 Docker image 확인
- [ ] `run_manifest.json`에서 전체 block 수와 완료 상태 확인
- [ ] `chapter_error_report.md`에서 실패와 skip 원인 검토
- [ ] `output_mismatch`의 예상·실제 출력 비교
- [ ] OCR 또는 문맥 복원 오류가 의심되는 원문 페이지 재검토
- [ ] 외부 공유 전 API key, 원문, 절대경로 제거 확인
