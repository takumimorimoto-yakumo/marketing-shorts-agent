"""FastAPI application entry point for marketing-shorts-agent.

Start with::

    uvicorn marketing_shorts_agent.main:app --host 0.0.0.0 --port 8080

Environment variables (see deploy/DEPLOY.md for full reference):

RENDERER_URL
    Base URL of the renderer service, e.g. ``https://renderer.run.app/v1``.
    Empty → the bundled renderer-stub is started in-process automatically.
CONTENT_URL
    Base URL of the content service.  Empty → bundled content-stub.
STORYBOARD_URL
    Base URL of the storyboard service.  Empty → bundled storyboard-stub.
AGENTOPS_BASE_URL
    Base URL of the agentops-platform.  Empty → agentops integration is
    skipped; stub implementations are used for evaluator, analytics, and
    version register (matching the existing PipelineConfig defaults).
DRY_RUN
    ``true`` (default) → the publisher skips the actual YouTube upload and
    returns a mock PublishResult.  Set to ``false`` in production when real
    YouTube credentials are provided.
LOG_LEVEL
    Python log level string (default ``INFO``).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .content import StockInfo
from .models import FigureItem, QaVerdictResult
from .pipeline import PipelineConfig, PipelineOrchestrator, PipelineResult

# ── Logging setup ─────────────────────────────────────────────────────────────

_LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, _LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)

# ── Request / response models ─────────────────────────────────────────────────


class StockInfoRequest(BaseModel):
    """Request body for ``POST /pipeline/run``.

    Mirrors :class:`~marketing_shorts_agent.content.StockInfo`.
    """

    ticker: str
    company_name: str
    sector: str
    figures: list[FigureItem]


class PublishResultResponse(BaseModel):
    """Serialisable form of :class:`~marketing_shorts_agent.publisher.PublishResult`."""

    video_id: str
    url: str
    dry_run: bool


class PipelineResultResponse(BaseModel):
    """Serialisable form of :class:`~marketing_shorts_agent.pipeline.PipelineResult`."""

    success: bool
    ticker: str
    version_id: str
    errors: list[str]
    render_job_id: str
    render_job_state: str
    video_url: str | None
    publish_result: PublishResultResponse | None
    qa_verdict: QaVerdictResult | None = None
    """Video QA result — pass/fail verdict, deterministic check details, visual judgment."""


def _to_response(result: PipelineResult) -> PipelineResultResponse:
    """Convert a :class:`PipelineResult` dataclass to a JSON-serialisable response."""
    pub: PublishResultResponse | None = None
    if result.publish_result is not None:
        pub = PublishResultResponse(
            video_id=result.publish_result.video_id,
            url=result.publish_result.url,
            dry_run=result.publish_result.dry_run,
        )
    return PipelineResultResponse(
        success=result.success,
        ticker=result.ticker,
        version_id=result.version_id,
        errors=result.errors,
        render_job_id=result.render_job.render_id,
        render_job_state=result.render_job.state.value,
        video_url=result.render_job.video_url,
        publish_result=pub,
        qa_verdict=result.qa_verdict,
    )


# ── Global orchestrator ───────────────────────────────────────────────────────

_orchestrator: PipelineOrchestrator | None = None


def _build_orchestrator() -> PipelineOrchestrator:
    """Construct the :class:`PipelineOrchestrator` from environment variables.

    When ``RENDERER_URL`` is empty the bundled renderer-stub is started
    in-process on a free port and its URL is forwarded to :class:`PipelineConfig`.
    Content- and storyboard-stub startup is delegated to
    :class:`PipelineOrchestrator` itself (existing behaviour).

    When ``AGENTOPS_BASE_URL`` is empty the default stub implementations are
    used for the evaluator, analytics, and version-register steps — no network
    calls are made (matching the existing ``PipelineConfig`` defaults).
    """
    renderer_url: str = os.environ.get("RENDERER_URL", "").strip()
    content_url: str = os.environ.get("CONTENT_URL", "").strip()
    storyboard_url: str = os.environ.get("STORYBOARD_URL", "").strip()
    dry_run: bool = os.environ.get("DRY_RUN", "true").strip().lower() not in (
        "false",
        "0",
        "no",
    )

    if not renderer_url:
        # Import helpers from orchestrator to reuse port-allocation + stub-startup logic.
        from .pipeline.orchestrator import _allocate_port, _start_stub_server  # noqa: PLC0415
        from renderer_stub.app import app as _renderer_stub_app  # noqa: PLC0415

        port = _allocate_port(18080)
        _start_stub_server(_renderer_stub_app, "127.0.0.1", port)
        renderer_url = f"http://127.0.0.1:{port}/v1"
        logger.info("Bundled renderer-stub started", extra={"url": renderer_url})

    agentops_base_url: str = os.environ.get("AGENTOPS_BASE_URL", "").strip()
    agentops_agent_id: str = os.environ.get("AGENTOPS_AGENT_ID", "marketing-shorts-agent").strip()
    agentops_api_key: str = os.environ.get("AGENTOPS_API_KEY", "").strip()

    # ── Video QA ─────────────────────────────────────────────────────────────
    video_qa_use_gemini_str: str = os.environ.get("VIDEO_QA_USE_GEMINI", "false").strip().lower()
    video_qa_use_gemini: bool = video_qa_use_gemini_str in ("true", "1", "yes")
    video_qa_gemini_backend: str = os.environ.get("VIDEO_QA_GEMINI_BACKEND", "genai").strip()

    video_qa = None
    if video_qa_use_gemini:
        from .video_qa import VideoQAClient  # noqa: PLC0415

        video_qa = VideoQAClient(
            gemini_model=os.environ.get("GEMINI_EVAL_MODEL", "gemini-2.5-flash").strip(),
            gemini_backend=video_qa_gemini_backend,
            gcp_project=os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip(),
            gcp_region=os.environ.get("GOOGLE_CLOUD_REGION", "us-central1").strip(),
        )
        logger.info(
            "VideoQA live client configured",
            extra={"backend": video_qa_gemini_backend},
        )
    else:
        logger.info("VIDEO_QA_USE_GEMINI not set; VideoQAStub used (always passes)")

    version_register = None
    analytics = None

    if agentops_base_url:
        from .analytics.client import AgentOpsAnalyticsClient  # noqa: PLC0415
        from .version_register.client import AgentOpsVersionRegisterClient  # noqa: PLC0415

        bearer_token: str | None = agentops_api_key if agentops_api_key else None

        version_register = AgentOpsVersionRegisterClient(
            base_url=agentops_base_url,
            bearer_token=bearer_token,
            dry_run=False,
        )
        analytics = AgentOpsAnalyticsClient(
            base_url=agentops_base_url,
            bearer_token=bearer_token,
            dry_run=False,
        )
        logger.info(
            "AgentOps live clients configured",
            extra={
                "agentops_base_url": agentops_base_url,
                "agent_id": agentops_agent_id,
                "auth": "bearer" if bearer_token else "none",
            },
        )
    else:
        logger.info(
            "AGENTOPS_BASE_URL not set; stub implementations used for "
            "version-register and analytics"
        )

    config = PipelineConfig(
        renderer_base_url=renderer_url,
        content_url=content_url,
        storyboard_url=storyboard_url,
        dry_run=dry_run,
        agent_id=agentops_agent_id,
        version_register=version_register,
        analytics=analytics,
        video_qa=video_qa,
    )
    logger.info(
        "Building PipelineOrchestrator",
        extra={
            "renderer_base_url": renderer_url,
            "content_url": content_url or "(bundled stub)",
            "storyboard_url": storyboard_url or "(bundled stub)",
            "dry_run": dry_run,
        },
    )
    return PipelineOrchestrator(config)


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def _lifespan(application: FastAPI):  # noqa: ARG001
    """Start the pipeline orchestrator (and any bundled stubs) on app startup."""
    global _orchestrator  # noqa: PLW0603

    logger.info("marketing-shorts-agent starting up")
    _orchestrator = _build_orchestrator()
    logger.info(
        "Pipeline orchestrator ready",
        extra={"dry_run": _orchestrator._config.dry_run},
    )

    yield

    logger.info("marketing-shorts-agent shutting down")


# ── FastAPI application ───────────────────────────────────────────────────────

app = FastAPI(
    title="marketing-shorts-agent",
    version="0.1.0",
    description=(
        "Autonomous AI agent that turns Japanese-stock financial data into "
        "YouTube Shorts — from script generation through render — in a single pipeline call."
    ),
    lifespan=_lifespan,
)

# ── Endpoints ─────────────────────────────────────────────────────────────────

_PIPELINE_STAGES = [
    ("Content generation（スクリプト生成）", "決算データから YouTube Shorts 台本を自動生成する。外部 content サービスまたは組み込みスタブを使用。"),
    ("YMYL guard（スクリプト）", "投資推奨・数値改変がないかチェックする YMYL ガード。免責事項が含まれているか、推奨表現がないかを確認する。"),
    ("Evaluator hook（軌跡評価）", "AgentOps Platform へパイプライン軌跡・ドリフトスコアを送信する評価フック。"),
    ("Storyboard generation（絵コンテ生成）", "台本を元に各カットの構成・テキスト・レイアウトを定義した絵コンテを生成する。"),
    ("YMYL guard（絵コンテ）", "絵コンテに投資推奨・不適切な数値表現が含まれていないかを再確認するガード。"),
    ("Renderer submit &amp; wait（レンダリング）", "外部レンダラーまたは組み込み renderer-stub に映像生成ジョブを送信し、完了を待機する。"),
    ("Video QA（映像品質検証）", "ffprobe による決定論的チェック（解像度・コーデック等）と Gemini 視覚判定を組み合わせた fail-closed ゲート。スタブ出力を却下することは意図した挙動。"),
    ("Publisher（公開）", "YouTube Shorts へアップロードする。デフォルトはドライラン。Video QA 不合格の場合はスキップされる。"),
    ("Version register（バージョン登録）", "AgentOps Platform にパイプライン実行バージョンを自動登録する。"),
    ("Analytics push（メトリクス送信）", "Video QA 結果を含むパイプライン実行メトリクスを AgentOps Platform へ送信する。"),
]

_LANDING_HTML = """\
<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>marketing-shorts-agent</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      font-family: "Helvetica Neue", Arial, "Hiragino Kaku Gothic ProN", "Hiragino Sans", Meiryo, sans-serif;
      max-width: 800px;
      margin: 0 auto;
      padding: 48px 24px 80px;
      color: #111;
      background: #fff;
      line-height: 1.7;
    }}
    h1 {{
      font-size: 1.6rem;
      font-weight: 700;
      margin: 0 0 0.2rem;
      letter-spacing: -0.01em;
    }}
    .sub {{ color: #555; font-size: 0.85rem; margin: 0 0 0.6rem; }}
    .tagline {{
      font-size: 1.05rem;
      color: #222;
      margin: 0 0 2rem;
      padding: 0.75rem 1rem;
      border-left: 3px solid #111;
      background: #f8f8f8;
    }}
    h2 {{
      font-size: 1rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: #444;
      margin: 2.5rem 0 0.75rem;
      padding-bottom: 0.3rem;
      border-bottom: 1px solid #ddd;
    }}
    .stages {{ list-style: none; padding: 0; margin: 0; }}
    .stages li {{
      display: flex;
      gap: 0.75rem;
      padding: 0.5rem 0;
      border-bottom: 1px solid #f0f0f0;
    }}
    .stage-num {{
      flex-shrink: 0;
      width: 1.6rem;
      height: 1.6rem;
      background: #111;
      color: #fff;
      border-radius: 50%;
      font-size: 0.75rem;
      font-weight: 700;
      display: flex;
      align-items: center;
      justify-content: center;
      margin-top: 0.15rem;
    }}
    .stage-body {{ flex: 1; }}
    .stage-name {{ font-weight: 600; font-size: 0.9rem; display: block; }}
    .stage-desc {{ font-size: 0.85rem; color: #555; }}
    .features {{ list-style: none; padding: 0; margin: 0; }}
    .features li {{
      padding: 0.6rem 0.8rem;
      margin-bottom: 0.5rem;
      background: #f8f8f8;
      border-radius: 4px;
      font-size: 0.9rem;
    }}
    .features li strong {{ display: block; margin-bottom: 0.2rem; }}
    .note {{
      font-size: 0.8rem;
      color: #777;
      margin-top: 0.25rem;
    }}
    .links {{ list-style: none; padding: 0; margin: 0; }}
    .links li {{ margin-bottom: 0.5rem; font-size: 0.9rem; }}
    a {{ color: #0057b8; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    code {{
      background: #f0f0f0;
      padding: 2px 6px;
      border-radius: 3px;
      font-size: 0.85em;
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    }}
    pre {{
      background: #1a1a1a;
      color: #e8e8e8;
      padding: 1rem 1.2rem;
      border-radius: 6px;
      overflow-x: auto;
      font-size: 0.82rem;
      line-height: 1.6;
      margin: 0.5rem 0 0;
    }}
    .section-links {{ display: flex; gap: 1rem; flex-wrap: wrap; margin-top: 0.5rem; }}
    .section-links a {{
      padding: 0.35rem 0.75rem;
      border: 1px solid #0057b8;
      border-radius: 4px;
      font-size: 0.85rem;
    }}
    .section-links a:hover {{ background: #0057b8; color: #fff; text-decoration: none; }}
  </style>
</head>
<body>

  <h1>marketing-shorts-agent</h1>
  <p class="sub">DevOps AI Agent Hackathon — AgentOps Platform 連携デモ</p>
  <p class="tagline">
    決算データから YouTube Shorts を生成するパイプラインを、一気通貫で編成・品質保証する AI エージェント。<br>
    台本・絵コンテ・レンダラは OpenAPI 契約で分離された差し替え可能な外部サービス（同梱スタブで全ステージ検証可能）。<br>
    AgentOps Platform の管理下で稼働する「被管理エージェント」の実例。
  </p>

  <h2>パイプラインステージ</h2>
  <ol class="stages">
{stages}
  </ol>

  <h2>主な特徴</h2>
  <ul class="features">
    <li>
      <strong>YMYL ガード（投資推奨拒否・数値改変不可）</strong>
      スクリプト・絵コンテの両段階で「投資推奨を含む文章」「数値の書き換え」を検出してパイプラインを停止する。
      金融コンテンツ（Your Money or Your Life）の安全基準に準拠する 2 層ガード。
    </li>
    <li>
      <strong>自律 Video QA（決定論 + Gemini 視覚判定・fail-closed）</strong>
      ffprobe による解像度・コーデック等の決定論的チェックと、Gemini による視覚的品質判定を組み合わせたゲート。
      いずれかが不合格の場合はパブリッシュをスキップする（fail-closed 設計）。
      <span class="note">※ スタブモードでは Gemini は実行されず常に pass となる。スタブ出力を却下するケースは <strong>意図した挙動</strong>であり、Video QA が正常に機能していることを示す。</span>
    </li>
    <li>
      <strong>AgentOps 連携（バージョン・メトリクス自動報告・自己回復）</strong>
      各パイプライン実行のバージョン ID・評価スコア・Video QA 結果を AgentOps Platform へ自動送信する。
      <code>AGENTOPS_BASE_URL</code> を設定しない場合はスタブが使われ、ネットワーク不要で動作する。
    </li>
  </ul>

  <h2>API の使い方</h2>
  <p><strong>パイプライン実行</strong> — <code>POST /pipeline/run</code></p>
  <pre>curl -X POST https://&lt;HOST&gt;/pipeline/run \\
  -H "Content-Type: application/json" \\
  -d '{{"ticker":"7203","company_name":"トヨタ自動車","sector":"輸送用機器","figures":[{{"label":"売上高","value":"¥45兆円"}}]}}'</pre>

  <div class="section-links">
    <a href="/docs">API ドキュメント (Swagger UI)</a>
    <a href="/redoc">ReDoc</a>
    <a href="/healthz">ヘルスチェック</a>
    <a href="https://agentops-platform-nk3aomvl6q-an.a.run.app/dashboard" target="_blank" rel="noopener">AgentOps ダッシュボード ↗</a>
    <a href="https://github.com/takumimorimoto-yakumo/marketing-shorts-agent" target="_blank" rel="noopener">GitHub ↗</a>
  </div>

</body>
</html>
""".format(
    stages="\n".join(
        f'    <li><span class="stage-num">{i + 1}</span>'
        f'<span class="stage-body"><span class="stage-name">{name}</span>'
        f'<span class="stage-desc">{desc}</span></span></li>'
        for i, (name, desc) in enumerate(_PIPELINE_STAGES)
    )
)


@app.get("/healthz", summary="Health check")
def health() -> dict[str, str]:
    """Return ``{"status": "ok"}`` when the service is running."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def landing() -> str:
    """HTML landing page with agent description and API links."""
    return _LANDING_HTML


@app.post(
    "/pipeline/run",
    response_model=PipelineResultResponse,
    summary="Run the Shorts generation pipeline",
)
def pipeline_run(request: StockInfoRequest) -> PipelineResultResponse:
    """Execute the full Shorts generation pipeline for a single stock.

    Accepts stock financial data and runs the end-to-end pipeline
    (content → YMYL → storyboard → render → publish).  Returns the pipeline
    result including render-job state and publish result.

    Runs synchronously; expect a few seconds in bundled-stub mode.
    Set ``DRY_RUN=false`` and provide YouTube credentials to enable real upload.
    """
    if _orchestrator is None:  # pragma: no cover — lifespan guarantees initialisation
        raise RuntimeError("Pipeline orchestrator is not initialised")

    stock_info = StockInfo(
        ticker=request.ticker,
        company_name=request.company_name,
        sector=request.sector,
        figures=list(request.figures),
    )
    result = _orchestrator.run(stock_info)
    return _to_response(result)
