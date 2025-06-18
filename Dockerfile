# Dockerfile for AI Dev Bot

# Use the latest slim Python image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies needed by some Python packages
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt and install dependencies except langchain
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Install latest langchain directly from GitHub main branch
RUN pip install --no-cache-dir git+https://github.com/hwchase17/langchain.git@master

# Copy the rest of your app code
COPY . .

# Expose port (adjust as needed)
EXPOSE 8004

# Run your app (adjust as needed)
CMD ["uvicorn", "bot.main:app", "--host", "0.0.0.0", "--port", "8004"]