# marketing-shorts-agent

Marketing video agent for メイガラシリタイ — generates and publishes Japanese-stock YouTube Shorts, operated on top of agentops-platform.

## コミュニケーション
- 日本語で回答すること。コードのコメント・docstring・README は英語

## グローバル原則の継承

開発系エージェント（system-developer / web-developer）の共通原則は `~/.claude/docs/dev-principles.md` に集約されている。このプロジェクトでも同じ原則に従う。

## スコープ

| 含める | 含めない |
|---|---|
| 個別銘柄解説 shorts の量産 + YouTube Shorts 投稿 | 長尺動画 |
| Analytics → eval → 改善 PR ループ（agentops-platform と連動） | 独立した自己改善ループ実装 |
| メイガラシリタイ 専用台本テンプレ・サムネテンプレ | 汎用動画スキーマ・抽象化レイヤ |
| YMYL 免責 / 銘柄推奨禁止ガード | エージェント協調設計 |
| renderer-stub（黒背景 + テキストの mp4） | レンダラ本体（外部 HTTP サービス） |

レンダラは外部サービスとして HTTP API（OpenAPI 契約は公開）で分離。このリポにはスタブのみ同梱する。

## コンテンツガード（YMYL・最重要）

- 銘柄推奨表現は禁止（テンプレレベルで担保、Gemini eval で違反検出）
- 免責テロップ必須
- データソースは公式一次データ（EDINET / J-Quants 等）のみ。企業ロゴ不使用、ティッカー表示で代替
- AI 生成であることは YouTube 上で開示する

## 技術スタック

ADK + Gemini API（台本）/ Veo（フック・B-roll）/ Imagen（サムネ）/ Chirp（TTS）/ Lyria（BGM）/ Cloud Run / BigQuery。**外部 LLM への依存は一切追加しない**。

## SSOT マップ（ハードコード禁止カテゴリ）

| カテゴリ | 格納場所 |
|---|---|
| 台本テンプレ・免責文言 | `config/templates/`（実装時に作成） |
| renderer API エンドポイント | `.env.example` + config 層 |
| Gemini / Veo モデル ID | config 層（コード直書き禁止） |

実装前に該当ファイルを Grep し、見つからなければ SSOT に追加してから参照する。

## Git
- コミットメッセージは英語
- 作業ブランチ: `develop`（`main` への直接コミット禁止）
- ライセンス: Apache-2.0、著作権者は個人名（`Copyright (c) 2026 Takumi Morimoto`）
- コミット時のユーザー情報:
```bash
git -c user.name="takumimorimoto-yakumo" -c user.email="takumi.morimoto@yakumo.world" commit -m "..."
```
