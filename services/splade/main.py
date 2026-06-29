"""SPLADE sparse vector microservice."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

import torch
from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoModelForMaskedLM, AutoTokenizer

SPLADE_MODEL = os.getenv("SPLADE_MODEL", "naver/splade-cocondenser-ensembledistil")
MAX_LENGTH = int(os.getenv("SPLADE_MAX_LENGTH", "256"))
QUERY_MAX_LENGTH = int(os.getenv("SPLADE_QUERY_MAX_LENGTH", "64"))

_model = None
_tokenizer = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model, _tokenizer  # noqa: PLW0603
    _tokenizer = AutoTokenizer.from_pretrained(SPLADE_MODEL)
    _model = AutoModelForMaskedLM.from_pretrained(SPLADE_MODEL)
    _model.eval()
    yield


app = FastAPI(lifespan=lifespan)


class SparseRequest(BaseModel):
    text: str
    max_length: int | None = None


class SparseResponse(BaseModel):
    indices: list[int]
    values: list[float]


def _compute(text: str, max_length: int) -> tuple[list[int], list[float]]:
    tokens = _tokenizer(
        text,
        return_tensors="pt",
        max_length=max_length,
        truncation=True,
        padding=True,
    )
    with torch.no_grad():
        output = _model(**tokens)
    splade_vector = torch.max(torch.log1p(torch.relu(output.logits)), dim=1).values.squeeze()
    indices = splade_vector.nonzero(as_tuple=True)[0].tolist()
    values = splade_vector[indices].tolist()
    return indices, values


@app.post("/sparse/document", response_model=SparseResponse)
def sparse_document(req: SparseRequest):
    indices, values = _compute(req.text, req.max_length or MAX_LENGTH)
    return SparseResponse(indices=indices, values=values)


@app.post("/sparse/query", response_model=SparseResponse)
def sparse_query(req: SparseRequest):
    indices, values = _compute(req.text, req.max_length or QUERY_MAX_LENGTH)
    return SparseResponse(indices=indices, values=values)


@app.get("/health")
def health():
    return {"status": "ok", "model": SPLADE_MODEL, "device": "cpu"}
