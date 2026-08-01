# Project Manifest — v0.6.0

## 根目錄

- `README.md` — 安裝、分析、狀態、趨勢、規則套件與 CI 使用說明。
- `CHANGELOG.md` — v0.1–v0.6 版本紀錄。
- `VALIDATION.md` — 測試、格式、安裝與命令列驗證。
- `BENCHMARK.md` — 合成倉庫與狀態庫基準。
- `SECURITY.md` — 安全邊界。
- `LICENSE` — MIT。
- `.perspector.example.yml` — 分層、規則覆寫與健康門檻範例。
- `pyproject.toml` — Python 套件設定。
- `run.py` — 不安裝套件時的入口。

## v0.6 新增核心

- `src/repo_perspector/health.py` — 可解釋的架構健康分數。
- `src/repo_perspector/state.py` — 專案鎖定、gzip 快照、去重、retention、趨勢輸出。
- `src/repo_perspector/rule_packs.py` — balanced／strict／legacy／monorepo 治理套件與規則覆寫。
- `src/repo_perspector/indexer.py` — 緊湊的元件／符號查詢索引。

## 既有分析核心

- `analyzer.py`、`report_builder.py` — 分析入口與階段編排。
- `inventory_scan.py`、`inventory_mapping.py`、`file_parsing.py`、`inventory.py` — 掃描、工作區映射、解析、快取與並行。
- `parser_plugins.py`、`parsers.py`、`symbols.py` — 內建與第三方語言解析。
- `graph_builder.py`、`impact.py`、`quality.py`、`heuristics.py` — 依賴圖、爆炸半徑、風險與架構判斷。
- `history.py` — Git churn 與共同變更。
- `policy.py`、`checking.py`、`baseline.py` — 政策與 CI 基準線治理。
- `change_impact.py`、`diffing.py` — PR 影響與架構差分。
- `query.py`、`command_query.py` — 唯讀查詢。
- `renderers.py`、`sarif.py` — JSON、索引、HTML、Mermaid、MSSP、Markdown、SARIF。
- `mcp_server.py` — 保留的選用 MCP 介面；v0.6 未把 MCP 實機握手列為完成項目。

## 測試與範例

- `tests/test_analyzer.py` — 16 組單元與整合測試。
- `examples/sample_project/` — 基本 Python 範例。
- `examples/monorepo_sample/` — 多工作區與生成碼範例。
- `examples/parser-plugin/` — `.xyz` 外部解析器插件。
- `examples/github-actions/` — SARIF、PR gate、狀態與趨勢工作流。

## 生成驗證產物

- `demo_output/` — 基本範例完整報告。
- `monorepo_demo/` — 工作區範例報告。
- `self_report/` — v0.6 分析自身。
- `diff_demo/` — v0.5 → v0.6 差分。
- `state_demo/` — 兩份完整 gzip 架構快照與 manifest。
- `trend_demo/` — 健康基準 → 人為循環退化的趨勢報告。
- `change_impact_demo/` — PR 影響範例。
- `benchmarks/` — 原始基準 JSON。
- `dist/repo_perspector-0.6.0-py3-none-any.whl` — 可安裝 wheel。
