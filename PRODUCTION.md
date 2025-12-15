# Production Deployment Guide 🚀

To deploy the AI Mock Interview Agent in a production environment, follow these recommendations for stability, scalability, and security.

## 1. Containerization (Docker)

We have provided a `Dockerfile` to wrap the application. Use this to build a lightweight, portable container.

**Build:**
```bash
docker build -t ai-mock-interview-agent .
```

**Run locally (for testing):**
```bash
docker run --env-file .env ai-mock-interview-agent
```

## 2. Deployment Architecture

LiveKit Agents run as **workers**. They connect *outbound* to the LiveKit Server via WebSocket. This means you do **not** need to expose public ingress ports (like 80 or 443) for the agent itself, greatly simplifying network configuration.

### Option A: Cloud-Native (Kubernetes / AWS ECS) - **Recommended**
Deploy your docker container as a **StatefulSet** or **Deployment**.
*   **Replicas**: Run multiple replicas. The LiveKit Server will automatically balance incoming room sessions across available workers.
*   **Auto-scaling**: Scale based on CPU/Memory usage.

### Option B: simple VM (EC2 / DigitalOcean)
For smaller setups, run the Docker container on a VM using `docker-compose`. Ensure you enable "Restart Policies" (`restart: always`) so it recovers from crashes.

## 3. Environment & Security

*   **Secrets**: Do NOT commit `.env` files. In production, inject secrets via your orchestrator (e.g., Kubernetes Secrets, AWS Secrets Manager).
*   **Permissions**: The `Dockerfile` creates a non-root user (`appuser`). Do not run as root.
*   **Vulnerability Scanning**: Scan your PDF inputs or use a sandboxed parser if dealing with untrusted users.

## 4. Monitoring & Observability

*   **Logs**: The application logs to `stdout`/`stderr`. Capture these logs using your platform's logging driver (e.g., CloudWatch, Datadog).
*   **Health Checks**: Implement a simple health check. While the agent connects via WebSocket, you can monitor the process status.
*   **Metrics**: Monitor `job_count` and CPU usage. Audio processing (VAD/STT/TTS) is CPU-intensive.

## 5. The "Start" Command

In production, use `python main.py start` instead of `python main.py dev`.
*   `dev`: Hot-reloading, local simplified connection.
*   `start`: Production mode, optimized for stable connections.

## 6. CI/CD Pipeline

1.  **Code Push**: Trigger GitHub Action.
2.  **Test**: Run `verify_resume.py` and unit tests.
3.  **Build**: Build Docker image.
4.  **Deploy**: Update Kubernetes Deployment implementation.


## 7. Known Issues Handling

*   **VAD/Port Issues**: The included `pre_start_cleanup` and `patch_vad_class.py` scripts are designed to work inside the container automatically, ensuring self-healing capabilities.

## 8. 📄 Data Protocol (Resume & JD)

To pass a custom Resume and Job Description for each user session, your frontend should send a JSON string in the **Room Metadata** when connecting.

**Format:**
```json
{
  "resume_text": "Full text content of the candidate's resume...",
  "job_description": "Full text content of the job requirement..."
}
```

1.  **Extract Text**: Your frontend (or separate backend) must parse the PDF/Docx to text first.
2.  **Set Metadata**: Passing this JSON in `metadata` ensures the Agent picks it up immediately upon connection.
3.  **Fallback**: If no metadata is provided, the Agent defaults to the files in `example/`.

## 9. 🎨 Demo UI & Docker Compose

For a complete local demo experience (Backend + Resume Upload UI), use Docker Compose.

1.  **Run Services**:
    ```bash
    sudo docker compose up --build
    ```
    This starts:
    *   **Agent Backend**: Connected to LiveKit Cloud.
    *   **Demo UI**: Accessible at `http://localhost:8501`.

2.  **Upload Files**:
    *   Go to `http://localhost:8501`.
    *   Upload your Resume (PDF) and Job Description (MD/TXT).
    *   These files automatically update the shared `example/` folder inside the container.

3.  **Start Interview**:
    *   Go to [LiveKit Playground](https://agents-playground.livekit.io/).
    *   Connect to your room.
    *   The Agent will use the files you just uploaded!

