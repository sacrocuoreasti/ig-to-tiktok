FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PORT=5005

# Install system dependencies including ffmpeg
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Copy and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Ensure Chromium headless is ready
RUN playwright install chromium

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p data downloads

EXPOSE 5005

CMD ["python3", "app.py"]

