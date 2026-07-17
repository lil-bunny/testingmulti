# Use the official lightweight Python 3.11 image
FROM python:3.11-slim-bookworm

# Copy the pre-compiled 'uv' binary directly from the official Astral image 
# (This is the fastest, cleanest way to install uv in Docker)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Keep Python from buffering logs so they show up instantly in AWS CloudWatch
ENV PYTHONUNBUFFERED=1
# Tell uv to compile bytecode for faster application startups
ENV UV_COMPILE_BYTECODE=1

# Set the working directory inside the container
WORKDIR /code

# --- INSTALL SYSTEM DEPENDENCIES  ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    libheif-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy ONLY your dependency files first. 
# Docker caches layers. By doing this before copying your code, changing a python file won't force a full re-install of all packages.
COPY pyproject.toml uv.lock ./
COPY README.md ./

# Install dependencies using uv. 
# --frozen ensures it strictly follows your lockfile.
# --no-dev excludes local testing tools (like pytest) to keep the image small.
RUN uv sync --frozen --no-install-project --no-dev

# Now copy your actual application code into the container
COPY ./app /code/app

# Sync again to finalize the installation with your project files
RUN uv sync --frozen --no-dev

# Add the uv virtual environment to the system PATH.
# This allows us to just type "uvicorn" or "celery" without needing to prefix it with "uv run"
ENV PATH="/code/.venv/bin:$PATH"

# The default command runs the Uvicorn web API on port 80 (standard for AWS containers).
# Note: For the Celery worker container in ECS, we will override this command via the AWS console.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]