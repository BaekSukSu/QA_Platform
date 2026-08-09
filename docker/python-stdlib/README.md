# Python 표준 라이브러리 실행 이미지

이 Dockerfile은 QA_Platform MVP 3에서 Python 표준 라이브러리 코드 block을 실행할 때 사용하는 로컬 이미지를 만든다.

## 사전 조건

- Docker CLI가 설치되어 있어야 한다.
- Docker daemon 또는 Docker Desktop이 실행 중이어야 한다.
- Windows에서는 Docker Desktop의 WSL 2 backend와 Linux container mode를 사용한다.

## 이미지 빌드

QA Platform은 실행 전에 `project.python_version`과 일치하는 Docker image를 준비한다. image가 없거나 image 내부의 실제 Python 버전이 요청한 버전과 다르면 Python 코드에 포함된 기본 Dockerfile template을 임시 build context에 materialize해서 image를 build한다. 이 디렉터리의 Dockerfile은 개발/수동 빌드용 참조 파일이다. 수동으로 빌드하려면 저장소 루트에서 다음 명령을 실행한다.

```bash
docker build \
  --build-arg PYTHON_VERSION=3.11 \
  -t qa-platform-python-stdlib:3.11 \
  docker/python-stdlib
```

`PYTHON_VERSION`과 image tag는 `project.python_version` 값에 맞춘다. 예를 들어 `project.python_version: "3.10"`이면 `PYTHON_VERSION=3.10`, tag는 `qa-platform-python-stdlib:3.10`을 사용한다. 이미지는 프로젝트 디렉터리에 파일로 생성되지 않고 사용자 PC의 Docker image 저장소에 보관된다.

## 이미지 확인

```bash
docker run --rm \
  qa-platform-python-stdlib:3.11 \
  python --version
```

출력은 image tag와 같은 Python 버전 형식이어야 한다.

비루트 실행 사용자도 확인할 수 있다.

```bash
docker run --rm \
  qa-platform-python-stdlib:3.11 \
  sh -c 'python --version && id -u && id -g'
```

UID와 GID는 모두 `10001`이어야 한다.

Docker 저장소에 image가 준비되었는지는 다음 명령으로 확인한다.

```bash
docker image inspect qa-platform-python-stdlib:3.11
```

## 테스트 실행

일반 테스트에서는 실제 Docker 컨테이너 테스트를 제외한다.

```bash
PYTHONPATH=. .venv/bin/pytest -m "not docker" -q
```

Docker daemon과 실행 image가 준비된 환경에서는 다음 명령으로 실제 격리 실행과 ChapterRunner smoke test를 수행한다.

```bash
QA_PLATFORM_RUN_DOCKER_TESTS=1 \
PYTHONPATH=. \
.venv/bin/pytest -m docker -q
```

테스트 또는 실행 후 QA_Platform이 만든 컨테이너가 남아 있는지 확인한다.

```bash
docker ps -a \
  --filter label=qa-platform.managed=true \
  --format '{{.ID}} {{.Names}}'
```

정상적으로 정리되었다면 출력이 없어야 한다.

## MVP 3 정책

- 실행 Python 버전은 Dockerfile의 `PYTHON_VERSION` build arg와 `project.python_version`으로 정한다.
- `project.python_version`이 없으면 기본 안정 버전 `3.11`을 사용한다.
- `[PACKAGES]`가 비어 있거나 표준 라이브러리만 사용하는 block은 기본 표준 라이브러리 image(`qa-platform-python-stdlib:{python_version}`)로 실행한다.
- 지원되는 외부 pip package가 필요한 chapter는 실행 전에 Python 버전과 dependency hash 기반 image(`qa-platform-python:{python_version}-deps-{hash}`)를 자동 build하거나 재사용한다.
- 지원되지 않는 외부 package가 `[PACKAGES]`에 선언되었거나 import에서 감지된 block은 `unsupported_package`로 기록한다.
- `turtle`, `tkinter`는 pip 설치 대상이 아니라 표준 라이브러리 GUI/environment module이다. Docker headless 환경에서 실행할 수 없으면 package 오류가 아니라 `environment_dependent`로 분류한다.
- executor는 image를 자동으로 pull하지 않는다.
- image가 없거나 image 내부의 실제 Python 버전이 요청한 버전과 다르면 QA Platform이 image를 build한다.
- build 후에도 image가 없거나 Python 버전이 일치하지 않으면 block 결과를 `executor_input_error`로 기록한다.
- block마다 이 image로 새 컨테이너를 생성하고 실행 후 삭제한다.
