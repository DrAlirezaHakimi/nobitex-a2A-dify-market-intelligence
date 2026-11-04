import os
import uvicorn

if __name__ == "__main__":
    host = os.getenv("BIND_HOST", "127.0.0.1")
    if host not in ("127.0.0.1", "localhost", "::1") and not os.getenv("API_KEY"):
        raise SystemExit("For remote bind, configure a strong API_KEY and HTTPS reverse proxy")
    uvicorn.run("app.server:app", host=host, port=int(os.getenv("PORT", "8000")), reload=False)
