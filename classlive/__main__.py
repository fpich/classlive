"""Exécution : python -m classlive ou classlive."""
from __future__ import annotations

import logging
import sys

import uvicorn

from classlive.api import create_app
from classlive.config import load_settings


def main() -> None:
    try:
        cfg = load_settings()
        logging.basicConfig(level=cfg.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        app = create_app(cfg)
        if cfg.trainer_password is None and cfg.api_key is None:
            logging.getLogger("classlive").warning("Aucun identifiant formateur configuré : définir CLASSLIVE_TRAINER_PASSWORD.")
    except (ValueError, FileNotFoundError, OSError) as exc:
        print(f"Impossible de démarrer ClassLive : {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level=cfg.log_level.lower(), proxy_headers=False)


if __name__ == "__main__":
    main()
