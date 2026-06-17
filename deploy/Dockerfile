# luna — 1 container self-contained: Node (Claude CLI) + Python (FastAPI) + git + gh.
# Image non-root: Claude từ chối bypassPermissions khi chạy root → drop xuống user 'node'
# bằng gosu (xem entrypoint.sh). Pattern port từ Dockerfile.
FROM node:22-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

# Toolchain: git/gh (commit + PR), python (app), ripgrep (Claude search), gosu (drop root).
RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates curl gnupg python3 python3-pip ripgrep less openssh-client gosu \
 && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
 && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
 && apt-get update && apt-get install -y --no-install-recommends gh \
 && rm -rf /var/lib/apt/lists/*

# Claude Code CLI (headless). Auth qua CLAUDE_CODE_OAUTH_TOKEN (subscription).
RUN npm install -g @anthropic-ai/claude-code

ENV HOME=/home/node \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY requirements.txt ./
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Mã nguồn + migrations + scripts seed.
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY scripts/ ./scripts/
COPY alembic.ini ./
COPY deploy/entrypoint.sh ./entrypoint.sh
RUN chmod +x entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
