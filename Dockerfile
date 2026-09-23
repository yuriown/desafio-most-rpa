# Imagem oficial do Playwright: já traz o Chromium e as bibliotecas do sistema.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY robo ./robo
COPY api ./api

ENV ROBO_HEADLESS=true
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
