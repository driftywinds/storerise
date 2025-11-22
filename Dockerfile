FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

RUN mkdir -p /app/data && chown -R botuser:botuser /app

USER botuser

CMD ["python3", "-u", "bot.py"]
