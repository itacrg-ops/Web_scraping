"""Entity Resolution — microservizio (gate anti-omonimia).

Corrisponde al componente `worker-entity-resolution` del documento di
deployment. Il workflow di screening lo invoca **per primo**: se il gate non è
superato, non si produce alcun giudizio adverse-media e si escala alla
disambiguazione umana.
"""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from app import resolver
from app.normalize import valid_cf, valid_identifier, valid_piva

app = FastAPI(title="Entity Resolution", version="0.1.0")


class SubjectIn(BaseModel):
    denominazione: str
    cf_piva: str | None = None
    cup: list[str] = []
    sede: str | None = None
    alias: list[str] = []


class MatchOut(BaseModel):
    id: str
    denominazione: str
    cf_piva: str | None = None
    cup: list[str] = []
    score: float | None = None


class ResolveOut(BaseModel):
    resolved: bool
    status: str                 # resolved | ambiguous | unresolved
    method: str
    confidence: float
    identifier_valid: bool
    matched: MatchOut | None = None
    candidates: list[MatchOut] = []
    warnings: list[str] = []


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/resolve", response_model=ResolveOut)
def resolve(subject: SubjectIn) -> dict:
    return resolver.resolve(subject.model_dump())


@app.get("/validate")
def validate(id: str) -> dict:
    """Utility: valida formalmente un CF o una P.IVA."""
    return {"value": id, "valid": valid_identifier(id), "is_cf": valid_cf(id), "is_piva": valid_piva(id)}
