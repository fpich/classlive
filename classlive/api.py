"""Contrats HTTP publics de ClassLive (v1)."""
from __future__ import annotations

import io
import json
import logging
import time
import zipfile
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from stat import S_ISREG

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from classlive import __version__
from classlive.config import Settings, load_settings
from classlive.storage import EVENT_RE, EventStorage, InvalidName, ResourceConflict, ResourceNotFound, StorageError
from classlive.slides import MEDIA_TYPES, SLIDE_RE, SlideStorage
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
    slide_type: str = Field(pattern=r"^[CAORQTFNPLI]$")
    content: str = ""
    number: int | None = Field(default=None, ge=1, le=999999, strict=True)


class SlideRenameRequest(BaseModel):
    new_name: str | None = Field(default=None, min_length=1, max_length=150)
    new_number: int | None = Field(default=None, ge=1, le=999999, strict=True)
    new_type: str | None = Field(default=None, pattern=r"^[CAORQTFNPLI]$")

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


class SPAStaticFiles(StaticFiles):
    """Sert le build du frontend sur /app avec fallback sur index.html (routes client)."""

    async def get_response(self, path, scope):
        full_path, stat_result = self.lookup_path(path)
        if stat_result is not None and S_ISREG(stat_result.st_mode):
            return await super().get_response(path, scope)
        return await super().get_response("index.html", scope)


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or load_settings()
    storage = EventStorage(cfg.workdir, cfg.events_dir)
    slides = SlideStorage(storage, media_max_bytes=cfg.media_max_mb * 1024 * 1024)
    navigator = SlideNavigator(slides)
    # Sans load_settings (Settings construit à la main), audit_file vaut None : repli par défaut.
    audit_file = cfg.audit_file if cfg.audit_file is not None else (cfg.workdir / "audit.log" if cfg.audit_enabled else None)
    live = LiveStore(cfg.workdir / "classlive.db", slides, audit_file=audit_file, max_students=cfg.max_students)
    # Échec immédiat au démarrage si le stockage est inutilisable.
    storage.init()
    # Purge automatique des sessions terminées trop anciennes (rétention configurée).
    if cfg.retention_days > 0:
        live.purge(cfg.retention_days)
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

    @router.post("/groups/{group}/duplicate", tags=["Groupes"])
    def duplicate_group(group: str, payload: DuplicateRequest | None = None):
        new_name = payload.new_title if payload else None
        result = storage.duplicate_group(group, new_name)
        logger.info("Groupe dupliqué : %s -> %s", result["group"], result["new_name"])
        return {"success": True, **result}

    @router.delete("/groups/{group}/events/{event}/students-data", tags=["RGPD"])
    def forget_student(group: str, event: str, nom: str = Query(min_length=1), prenom: str = Query(min_length=1)):
        """Droit à l'oubli : supprime toutes les participations d'un élève sur un événement."""
        return live.forget_student(group, event, nom.strip(), prenom.strip())

    @router.get("/groups/{group}/events/{event}/export.zip", tags=["Événements"])
    def export_event_zip(group: str, event: str):
        g, parent = slides._parent(group, event)
        buffer = io.BytesIO()
        manifest = {"format": "classlive-event", "version": 1, "group": g.name, "event": parent.name,
                    "slides": [p.name for p in slides._slides(parent)]}
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for p in slides._slides(parent):
                zf.write(p, p.name)
        logger.info("Export ZIP de l'événement %s/%s (%d slides)", g.name, parent.name, len(manifest["slides"]))
        return Response(content=buffer.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{parent.name}.zip"'})

    @router.post("/groups/{group}/import.zip", tags=["Événements"], status_code=200)
    async def import_event_zip(group: str, request: Request):
        """Importe un événement depuis un ZIP produit par export.zip (manifest.json + slides Sxxx_*.md).
        Le ZIP est envoyé en corps brut (application/zip), sans multipart."""
        limit = cfg.export_max_zip_mb * 1024 * 1024
        # Refus précoce si l'en-tête annonce un corps trop gros (évite de tout lire en mémoire).
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > limit:
                    raise HTTPException(status_code=413, detail=f"ZIP trop volumineux (max {cfg.export_max_zip_mb} Mo).")
            except ValueError:
                raise HTTPException(status_code=422, detail="En-tête Content-Length invalide.") from None
        data = await request.body()
        if not data:
            raise HTTPException(status_code=422, detail="Fichier ZIP vide.")
        if len(data) > limit:
            raise HTTPException(status_code=413, detail=f"ZIP trop volumineux (max {cfg.export_max_zip_mb} Mo).")
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=422, detail=f"ZIP invalide : {exc}") from exc
        with zf:
            # Protection anti zip-bomb : taille décompressée totale plafonnée au même limit.
            total_uncompressed = sum(info.file_size for info in zf.infolist() if not info.is_dir())
            if total_uncompressed > limit:
                raise HTTPException(status_code=413, detail=f"ZIP décompressé trop volumineux (max {cfg.export_max_zip_mb} Mo).")
            names = zf.namelist()
            if "manifest.json" not in names:
                raise HTTPException(status_code=422, detail="manifest.json manquant dans le ZIP.")
            try:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise HTTPException(status_code=422, detail=f"manifest.json illisible : {exc}") from exc
            if not isinstance(manifest, dict) or manifest.get("format") != "classlive-event" \
                    or not isinstance(manifest.get("event"), str) or not manifest["event"].strip():
                raise HTTPException(status_code=422, detail="manifest.json invalide (format classlive-event requis).")
            slides_infos = manifest.get("slides")
            if not isinstance(slides_infos, list) or not slides_infos \
                    or any(not isinstance(s, str) or not SLIDE_RE.fullmatch(s) for s in slides_infos):
                raise HTTPException(status_code=422, detail="manifest.json : liste de slides Sxxx_[CAORQTFNPLI]_*.md requise.")
            for name in slides_infos:
                if name not in names:
                    raise HTTPException(status_code=422, detail=f"Slide {name} absente du ZIP.")
            # Valide tout le contenu avant de créer quoi que ce soit.
            contents = {}
            for name in slides_infos:
                try:
                    contents[name] = zf.read(name).decode("utf-8")
                except (UnicodeError, KeyError) as exc:
                    raise HTTPException(status_code=422, detail=f"Slide {name} illisible : {exc}") from exc
            # create_event refuse un identifiant Exxx_ complet : on importe le libellé seul.
            event_name = manifest["event"]
            match = EVENT_RE.fullmatch(event_name)
            title = match.group(2) if match else event_name
            created = storage.create_event(group, title)
            g, parent = slides._parent(created["group"], created["title"])
            written = []
            for name in slides_infos:
                (parent / name).write_text(contents[name], encoding="utf-8")
                written.append(name)
        live.audit("formateur", "import_zip", f"{created['group']}/{created['title']} ({len(written)} slides)")
        logger.info("Import ZIP : %s/%s (%d slides)", created["group"], created["title"], len(written))
        return {"success": True, "group": created["group"], "event": created["title"],
                "created": created["created"], "slides": written}

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
        old = slides.read(group, event, slide)['content']
        result = slides.update_content(group, event, slide, payload.content)
        if old != payload.content:  # pas de version archivée si le contenu est identique
            live.record_slide_version(group, event, slide, old, 'formateur')
        return {"success": True, **result}

    @router.get("/groups/{group}/events/{event}/slides/{slide}/versions", tags=["Slides"])
    def slide_versions(group: str, event: str, slide: str):
        return live.slide_versions(group, event, slide)

    @router.get("/groups/{group}/events/{event}/slides/{slide}/versions/{vid}", tags=["Slides"])
    def slide_version(group: str, event: str, slide: str, vid: int):
        return live.slide_version(group, event, slide, vid)

    @router.post("/groups/{group}/events/{event}/slides/{slide}/versions/{vid}/restore", tags=["Slides"])
    def restore_slide_version(group: str, event: str, slide: str, vid: int):
        return live.restore_slide_version(group, event, slide, vid, actor='formateur')

    @router.delete("/groups/{group}/events/{event}/slides/{slide}", tags=["Slides"])
    def delete_slide(group: str, event: str, slide: str):
        return {"success": True, **slides.delete(group, event, slide)}

    @router.get("/stats/usage", tags=["Système"])
    def usage_stats():
        return live.usage_stats()

    @router.post("/admin/purge", tags=["Système"])
    def purge_sessions():
        """Purge manuelle des sessions terminées selon la rétention configurée."""
        return live.purge(cfg.retention_days)

    @router.get("/admin/backup.zip", tags=["Système"])
    def backup_zip():
        """Archive ZIP complète du workspace (Evts/, classlive.db, audit.log, guide)."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(cfg.workdir.rglob("*")):
                if p.is_symlink():
                    continue
                if p.is_file():
                    zf.write(p, p.relative_to(cfg.workdir))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        logger.info("Backup ZIP du workspace (%d fichiers)", len(zipfile.ZipFile(io.BytesIO(buffer.getvalue())).namelist()))
        live.audit("formateur", "backup", "workspace archivé en ZIP")
        return Response(content=buffer.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="classlive_backup_{stamp}.zip"'})

    @router.get("/audit", tags=["Système"])
    def audit_log(limit: int = Query(default=200, ge=1, le=1000)):
        return live.audit_list(limit)

    # ── Médias de l'événement (upload en corps brut, téléchargement public sur /media/...) ──

    @router.post("/groups/{group}/events/{event}/media", tags=["Médias"], status_code=200)
    async def upload_media(group: str, event: str, request: Request, filename: str = Query(min_length=1, max_length=150)):
        limit = cfg.media_max_mb * 1024 * 1024
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > limit:
                    raise HTTPException(status_code=413, detail=f"Média trop volumineux (max {cfg.media_max_mb} Mo).")
            except ValueError:
                raise HTTPException(status_code=422, detail="En-tête Content-Length invalide.") from None
        data = await request.body()
        if not data:
            raise HTTPException(status_code=422, detail="Fichier vide.")
        if len(data) > limit:
            raise HTTPException(status_code=413, detail=f"Média trop volumineux (max {cfg.media_max_mb} Mo).")
        result = slides.upload_media(group, event, filename, data)
        logger.info("Média uploadé : %s/%s/%s (%d octets)", result["group"], result["event"], filename, len(data))
        return {"success": True, **result}

    @router.get("/groups/{group}/events/{event}/media", tags=["Médias"])
    def list_media(group: str, event: str):
        return slides.list_media(group, event)

    @router.delete("/groups/{group}/events/{event}/media/{filename}", tags=["Médias"])
    def delete_media(group: str, event: str, filename: str):
        return {"success": True, **slides.delete_media(group, event, filename)}

    @router.post("/groups/{group}/events/{event}/slides/{slide}/duplicate", tags=["Slides"])
    def duplicate_slide(group: str, event: str, slide: str, payload: DuplicateRequest | None = None):
        result = slides.duplicate(group, event, slide, payload.new_title if payload else None)
        logger.info("Slide dupliquée : %s/%s/%s -> %s", result["group"], result["event"], result["slide"], result["new_slide"])
        return {"success": True, **result}

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

    # Médias des événements servis publiquement (référencés dans le Markdown des slides).
    @app.get("/media/{group}/{event}/{filename}", tags=["Médias"])
    def media_download(group: str, event: str, filename: str):
        path = slides.media_file(group, event, filename)
        return FileResponse(path, media_type=MEDIA_TYPES[path.suffix.lower()])

    # Build du frontend servi sur /app quand server.frontend_dir est configuré.
    if cfg.frontend_dir is not None:
        frontend_path = Path(cfg.frontend_dir).expanduser()
        if not frontend_path.is_absolute():
            frontend_path = cfg.workdir / frontend_path
        if frontend_path.is_dir():
            app.mount("/app", SPAStaticFiles(directory=str(frontend_path), html=True), name="frontend")
            logger.info("Frontend statique servi sur /app depuis %s", frontend_path)
    return app
