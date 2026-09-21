from __future__ import annotations

import os

import uvicorn

from app.security import forwarded_allow_ips


def main() -> None:
    port = int(os.environ.get("PORT", "3000"))
    reload = os.environ.get("DEV", "").lower() in {"1", "true", "yes"}
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=port,
        reload=reload,
        proxy_headers=True,
        forwarded_allow_ips=forwarded_allow_ips(),
        access_log=False,
    )


if __name__ == "__main__":
    main()
