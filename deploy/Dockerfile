# Draft single-image build: FalkorDB (same pinned image as docker-compose.yml) + the API + the helpers.
# Not deployed anywhere yet. Build from the repo root:  docker build -f deploy/Dockerfile -t leaktrace-demo .
FROM falkordb/falkordb@sha256:107455e862a824e45e8e9f5a7fbfdf5e00a08b14e13eae2577c72fd9e3f59ba6

ENV BROWSER=0 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* && python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
COPY packs ./packs
COPY deploy/start.sh ./start.sh

EXPOSE 7860
ENTRYPOINT ["sh", "/app/start.sh"]
