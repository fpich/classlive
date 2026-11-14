"""Contrats HTTP publics de ClassLive (v1)."""
from __future__ import annotations

from importlib.resources import files

import logging
import time

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field, model_validator

from classlive import __version__
from classlive.config import Settings, load_settings
from classlive.storage import EventStorage, InvalidName, ResourceConflict, ResourceNotFound, StorageError
from classlive.slides import SlideStorage
from classlive.navigation import SlideNavigator
from classlive.live import LiveStore
from classlive.live_api import install_live_api

logger = logging.getLogger("classlive")


class GroupRequest(BaseModel):
    group: str = Field(min_length=1, max_length=150)


class EventRequest(GroupRequest):
    title: str = Field(min_length=1, max_length=150)


class RenameRequest(BaseModel):
    new_name: str | None = Field(default=None, min_length=1, max_length=150)
    new_number: int | None = Field(default=None, ge=1, le=999999, strict=True)

    @model_validator(mode="after")
    def require_change(self):
        if self.new_name is None and self.new_number is None:
            raise ValueError('Indiquer new_name et/ou new_number.')
        return self


class SlideRequest(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    slide_type: str = Field(pattern=r"^[CAORQT]$")
    content: str = ""
    number: int | None = Field(default=None, ge=1, le=999999, strict=True)


class SlideRenameRequest(BaseModel):
    new_name: str | None = Field(default=None, min_length=1, max_length=150)
    new_number: int | None = Field(default=None, ge=1, le=999999, strict=True)
    new_type: str | None = Field(default=None, pattern=r"^[CAORQT]$")

    @model_validator(mode="after")
    def require_change(self):
        if self.new_name is None and self.new_number is None and self.new_type is None:
            raise ValueError("Indiquer new_name, new_number et/ou new_type.")
        return self


class SlideContentRequest(BaseModel):
    content: str


class DuplicateRequest(BaseModel):
    new_title: str | None = Field(default=None, min_length=1, max_length=150)


class GroupResult(BaseModel):
    success: bool = True
    group: str
    created: bool
    path: str


class EventResult(GroupResult):
    title: str


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or load_settings()
    storage = EventStorage(cfg.workdir, cfg.events_dir)
    slides = SlideStorage(storage)
    navigator = SlideNavigator(slides)
    live = LiveStore(cfg.workdir / "classlive.db", slides)
    # Échec immédiat au démarrage si le stockage est inutilisable.
    storage.init()
    guide_path = cfg.workdir / "GUIDE_CLASSLIVE.md"
    # Ne pas écraser les adaptations locales du guide lors d'une mise à jour.
    if not guide_path.exists():
        guide_path.write_text(files('classlive').joinpath('GUIDE_CLASSLIVE.md').read_text(encoding='utf-8'), encoding='utf-8')
    app = FastAPI(title="ClassLive Backend", version=__version__, description="Gestion des groupes et événements sur disque.")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cfg.cors_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        duration = time.monotonic() - start
        logger.info("%s %s -> %d (%.0f ms)", request.method, request.url.path, response.status_code, duration * 1000)
        return response

    auth = install_live_api(app, cfg, live)

    @app.exception_handler(ValueError)
    async def value_error_handler(request, exc: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(InvalidName)
    async def invalid_name_handler(request, exc: InvalidName):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(ResourceNotFound)
    async def not_found_handler(request, exc: ResourceNotFound):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ResourceConflict)
    async def conflict_handler(request, exc: ResourceConflict):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(StorageError)
    async def storage_error_handler(request, exc: StorageError):
        logger.error("Erreur de stockage : %s", exc)
        return JSONResponse(status_code=500, content={"detail": "Erreur de stockage. Consulter les journaux du service."})

    @app.get("/api/v1/help", tags=["Aide"], response_class=Response,
             summary="Guide Markdown stocké à la racine du workspace")
    def help_guide():
        return Response(content=guide_path.read_text(encoding='utf-8'),
                        media_type='text/markdown; charset=utf-8')

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse(url="/docs")

    @app.get("/health", tags=["Système"])
    def health():
        db_ok = True
        try:
            with live.db() as con:
                con.execute("SELECT COUNT(*) FROM live_sessions").fetchone()
        except Exception:
            db_ok = False
        return {"status": "ok" if db_ok else "degraded", "service": "classlive", "version": __version__, "database": db_ok}

    router = APIRouter(dependencies=[Depends(auth.trainer)])

    @router.post("/groups", response_model=GroupResult, tags=["Groupes"], status_code=200)
    def create_group(payload: GroupRequest):
        result = storage.create_group(payload.group)
        logger.info("Groupe %s (%s)", result["group"], "créé" if result["created"] else "existant")
        return {"success": True, **result}

    @router.get("/groups", tags=["Groupes"])
    def list_groups():
        return {"groups": storage.list_groups()}

    @router.get("/groups/{group}/events", tags=["Événements"])
    def list_events(group: str):
        events = storage.list_events(group)
        if events is None:
            raise HTTPException(status_code=404, detail="Groupe introuvable.")
        return {"group": group, "events": events}

    @router.post("/events", response_model=EventResult, tags=["Événements"], status_code=200)
    def create_event(payload: EventRequest):
        result = storage.create_event(payload.group, payload.title)
        logger.info("Événement %s/%s (%s)", result["group"], result["title"], "créé" if result["created"] else "existant")
        return {"success": True, **result}

    @router.get("/events", tags=["Événements"])
    def list_all_events():
        events = [{"group": g, "title": e} for g in storage.list_groups() for e in (storage.list_events(g) or [])]
        return {"events": events}

    @router.post("/groups/{group}/events/{event}/duplicate", tags=["Événements"])
    def duplicate_event(group: str, event: str, payload: DuplicateRequest | None = None):
        result = storage.duplicate_event(group, event, payload.new_title if payload else None)
        logger.info("Événement dupliqué : %s/%s -> %s", result["group"], result["title"], result["new_title"])
        return {"success": True, **result}

    @router.patch("/groups/{group}", tags=["Groupes"])
    def rename_group(group: str, payload: RenameRequest):
        resolved = storage._group(group).name
        if any(live.sessions(resolved, e)['sessions'] for e in (storage.list_events(resolved) or [])):
            raise ResourceConflict('Supprimer les sessions archivées avant de renommer ce groupe.')
        result = storage.rename_group(group, payload.new_name, payload.new_number)
        logger.info("Groupe renommé : %s -> %s (modifié=%s)", group, result["new_name"], result["renamed"])
        return {"success": True, **result}

    @router.patch("/groups/{group}/events/{title}", tags=["Événements"])
    def rename_event(group: str, title: str, payload: RenameRequest):
        if live.sessions(group,title)['sessions']:
            raise ResourceConflict('Supprimer les sessions archivées avant de renommer cet événement.')
        result = storage.rename_event(group, title, payload.new_name, payload.new_number)
        logger.info("Événement renommé : %s/%s -> %s (modifié=%s)", group, title, result["new_name"], result["renamed"])
        return {"success": True, **result}

    @router.delete("/groups/{group}/events/{title}", tags=["Événements"])
    def delete_event(group: str, title: str):
        if live.sessions(group,title)['sessions']:
            raise ResourceConflict('Supprimer les sessions archivées avant de supprimer cet événement.')
        result = storage.delete_event(group, title)
        logger.warning("Événement supprimé récursivement : %s/%s", group, title)
        return {"success": True, **result}

    @router.delete("/groups/{group}", tags=["Groupes"])
    def delete_group(group: str):
        resolved = storage._group(group).name
        if any(live.sessions(resolved,e)['sessions'] for e in storage.list_events(resolved)):
            raise ResourceConflict('Supprimer les sessions archivées avant de supprimer ce groupe.')
        result = storage.delete_group(group)
        logger.warning("Groupe supprimé récursivement : %s", group)
        return {"success": True, **result}

    @router.post("/groups/{group}/events/{event}/slides", tags=["Slides"])
    def create_slide(group: str, event: str, payload: SlideRequest):
        return {"success": True, **slides.create(group, event, payload.title, payload.slide_type, payload.content, payload.number)}

    @router.get("/groups/{group}/events/{event}/slides", tags=["Slides"])
    def list_slides(group: str, event: str):
        return slides.list(group, event)

    @router.get("/groups/{group}/events/{event}/slides/{slide}", tags=["Slides"])
    def get_slide(group: str, event: str, slide: str):
        return slides.read(group, event, slide)

    @router.patch("/groups/{group}/events/{event}/slides/{slide}", tags=["Slides"])
    def rename_slide(group: str, event: str, slide: str, payload: SlideRenameRequest):
        return {"success": True, **slides.rename(group, event, slide, payload.new_name, payload.new_number, payload.new_type)}

    @router.put("/groups/{group}/events/{event}/slides/{slide}/content", tags=["Slides"])
    def update_slide_content(group: str, event: str, slide: str, payload: SlideContentRequest):
        return {"success": True, **slides.update_content(group, event, slide, payload.content)}

    @router.delete("/groups/{group}/events/{event}/slides/{slide}", tags=["Slides"])
    def delete_slide(group: str, event: str, slide: str):
        return {"success": True, **slides.delete(group, event, slide)}

    # Lecteur séquentiel : chaque session client a sa propre position.
    @router.post("/player/select", tags=["Lecture"])
    def select_event(payload: EventRequest):
        return navigator.select(payload.group, payload.title)

    @router.post("/player/{session_id}/next", tags=["Lecture"])
    def next_slide(session_id: str):
        return navigator.navigate(session_id, 'next')

    @router.post("/player/{session_id}/previous", tags=["Lecture"])
    def previous_slide(session_id: str):
        return navigator.navigate(session_id, 'previous')

    @router.get("/player/{session_id}", tags=["Lecture"])
    def current_slide(session_id: str):
        return navigator.navigate(session_id, 'current')

    @router.delete("/player/{session_id}", tags=["Lecture"])
    def close_player(session_id: str):
        return navigator.close(session_id)

    app.include_router(router, prefix="/api/v1")
    # Alias compatible avec le contrat initial /api/events.
    app.include_router(router, prefix="/api", include_in_schema=False)
    return app
