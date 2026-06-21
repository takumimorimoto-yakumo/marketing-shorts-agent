"""Content stub — FastAPI service implementing the content contract v1.0.0.

Implements:
  POST /v1/scripts — validate request, delegate to ExampleContentGenerator,
                     return the Script as JSON.

This stub wraps ExampleContentGenerator (the bundled reference implementation)
so the whole pipeline runs end-to-end without any private dependency.  Any HTTP
service that implements the contract can replace this stub.

Contract invariants enforced:
1. MISSING_DISCLAIMER — 400 if the generated script lacks a disclaimer segment.
2. RECOMMENDATION_DETECTED — 400 if recommendation phrasing is detected.
   (Both are re-validated client-side by the pipeline YMYL guard as well.)
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = FastAPI(title="Content Stub", version="1.0.0")

_CONTRACT_MAJOR = "1"


# ── Request / response models (aligned with content.openapi.yaml) ─────────────


class _FigureItemIn(BaseModel):
    label: str
    value: str


class _ScriptGenerationRequest(BaseModel):
    ticker: str
    company_name: str
    sector: str
    figures: list[_FigureItemIn]


# ── Route ─────────────────────────────────────────────────────────────────────


@app.post("/v1/scripts", status_code=200)
def create_script(body: _ScriptGenerationRequest, response: Response) -> dict[str, Any]:
    """Generate a script via ExampleContentGenerator and return as JSON.

    Enforces contract invariants before returning:
    - Disclaimer segment must be present.
    - No recommendation phrasing (checked by the pipeline YMYL guard).
    """
    response.headers["X-Contract-Version"] = _CONTRACT_MAJOR

    # Import here to avoid circular deps when running tests
    from marketing_shorts_agent.content.example import ExampleContentGenerator
    from marketing_shorts_agent.content.interface import StockInfo
    from marketing_shorts_agent.guards.ymyl import check_script_ymyl
    from marketing_shorts_agent.models import FigureItem

    stock_info = StockInfo(
        ticker=body.ticker,
        company_name=body.company_name,
        sector=body.sector,
        figures=[FigureItem(label=f.label, value=f.value) for f in body.figures],
    )

    generator = ExampleContentGenerator()
    script = generator.generate(stock_info)

    # Enforce contract invariant: disclaimer required
    from marketing_shorts_agent.models import ScriptShotType

    has_disclaimer = any(s.type == ScriptShotType.DISCLAIMER for s in script.segments)
    if not has_disclaimer:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "MISSING_DISCLAIMER",
                "message": "Generated script does not contain a disclaimer segment.",
            },
        )

    # Enforce contract invariant: no recommendation phrasing
    ymyl = check_script_ymyl(script)
    if not ymyl.passed:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "RECOMMENDATION_DETECTED",
                "message": f"Generated script contains recommendation phrasing: {ymyl.violations}",
            },
        )

    # Serialize to wire format (snake_case for segment fields)
    return _script_to_wire(script)


# ── Serialisation helpers ─────────────────────────────────────────────────────


def _script_to_wire(script: object) -> dict[str, Any]:
    """Convert a Script model to the JSON wire format defined in content.openapi.yaml."""
    from marketing_shorts_agent.models import Script

    assert isinstance(script, Script)

    def _segment_to_wire(seg: object) -> dict[str, Any]:
        from marketing_shorts_agent.models import ScriptSegment

        assert isinstance(seg, ScriptSegment)
        out: dict[str, Any] = {
            "type": seg.type.value,
            "text": seg.text,
        }
        if seg.figures:
            out["figures"] = [{"label": f.label, "value": f.value} for f in seg.figures]
        if seg.duration_sec is not None:
            out["duration_sec"] = seg.duration_sec
        return out

    return {
        "ticker": script.ticker,
        "title": script.title,
        "segments": [_segment_to_wire(s) for s in script.segments],
    }
