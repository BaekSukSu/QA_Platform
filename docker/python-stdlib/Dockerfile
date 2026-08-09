ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt /tmp/qa-requirements.txt

RUN if [ -s /tmp/qa-requirements.txt ]; then \
        python -m pip install --no-cache-dir -r /tmp/qa-requirements.txt; \
    fi \
    && rm -f /tmp/qa-requirements.txt

RUN groupadd --gid 10001 qa \
    && useradd \
        --uid 10001 \
        --gid 10001 \
        --no-create-home \
        --shell /usr/sbin/nologin \
        qa \
    && mkdir -p /work \
    && chown 10001:10001 /work

USER 10001:10001
WORKDIR /work

CMD ["python", "--version"]
