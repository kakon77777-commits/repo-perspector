# Changelog

## 0.6.0 — 2026-07-14

- 新增持久化架構狀態庫：`record_snapshot`、gzip 完整報告快照、內容指紋去重、專案身分鎖定與 retention。
- 新增 `repo-perspector record` 與 `repo-perspector trend`。
- `analyze` 新增 `--state-dir`、`--record`、`--label`、`--retention`。
- 新增 0–100 架構健康分數、A–E 等級、狀態、訊號與逐項扣分。
- `check` 新增 `--min-health` 與 baseline-aware `--max-health-drop`。
- 基準線與架構 diff 新增健康分數變化。
- 新增 `balanced`、`strict`、`legacy`、`monorepo` 內建治理套件。
- 專案政策新增 built-in finding 啟停與 severity override。
- 新增 `architecture.index.json` 緊湊查詢索引與 `query search`。
- 趨勢輸出包含 JSON、Markdown 與離線 HTML 折線圖。
- schema 升級至 `repo-perspector.ir/v0.6`；cache、symbols、diff、baseline、change-impact 同步升級。
- 新增狀態去重、趨勢、健康退化 CI 與規則套件測試；測試總數增至 16。

## 0.5.0 — 2026-07-14

- 新增 monorepo／workspace 邊界辨識。
- 新增 `.gitignore`、`.perspectorignore` 與生成碼排除。
- 新增並行解析、時間預算、部分報告與解析覆蓋資訊。
- 新增 `repo_perspector.parsers` entry-point 插件介面與 `.xyz` 示範插件。
- 快取 schema 升級，內容指紋納入 parser identity；快取操作改為執行緒安全。
- 重構 inventory 為掃描、映射、解析與編排階段。

## 0.4.0 — 2026-07-14

- 新增增量解析快取、基準線治理、PR 變更影響與自身高耦合重構。

## 0.3.0 — 2026-07-14

- 新增符號／呼叫圖、共同變更、政策、SARIF 與 CI 架構閘門。

## 0.2.0 — 2026-07-14

- 新增 Git 演化、爆炸半徑、風險模型、架構差分與唯讀查詢。

## 0.1.0 — 2026-07-14

- 首個靜態證據層 MVP。
