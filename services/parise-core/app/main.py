"""parise-core — API central.

Cada projeto (ARENA, Android, apps de estudo, novos) se registra como módulo
e passa a ser descoberto por todos os outros via /api/modules.
Persistência simples em JSON (PARISE_DATA). Auth: header X-Parise-Token.
"""
import json
import os
import secrets
import threading
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

DATA = Path(os.environ.get("PARISE_DATA", "/data"))
DATA.mkdir(parents=True, exist_ok=True)
REGISTRY = DATA / "modules.json"
TOKEN = os.environ.get("PARISE_TOKEN", "")

app = FastAPI(title="parise-core", version="0.1.0")


def auth(x_parise_token: str = Header(default="")) -> None:
    # Sem token configurado = bloqueia tudo (falha segura)
    if not TOKEN or not secrets.compare_digest(x_parise_token.encode(), TOKEN.encode()):
        raise HTTPException(status_code=401, detail="token inválido")


# As rotas são síncronas (rodam em várias threads): a trava evita perder registros
LOCK = threading.Lock()


def load() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8")) if REGISTRY.exists() else {}


def save(reg: dict) -> None:
    tmp = REGISTRY.with_suffix(".tmp")   # grava e troca: queda no meio não corrompe o arquivo
    tmp.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(REGISTRY)


class Module(BaseModel):
    name: str            # ex.: "arena"
    url: str             # ex.: "http://arena.parise.lan"
    kind: str = "web"    # web | android | service | job
    description: str = ""


@app.get("/health")
def health() -> dict:
    return {"ok": True, "ts": int(time.time())}


@app.get("/api/modules")
def list_modules(_: None = Depends(auth)) -> dict:
    return load()


@app.put("/api/modules")
def register_module(m: Module, _: None = Depends(auth)) -> dict:
    with LOCK:
        reg = load()
        reg[m.name] = {**m.model_dump(), "seen": int(time.time())}
        save(reg)
    return reg[m.name]


@app.delete("/api/modules/{name}")
def remove_module(name: str, _: None = Depends(auth)) -> dict:
    with LOCK:
        reg = load()
        reg.pop(name, None)
        save(reg)
    return {"removed": name}


# PWA (instalável no Android): / -> app/static
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="pwa")
