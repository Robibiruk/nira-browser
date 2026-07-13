FROM python:3.11-slim

WORKDIR /app

# Lean image: NO Chromium. The default fetch backend needs only httpx.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Render free tier is 512MB; keep it tight.
ENV PORT=10000
ENV BROWSER_BACKEND=fetch
EXPOSE 10000

CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "10000"]
