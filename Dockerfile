FROM mcr.microsoft.com/playwright/python:v1.52.0-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create non-root user for Chromium sandbox
RUN useradd -m -s /bin/bash scraper && \
    mkdir -p /app/data && \
    chown -R scraper:scraper /app

USER scraper

EXPOSE 8035

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8035"]
