FROM python:3.11-slim

# Install system deps and Rust toolchain (for sqlalchemy-libsql/libsql-experimental build)
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential curl pkg-config libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Rust (non-interactive)
RUN curl https://sh.rustup.rs -sSf | bash -s -- -y && \
    /root/.cargo/bin/rustc --version
ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /app

# Install Python dependencies first (better layer caching)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Runtime env
ENV PYTHONUNBUFFERED=1 \
    FLASK_ENV=production \
    PORT=8080

EXPOSE 8080

# Start gunicorn
CMD ["gunicorn", "app_api_simple:app", "--bind", "0.0.0.0:8080", "--workers", "1", "--timeout", "60"]


