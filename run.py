"""Start the app:  python run.py   ->  http://localhost:8000"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))
import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
