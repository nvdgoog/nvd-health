from __future__ import annotations

from pathlib import Path
from typing import Dict

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.admin import router as admin_router
from app.api.analyst import router as analyst_router
from app.api.dashboard import router as dashboard_router
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="NVD Personal Health Engineering & AI Analytics Platform",
        version="0.1.0",
    )

    app.include_router(admin_router)
    app.include_router(dashboard_router)
    app.include_router(analyst_router)

    @app.get("/api/health")
    def healthcheck() -> Dict[str, str]:
        return {
            "status": "ok",
            "project_id": settings.gcp_project_id,
            "region": settings.gcp_region,
            "bucket": settings.gcs_raw_bucket,
        }

    dist_dir = Path(settings.frontend_dist_dir)
    if dist_dir.exists() and (dist_dir / "index.html").exists():
        assets_dir = dist_dir / "assets"
        if assets_dir.exists():
            app.mount(
                "/assets",
                StaticFiles(directory=str(assets_dir)),
                name="frontend-assets",
            )

        @app.get("/{full_path:path}")
        def serve_spa(full_path: str) -> FileResponse:
            candidate = dist_dir / full_path
            if full_path and candidate.is_file():
                return FileResponse(str(candidate))
            return FileResponse(str(dist_dir / "index.html"))

    return app


app = create_app()
