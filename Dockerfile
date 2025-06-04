# Use a slim Python runtime as a parent image
FROM python:3.12-slim-bullseye

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV APP_HOME=/app
ENV PORT=8080

# Set the working directory in the container
WORKDIR ${APP_HOME}

# Create a non-root user and group
RUN groupadd --system appgroup && useradd --system --gid appgroup --home ${APP_HOME} appuser

# Install system dependencies if any (e.g., for libraries that need them)
# RUN apt-get update && apt-get install -y --no-install-recommends some-package && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY src/ ./src/
COPY templates/ ./templates/
# If you have other directories like 'static/', copy them as well:
# COPY static/ ./static/

# Change ownership of the app directory to the non-root user
RUN chown -R appuser:appgroup ${APP_HOME}

# Switch to the non-root user
USER appuser

# Expose the port the app runs on (for documentation, Cloud Run uses $PORT env var)
EXPOSE ${PORT}

# Run the application with Gunicorn
CMD ["gunicorn", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:${PORT}", "src.server:app"] 