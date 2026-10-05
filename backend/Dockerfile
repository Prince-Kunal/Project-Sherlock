FROM python:3.12-slim

ARG TYPST_VERSION=0.15.1
ARG TARGETARCH

# poppler-utils: pdftotext for the ATS check. typst: resume PDF rendering (fonts ship in the repo).
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils curl xz-utils ca-certificates \
    && case "${TARGETARCH:-amd64}" in \
         arm64) TYPST_ARCH=aarch64 ;; \
         *) TYPST_ARCH=x86_64 ;; \
       esac \
    && curl -fsSL "https://github.com/typst/typst/releases/download/v${TYPST_VERSION}/typst-${TYPST_ARCH}-unknown-linux-musl.tar.xz" \
       | tar -xJ -C /tmp \
    && mv "/tmp/typst-${TYPST_ARCH}-unknown-linux-musl/typst" /usr/local/bin/typst \
    && rm -rf /tmp/typst-* /var/lib/apt/lists/* \
    && typst --version

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
