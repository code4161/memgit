# memgit MCP server over stdio, built from this checkout.
# docker build -t memgit . && docker run -i --rm memgit
FROM python:3.12-slim

WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY memgit ./memgit
RUN pip install --no-cache-dir . && rm -rf /src

# Run unprivileged; the store is created under this home on first start.
RUN useradd --create-home --shell /usr/sbin/nologin memgit
USER memgit
WORKDIR /home/memgit
ENV MEMGIT_NO_AUTOSYNC=1

ENTRYPOINT ["memgit", "serve"]
