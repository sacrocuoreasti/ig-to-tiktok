FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV INSTAGRAM_BROWSER_CHANNEL=chrome

# Install system dependencies including ffmpeg
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Copy and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Google Chrome includes AAC media codecs that bundled Linux Chromium lacks.
# Instagram uses browser codec capabilities when choosing its audio renditions.
RUN playwright install chrome

# Copy application code
COPY . .

# Ensure entrypoint is executable
RUN chmod +x entrypoint.sh

# Create necessary directories
RUN mkdir -p data downloads

EXPOSE 10000

CMD ["/app/entrypoint.sh"]
