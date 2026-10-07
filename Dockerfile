# Base image with Python 3.11 slim
FROM python:3.11-slim

# Prevent Python from buffering stdout/stderr and writing pyc files
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . /app

# Create persistent directories
RUN mkdir -p /app/journal /app/artifacts /app/data

# Expose MT5 Bridge Server port
EXPOSE 8000

# Default to a short, self-limiting paper mode so that `docker run <image>`
# performs a safe, non-trading demonstration instead of either (a) attempting
# to place live trades against an unreachable broker, or (b) exiting with only
# --help output. Production deployments always override this via
# docker-compose services (bridge / squad / paper) with explicit commands.
CMD ["python3", "main.py", "run", "--agent=legacy3", "--mode=paper", "--interval=10", "--max-iter=5"]
