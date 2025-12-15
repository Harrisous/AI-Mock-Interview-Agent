# Use an official Python runtime as a parent image
FROM python:3.11-slim-bookworm

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Set work directory
WORKDIR /app

# Install system dependencies (required for some python packages and potentially cv2 if we added video later)
# 'fuser' is used in our pre_start_cleanup, so we need psmisc
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    psmisc \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
# Install python dependencies
COPY requirements.txt .
# Exclude livekit-plugins-silero from requirements to avoid dependency check failure
RUN grep -v "livekit-plugins-silero" requirements.txt > requirements_no_silero.txt
RUN pip install --no-cache-dir -r requirements_no_silero.txt
# Force install the incompatible version (we patch it later)
RUN pip install --no-cache-dir --no-deps livekit-plugins-silero==0.7.6

# Copy application code
COPY . .

# Apply VAD patch during build (as root)
RUN python3 patch_vad_class.py

# Create a non-root user for security
RUN useradd -m appuser && chown -R appuser /app
USER appuser

# Expose the port (though Agents usually connect OUT to LiveKit)
EXPOSE 8081

# Run the agent
# Note: In production, we typically don't run 'dev' mode. 
# We run 'start' which expects a room to be dispatched to it, or just runs as a worker.
# For a simple "always on" worker that connects to a room:
CMD ["python3", "main.py", "start"]
