"""Tests for content generator and storyboard generator."""

from __future__ import annotations

import pytest

from marketing_shorts_agent.content import ExampleContentGenerator, StockInfo
from marketing_shorts_agent.guards import check_script_ymyl
from marketing_shorts_agent.models import FigureItem, ScriptShotType, ShotType
from marketing_shorts_agent.storyboard import ExampleStoryboardGenerator


class TestExampleContentGenerator:
    def _stock_info(self, ticker: str = "7203") -> StockInfo:
        return StockInfo(
            ticker=ticker,
            company_name="テスト株式会社",
            sector="製造業",
            figures=[
                FigureItem(label="PER", value="12.3x"),
                FigureItem(label="PBR", value="1.2x"),
                FigureItem(label="売上高", value="¥1,234億"),
            ],
        )

    def test_generates_script_with_disclaimer(self):
        gen = ExampleContentGenerator()
        script = gen.generate(self._stock_info())
        types = [s.type for s in script.segments]
        assert ScriptShotType.DISCLAIMER in types

    def test_generated_script_passes_ymyl(self):
        gen = ExampleContentGenerator()
        script = gen.generate(self._stock_info())
        result = check_script_ymyl(script)
        assert result.passed, f"YMYL violations: {result.violations}"

    def test_generated_script_contains_ticker(self):
        gen = ExampleContentGenerator()
        script = gen.generate(self._stock_info("7203"))
        assert script.ticker == "7203"

    def test_figures_preserved(self):
        gen = ExampleContentGenerator()
        stock = self._stock_info()
        script = gen.generate(stock)
        # Find the figures segment
        figures_segs = [s for s in script.segments if s.type == ScriptShotType.FIGURES]
        assert figures_segs, "Script must contain a figures segment"
        seg_figures = figures_segs[0].figures
        assert len(seg_figures) == len(stock.figures)
        for orig, gen_fig in zip(stock.figures, seg_figures):
            assert gen_fig.label == orig.label
            assert gen_fig.value == orig.value


class TestExampleStoryboardGenerator:
    def _make_script_via_generator(self) -> object:
        stock = StockInfo(
            ticker="0001",
            company_name="サンプル株式会社",
            sector="情報技術",
            figures=[FigureItem(label="PER", value="20x")],
        )
        return ExampleContentGenerator().generate(stock)

    def test_storyboard_has_disclaimer_shot(self):
        gen = ExampleStoryboardGenerator()
        script = self._make_script_via_generator()
        storyboard = gen.generate(script)
        assert storyboard.has_disclaimer()

    def test_storyboard_figure_overlays_match_script(self):
        """Figure overlays in storyboard must exactly match the script's figures."""
        gen = ExampleStoryboardGenerator()
        script = self._make_script_via_generator()
        storyboard = gen.generate(script)

        # Collect figures from script
        script_figures = [
            (f.label, f.value)
            for seg in script.segments
            if seg.type == ScriptShotType.FIGURES
            for f in seg.figures
        ]

        # Collect figure overlays from storyboard
        storyboard_figures = [
            (o.label, o.value)
            for o in storyboard.all_figure_overlays()
        ]

        assert storyboard_figures == script_figures, (
            f"Figure mismatch: script={script_figures}, storyboard={storyboard_figures}"
        )

    def test_all_scenes_have_at_least_one_shot(self):
        gen = ExampleStoryboardGenerator()
        script = self._make_script_via_generator()
        storyboard = gen.generate(script)
        for scene in storyboard.scenes:
            assert len(scene.shots) >= 1

    def test_shot_types_match_segment_types(self):
        """Each shot type should correspond to the original segment type."""
        gen = ExampleStoryboardGenerator()
        script = self._make_script_via_generator()
        storyboard = gen.generate(script)

        shot_types = [
            shot.type
            for scene in storyboard.scenes
            for shot in scene.shots
        ]
        segment_types = [ShotType(s.type.value) for s in script.segments]
        assert shot_types == segment_types
