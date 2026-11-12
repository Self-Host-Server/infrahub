ARG BASE
FROM ${BASE}

RUN apt-get update && apt-get install -y --no-install-recommends nmap && rm -rf /var/lib/apt/lists/*

COPY . /app/ipam_sync
WORKDIR /app
CMD ["python", "-m", "ipam_sync.main"]
