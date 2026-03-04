"""Entry point when running as a module: python -m sentinel."""
import uvicorn
from sentinel.server import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000)
