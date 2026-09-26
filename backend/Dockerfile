FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg2 (Postgres driver) and scikit-learn/numpy wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

# Fly.io routes external traffic to internal port 8080 by convention (see fly.toml).
# --proxy-headers so FastAPI trusts Fly's edge proxy for client IPs/scheme.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
