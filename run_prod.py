import uvicorn
from dotenv import load_dotenv

load_dotenv()

from backend.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "run_prod:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        workers=1,
        access_log=False,
    )
