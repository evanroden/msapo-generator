"""
Entry point: launch the FastAPI webhook server.

Usage:
    uvicorn run_api:app --host 0.0.0.0 --port 8000
"""

from app.webhook import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.webhook:app", host="0.0.0.0", port=8000, reload=True)
