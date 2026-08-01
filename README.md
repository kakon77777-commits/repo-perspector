# GitHub 架構透視器 / Repository Architecture Perspector v0.6

Repository Architecture Perspector 是一個**證據優先、零必要第三方依賴**的儲存庫架構分析器。它把程式碼、依賴、符號、Git 演化、工作區、政策與風險轉換成可追溯的架構中間表示，而不是只生成一張好看的資料夾圖。

v0.6 的核心變化是：分析結果可以被持久記錄成時間序列，因此架構治理從「單次快照」推進到「長期演化觀測」。MCP 介面仍保留，但不是本版重點。

## 快速開始

```bash
python run.py analyze examples/sample_project -o report
```

分析 GitHub Repository：

```bash
python run.py analyze pallets/flask -o flask-report --history-commits 300
```

安裝 wheel 後：

```bash
pip install dist/repo_perspector-0.6.0-py3-none-any.whl
repo-perspector analyze owner/repository -o report
```

主要輸出：

```text
architecture.json          完整架構中間表示
architecture.index.json    緊湊查詢索引
architecture.html          離線互動報告
architecture.mmd           Mermaid 架構圖
architecture.sarif         GitHub Code Scanning SARIF
symbols.json               符號與符號關係
findings.md                架構問題
summary.md                 人類可讀摘要
mssp.config.yaml           MSSP 架構草案
```

## v0.6：持久化架構狀態

分析時直接記錄：

```bash
repo-perspector analyze . \
  -o report \
  --state-dir .perspector-state \
  --record \
  --label main-2026-07-14
```

也可以把既有報告加入狀態庫：

```bash
repo-perspector record report \
  --state-dir .perspector-state \
  --label release-candidate
```

相同架構內容會依內容指紋去重。狀態庫首次寫入時也會鎖定專案身分；不同 Repository 若誤用同一個 `--state-dir`，工具會拒絕寫入，避免污染趨勢。狀態庫採用：

```text
.perspector-state/
├── history.json
└── snapshots/
    └── <timestamp>-<commit>.json.gz
```

生成趨勢報告：

```bash
repo-perspector trend .perspector-state -o architecture-trend
```

輸出：

```text
architecture-trend.json
architecture-trend.md
architecture-trend.html
```

趨勢追蹤：

- 架構健康分數與等級
- 模組、依賴、符號與工作區數量
- error／warning／note 數量
- 循環依賴數量
- critical／high 風險模組
- 演化熱點
- 每次快照相對前一次的變化

## 架構健康分數

v0.6 新增 `quality.health`。分數範圍為 0–100，並提供 A–E 等級與狀態：

```text
healthy / watch / at_risk / critical
```

分數綜合：

- 架構 findings 的嚴重度
- 循環依賴
- critical／high 風險元件
- 時序熱點
- 解析警告與覆蓋率
- 報告是否只完成部分分析

它是**可解釋的架構治理指標**，不是可靠度、故障率或缺陷機率。每項扣分都保存在 `quality.health.penalties`。

## CI 健康閘門

```bash
repo-perspector check report \
  --fail-on warning \
  --min-health 80
```

相對基準線限制退化：

```bash
repo-perspector check current-report \
  --baseline baseline-report \
  --new-only \
  --fail-on warning \
  --fail-on-new-cycle \
  --fail-on-risk-regression \
  --max-health-drop 5
```

`--max-health-drop 5` 表示目前分數相對基準線最多只能下降 5 分。

## 內建治理規則套件

```bash
repo-perspector analyze . --rule-pack balanced
repo-perspector analyze . --rule-pack strict
repo-perspector analyze . --rule-pack legacy
repo-perspector analyze . --rule-pack monorepo
```

套件可重複指定，後面的專案政策仍可覆寫內建設定。

- `balanced`：一般專案的保守門檻。
- `strict`：循環、高風險、熱點與部分規則採較嚴格門檻。
- `legacy`：允許既有架構債務，適合先建立觀測基準。
- `monorepo`：保留零循環要求，但放寬大工作區常見的 fan-out 與數量門檻。

專案政策可調整內建規則：

```yaml
rules:
  architecture.high_fanout:
    severity: error
  architecture.hidden_change_coupling:
    enabled: false

thresholds:
  max_cycles: 0
  min_health: 80
  max_health_drop: 5
```

完整範例見 `.perspector.example.yml`。

## 緊湊查詢索引

`architecture.index.json` 保存元件、符號、依賴與 token 索引，讓大型報告可先做低成本搜尋。

CLI：

```bash
repo-perspector query report search engine
repo-perspector query report search Item --kind symbol
repo-perspector query report search domain --kind component
```

原有查詢仍保留：

```bash
repo-perspector query report overview
repo-perspector query report workspaces
repo-perspector query report components --risk-tier high
repo-perspector query report component src/demo/service
repo-perspector query report path src/demo/api src/demo/models
repo-perspector query report impact src/demo/models
repo-perspector query report symbols --search Item
repo-perspector query report findings --severity error
repo-perspector query report hotspots
repo-perspector query report cochange
```

## Monorepo、插件與增量分析

v0.5 已建立且 v0.6 保留：

- Node、Python、Cargo、Go、Maven、Gradle 工作區辨識
- `.gitignore` 與 `.perspectorignore`
- 生成碼跳過
- 解析器感知持久快取
- 多 worker 解析
- 時間預算與部分報告
- `repo_perspector.parsers` 第三方解析器 entry point
- Git churn、共同變更與 PR 爆炸半徑
- 基準線治理、SARIF 與 GitHub Actions

外部解析器示範在 `examples/parser-plugin/`。

## PR 變更影響

```bash
repo-perspector change-impact current-report \
  --repo . \
  --base origin/main \
  --head HEAD \
  --baseline baseline-report \
  -o pr-impact
```

輸出直接變更模組、傳遞依賴距離、爆炸半徑、風險等級與測試候選。

## 架構政策

Repository 根目錄可放：

```text
.perspector.yml
.perspector.yaml
.perspector.json
```

支援：

- 分層與允許依賴
- 禁止依賴
- 必要元件
- 規則啟停與嚴重度覆寫
- 循環、風險、findings、熱點與健康門檻

即使未安裝 PyYAML，內建受限 YAML 解析器仍可讀取本工具政策使用的子集。

## 測試與驗證

```bash
python -m unittest discover -s tests -v
```

v0.6 包含 16 組單元與整合測試，涵蓋靜態依賴、符號、Git、共同變更、monorepo、插件、快取、政策、SARIF、基準線、PR 影響、健康分數、狀態去重、趨勢輸出與 CI 健康退化阻擋。

詳細結果見 `VALIDATION.md`。

## 邊界

- 非 Python 語言目前仍以宣告級結構解析或外部插件為主。
- 健康分數是治理啟發式，不應被解釋成品質真值。
- 超大型 Repository 應使用忽略規則、快取、時間預算與工作區切分。
- MCP Host／Inspector 實機握手延後處理，本版不以 MCP 完成度作為交付主張。
