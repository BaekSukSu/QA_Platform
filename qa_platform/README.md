# QA Platform 패키지 메모

## macOS CLI pkg 배포 전제

- Docker Desktop은 별도로 설치하고 실행 중이어야 한다.
- Tesseract는 별도로 설치하며, macOS 기본 안내는 `brew install tesseract`다.
- `qa-platform doctor`로 Docker CLI, Docker daemon, Tesseract, config, `.env`, workspace 상태를 확인할 수 있다.
- 사용자 workspace 기본값은 `~/Documents/QA Platform`이다.
- `qa-platform init-config`는 기본 workspace, config, `.env`, 입력/출력 디렉토리를 생성한다.
- macOS 배포본은 `.pkg` installer로 제공한다.
- installer는 `/usr/local/bin/qa-platform` wrapper와 `/Library/Application Support/QA Platform/app/qa-platform/` 실행 파일 묶음을 설치한다.
- 내부 테스트용 완료 기준은 unsigned `.pkg`를 실제 설치한 뒤 `qa-platform --help`, `qa-platform init-config`, `qa-platform doctor`가 설치된 wrapper 기준으로 실행되는 것이다.

## Block metadata: `execution_mode`

추출 단계는 표준 `block_###.txt`의 `[META]`에 `execution_mode`를 기록한다. 이 값은 원본 교재의 코드 예제가 일반 스크립트 문맥인지, Python 대화형 세션(REPL) 문맥인지 보존하기 위한 metadata다.

| 값 | 의미 |
| --- | --- |
| `script` | 일반 `.py` 파일, 실습 파일, 독립 프로그램처럼 실행되는 코드 |
| `repl` | `>>>`, `...` 프롬프트나 표현식 echo 출력에 의존하는 대화형 예제 |

Gemini 응답이나 OCR 결과에 `execution_mode`가 있으면 postprocessor는 그 값을 보존한다. 값이 누락되면 기본값은 `script`이며, 명백한 REPL 프롬프트 또는 top-level 표현식 echo 후보가 있고 기대 출력이 있는 경우에만 보수적으로 `repl`로 보정한다.

## 현재 실행 동작

Docker executor는 `[META].execution_mode`를 읽어 실행 방식을 선택한다. `execution_mode=script`이거나 값이 누락된 블록은 기존처럼 `normalized.py`를 실행한다.

`execution_mode=repl` 블록은 `normalized.py`를 원본 정규화 결과로 보존한다. REPL 실행 artifact 변환에 성공하면 executor는 `repl_executable.py`를 생성하고 실행한다. 이 파일은 모듈 본문의 top-level 표현식 문장만 `sys.displayhook(...)` 방식으로 감싸 Python REPL의 표현식 echo를 재현한다.

코드를 AST로 parse할 수 없거나 생성된 실행 소스가 유효하지 않아 변환에 실패하면 executor는 fallback으로 `normalized.py`를 실행한다.

`result.json.meta.execution_strategy`에는 실제 실행 전략이 기록된다. 값은 일반 script 실행의 `script_normalized`, REPL displayhook 실행의 `repl_displayhook`, REPL 변환 실패 후 script fallback 실행의 `repl_transform_failed_script_fallback` 중 하나다.

## Block metadata: `output_determinism`

추출 단계는 `[META]`에 `output_determinism`을 기록한다. 이 값은 같은 입력으로 실행했을 때 출력이 항상 재현 가능한지 나타낸다.

| 값 | 의미 |
| --- | --- |
| `deterministic` | 같은 입력이면 같은 출력이 나오는 코드 |
| `nondeterministic` | `random`, `time`, process id 등으로 출력이나 분기가 실행마다 달라질 수 있는 코드 |

Docker executor는 프로세스가 정상 종료된 뒤 이 값을 출력 비교 정책에 사용한다. `output_determinism=deterministic`이거나 값이 누락된 블록은 `expected_output`과 실제 `stdout`을 비교한다. `output_determinism=nondeterministic` 블록은 출력 비교를 생략하고, 정상 종료 여부만으로 통과 처리한다.

`output_determinism=nondeterministic`은 출력 mismatch만 무시한다. SyntaxError, NameError, timeout 등 실행 실패는 그대로 실패로 기록된다.

## Config와의 경계

`execution_mode`와 `output_determinism`은 사용자가 설정하는 config 항목이 아니다. 이 값들은 각 block의 `[META]`에 들어가는 추출 결과 metadata이며, `config/*.json`의 `project`, `paths`, `execution` 섹션에 추가하지 않는다.
