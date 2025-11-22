FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY bot.py .

# Create data directory
RUN mkdir -p /app/data

# Run bot
CMD ["python", "-u", "bot.py"]
