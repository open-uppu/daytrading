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

# Default command: show help or run squad
CMD ["python3", "main.py", "--help"]
