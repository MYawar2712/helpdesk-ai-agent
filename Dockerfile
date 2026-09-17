# ── Stage: runtime ────────────────────────────────────────────────────────────
# python:3.11-slim satisfies requires-python = ">=3.11" (pyproject.toml).
# Slim (glibc-based) is required by numpy / scikit-learn / chromadb.
FROM python:3.11-slim

# Keep Python output unbuffered so container logs are visible in real time.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# ── 1. Install dependencies ────────────────────────────────────────────────────
# Copy only the requirements file first so Docker can cache this layer.
# The image is rebuilt from this point only when requirements.txt changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ── 2. Copy application source ─────────────────────────────────────────────────
# Install the local package in editable mode so all src/ imports resolve
# (mirrors pyproject.toml pythonpath = [".", "src"] used by pytest).
COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir -e .

# ── 3. Copy runtime assets ─────────────────────────────────────────────────────
# models/ — pre-trained ticket classifier (ticket_classifier.joblib)
# prompts/ — prompt templates used by the LangChain chains
# db/      — schema.sql and seed.py; SQLite database is created at startup
COPY models/ ./models/
COPY prompts/ ./prompts/
COPY db/schema.sql db/seed.py ./db/

# Ensure the db directory exists so SQLite can create the database file.
RUN mkdir -p /app/db

# ── 4. Expose and launch ───────────────────────────────────────────────────────
EXPOSE 8000

# src.api.main:app — works because /app is on PYTHONPATH via the editable install.
# main.py also inserts src/ into sys.path at startup as a belt-and-suspenders guard.
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
