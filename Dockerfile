# /architect, your Anaplan build buddy: one image for a laptop, a server inside an organisation, and Railway.
# The React app is already built into src/anaplan_architect/static/app, so there is no Node stage.
#
#   docker build -t anaplan-architect .
#   docker compose up                   # http://localhost:8765, data kept in the volume
#
# The two libraries are installed from GitHub at the commits below (or from wheels placed in vendor/).
FROM python:3.12-slim

# the commits that the tags v0.2.0 and v0.1.0 name (pins.json): a commit cannot be moved, a tag can
ARG ESTATE_REF=559f4fdde000e79c6270c0d71132e5e5048f268a
ARG GRAMMAR_REF=8a5683b50a7905318760ff7f53d83047db36e611
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ARCHITECT_DATA=/data

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# the two pinned libraries: local wheels when they were built, else the GitHub tags
COPY vendor* /wheels/
RUN if ls /wheels/*.whl >/dev/null 2>&1; then pip install /wheels/*.whl; \
    else pip install "git+https://github.com/klameer/anaplan-grammar@${GRAMMAR_REF}" "git+https://github.com/klameer/anaplan-estate@${ESTATE_REF}"; fi

COPY pyproject.toml README.md constraints.txt LICENSE* CITATION.cff* ./
COPY src ./src
COPY examples ./examples
# every other dependency at the version the tests ran against (constraints.txt)
RUN pip install -c constraints.txt ".[llm,web,openai,trace]"

RUN useradd --create-home --uid 10001 architect && mkdir -p /data && chown architect /data
USER architect
VOLUME ["/data"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8765'), timeout=4)" || exit 1

# Railway sets PORT; elsewhere it is 8765. Bound to every interface inside the container: publish the port to
# localhost only (compose does), or create the admin (ARCHITECT_ADMIN_USER and ARCHITECT_ADMIN_PASSWORD) before exposing it.
# On Railway the store lives on the volume attached to the service (Railway names its mount path in
# RAILWAY_VOLUME_MOUNT_PATH); elsewhere on the /data volume.
CMD ["sh", "-c", "anaplan-architect serve --data ${RAILWAY_VOLUME_MOUNT_PATH:-${ARCHITECT_DATA}} --host 0.0.0.0 --port ${PORT:-8765}"]
