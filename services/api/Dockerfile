# Start from a small official Python image.
FROM python:3.12-slim

# All app files live in /app inside the container.
WORKDIR /app

# Copy deps first and install them — this layer is cached unless requirements change,
# so rebuilds are fast when only your code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code.
COPY . .

# Cloud Run tells the container which port to listen on via $PORT (defaults to 8080).
# We must bind to 0.0.0.0 (all interfaces), not localhost, so Cloud Run can reach us.
ENV PORT=8080
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
