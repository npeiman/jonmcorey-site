# Container image for the Professional Advisory Group site.
# Pure standard-library Python app — no dependencies to install.
FROM python:3.12-slim

WORKDIR /app
COPY . /app

# Bind all interfaces inside the container. Keep the SQLite database on a
# mounted volume so it survives image rebuilds/redeploys.
ENV HOST=0.0.0.0 \
    PORT=8000 \
    PAG_DB=/data/pag.db

EXPOSE 8000
VOLUME ["/data"]

CMD ["python3", "server.py"]
