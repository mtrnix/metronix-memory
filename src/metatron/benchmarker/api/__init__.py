"""Benchmarker API — combined router for all benchmarker endpoints.

Sub-routers:
    - generation: POST /generate
    - testing:    POST /run-tests
    - benchmarks: /benchmarks CRUD
    - test_runs:  /test-runs CRUD

Register in app.py with:
    app.include_router(router, prefix="/api/v1/benchmarker")
"""

from fastapi import APIRouter

from metatron.benchmarker.api.benchmarks import router as benchmarks_router
from metatron.benchmarker.api.generation import router as generation_router
from metatron.benchmarker.api.test_runs import router as test_runs_router
from metatron.benchmarker.api.testing import router as testing_router

router = APIRouter()

router.include_router(generation_router)
router.include_router(testing_router)
router.include_router(benchmarks_router)
router.include_router(test_runs_router)

__all__ = ["router"]
