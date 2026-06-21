"""Evaluator hook against agentops-platform evaluation API.

Triggers an async evaluation run and polls for the result:
  POST /agents/{agentId}/evaluations — start an evaluation
  GET  /evaluations/{evaluationId}  — poll for completion

The evaluator requires a pre-registered eval suite (suiteId).  When
AGENTOPS_DRY_RUN=true (default), all HTTP calls are skipped and a
deterministic mock EvalResult is returned.

Note: the agentops-platform evaluator runs trajectory / drift scoring against
a registered ADK Eval dataset.  It is complementary to (not a replacement for)
the local YMYL guard which runs synchronously before render.
"""

from __future__ import annotations

import logging
import time

import httpx

from ..models import Script
from .interface import EvalResult, EvaluatorInterface

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 15.0
_POLL_INTERVAL_SEC = 2.0
_POLL_TIMEOUT_SEC = 120.0
_PASSED_STATES = {"succeeded"}
_FAILED_STATES = {"failed"}
_TERMINAL_STATES = _PASSED_STATES | _FAILED_STATES


class AgentOpsEvaluatorClient(EvaluatorInterface):
    """Trigger an agentops-platform evaluation run for a script version.

    Args:
        base_url: Base URL of agentops-platform, e.g. ``https://agentops.run.app/v1``.
        agent_id: The agentId under which the version is registered.
        suite_id: The pre-registered eval suiteId to run.
        version_id: The versionId to evaluate (registered by VersionRegisterClient).
        bearer_token: Optional Google-signed ID token for Cloud Run service auth.
        dry_run: When True, skip HTTP and return a passing mock result.
    """

    def __init__(
        self,
        base_url: str,
        agent_id: str,
        suite_id: str,
        version_id: str,
        bearer_token: str | None = None,
        dry_run: bool = True,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._agent_id = agent_id
        self._suite_id = suite_id
        self._version_id = version_id
        self._dry_run = dry_run
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        self._http = httpx.Client(
            base_url=self._base_url,
            headers=headers,
            timeout=_REQUEST_TIMEOUT,
        )

    # ── Public ──────────────────────────────────────────────────────────────

    def evaluate(self, script: Script) -> EvalResult:
        """Start an evaluation run for this script and poll until complete.

        In dry-run mode returns a mock passing result immediately.
        """
        if self._dry_run or not self._base_url:
            logger.info(
                "[DRY-RUN] Skipping agentops-platform evaluation",
                extra={"ticker": script.ticker, "version_id": self._version_id},
            )
            return EvalResult(
                passed=True,
                score=1.0,
                notes="dry-run evaluator — agentops-platform call skipped",
            )

        evaluation_id = self._start_evaluation()
        logger.info(
            "Evaluation started",
            extra={"evaluation_id": evaluation_id, "version_id": self._version_id},
        )

        run = self._poll_evaluation(evaluation_id)
        return self._parse_result(run)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "AgentOpsEvaluatorClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ── Private ─────────────────────────────────────────────────────────────

    def _start_evaluation(self) -> str:
        """POST /agents/{agentId}/evaluations — start evaluation run.

        Returns the evaluationId.
        """
        resp = self._http.post(
            f"/agents/{self._agent_id}/evaluations",
            json={"versionId": self._version_id, "suiteId": self._suite_id},
        )
        resp.raise_for_status()
        return resp.json()["evaluationId"]

    def _poll_evaluation(self, evaluation_id: str) -> dict:
        """GET /evaluations/{evaluationId} — poll until terminal state."""
        deadline = time.monotonic() + _POLL_TIMEOUT_SEC
        while True:
            resp = self._http.get(f"/evaluations/{evaluation_id}")
            resp.raise_for_status()
            run = resp.json()
            state = run.get("state", "")
            logger.debug(
                "Poll evaluation",
                extra={"evaluation_id": evaluation_id, "state": state},
            )
            if state in _TERMINAL_STATES:
                return run
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Evaluation {evaluation_id!r} did not complete within {_POLL_TIMEOUT_SEC}s"
                )
            time.sleep(_POLL_INTERVAL_SEC)

    @staticmethod
    def _parse_result(run: dict) -> EvalResult:
        """Convert an EvaluationRun dict to EvalResult.

        Overall score is the unweighted average of **all** recognised evaluation
        axes returned by agentops-platform.  Currently the platform returns two
        axes — ``drift`` and ``trajectory`` — and both contribute equally to the
        overall score.  Any future axes added to the response will be included
        automatically.  When no axis scores are present the score defaults to 1.0
        on success and 0.0 on failure.
        """
        state = run.get("state", "")
        passed = state in _PASSED_STATES

        scores: list[dict] = run.get("scores", [])
        all_axis_scores = [s["score"] for s in scores if "score" in s]
        overall_score = (
            sum(all_axis_scores) / len(all_axis_scores)
            if all_axis_scores
            else (1.0 if passed else 0.0)
        )

        violations: list[str] = []
        if not passed:
            violations.append(f"Evaluation state={state!r}")
            for s in scores:
                if not s.get("pass", True):
                    violations.append(
                        f"axis={s.get('axis')} score={s.get('score')} threshold={s.get('threshold')}"
                    )

        return EvalResult(
            passed=passed,
            score=float(overall_score),
            violations=violations,
            notes=f"agentops evaluationId={run.get('evaluationId', 'unknown')} state={state}",
        )
