"""Generic example content generator.

Produces a coherent, on-format commentary script using a template approach.
This is NOT a no-op: it generates a real, watchable script structure.

This generator is intentionally generic (not channel-tuned). A production
generator is plugged in via config and implements ContentGeneratorInterface.
"""

from __future__ import annotations

import textwrap

from ..models import FigureItem, Script, ScriptSegment, ScriptShotType
from .interface import ContentGeneratorInterface, StockInfo

# Disclaimer text loaded at module level; in production this comes from
# config/templates/disclaimer_ja.txt via the config loader.
_DISCLAIMER_TEXT = (
    "【免責事項】この動画は情報提供のみを目的としており、"
    "特定の銘柄への投資を推奨するものではありません。"
    "投資は自己責任でご判断ください。"
)


class ExampleContentGenerator(ContentGeneratorInterface):
    """Template-based generic script generator (bundled reference implementation).

    Produces a ~60-second commentary script for any Japanese stock, given
    pre-verified figures.  No LLM call; deterministic from input.

    Swap in a production subclass (with Gemini, private prompts, etc.) via config.
    """

    def generate(self, stock_info: StockInfo) -> Script:
        """Build a YMYL-compliant script from StockInfo."""
        segments: list[ScriptSegment] = []

        # 1. Hook
        segments.append(
            ScriptSegment(
                type=ScriptShotType.HOOK,
                text=f"{stock_info.company_name}（{stock_info.ticker}）を60秒で解説します！",
                duration_sec=5.0,
            )
        )

        # 2. Company intro narration
        segments.append(
            ScriptSegment(
                type=ScriptShotType.NARRATION,
                text=textwrap.dedent(f"""\
                    {stock_info.company_name}は{stock_info.sector}セクターの企業です。
                    今回は公式データをもとに最新の主要指標をお伝えします。
                """).strip(),
                duration_sec=10.0,
            )
        )

        # 3. Figures display
        if stock_info.figures:
            segments.append(
                ScriptSegment(
                    type=ScriptShotType.FIGURES,
                    text="主要財務指標をご覧ください。",
                    figures=list(stock_info.figures),
                    duration_sec=15.0,
                )
            )

        # 4. Commentary narration
        figure_summary = self._build_figure_summary(stock_info.figures)
        segments.append(
            ScriptSegment(
                type=ScriptShotType.NARRATION,
                text=textwrap.dedent(f"""\
                    以上が{stock_info.company_name}の直近データです。
                    {figure_summary}
                    詳細は各自で一次情報をご確認ください。
                """).strip(),
                duration_sec=20.0,
            )
        )

        # 5. Mandatory disclaimer (YMYL)
        segments.append(
            ScriptSegment(
                type=ScriptShotType.DISCLAIMER,
                text=_DISCLAIMER_TEXT,
                duration_sec=5.0,
            )
        )

        return Script(
            ticker=stock_info.ticker,
            title=f"{stock_info.company_name}（{stock_info.ticker}）最新データ解説",
            segments=segments,
        )

    @staticmethod
    def _build_figure_summary(figures: list[FigureItem]) -> str:
        """Build a short human-readable summary of provided figures."""
        if not figures:
            return ""
        items = "、".join(f"{fig.label} {fig.value}" for fig in figures[:3])
        return f"主な指標は{items}などとなっています。"
