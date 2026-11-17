FROM python:3.11-slim

WORKDIR /app

# Install system dependencies and timezone data
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Set timezone to Hong Kong (HKT - UTC+8)
ENV TZ=Asia/Hong_Kong
RUN ln -fs /usr/share/zoneinfo/Asia/Hong_Kong /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata

# Install core Python dependencies
RUN pip install --no-cache-dir \
    aiohttp==3.9.5 \
    aiosignal==1.3.1 \
    ccxt==4.4.77 \
    numpy==1.26.4 \
    pandas==2.2.0 \
    requests==2.31.0 \
    scikit-learn==1.4.1.post1 \
    selenium==4.16.0 \
    pytz==2024.1 \
    python-dateutil==2.8.2

# Copy application code
COPY src/ ./src/
COPY config.ini /app/config.ini

# Set working directory to src
WORKDIR /app/src

# Run the application (Docker version)
CMD ["python", "simple_docker.py"]
