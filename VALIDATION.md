# Validation Report — v0.6.0

驗證日期：2026-07-14

## 1. 自動化測試

執行：

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

結果：

```text
Ran 16 tests
OK
```

覆蓋：

- Python import、符號與呼叫關係
- Git churn、共同變更與查詢
- 架構政策、SARIF 與 CI gate
- 架構差分與 workspace 邊界
- 增量快取與 parser identity 失效
- 基準線既有債務抑制與新循環偵測
- PR 直接／傳遞影響
- monorepo、忽略規則、生成碼與並行掃描
- 外部解析器 registry
- 部分報告與時間預算
- 健康分數與規則套件
- 緊湊查詢索引
- 狀態快照內容去重
- 不同 Repository 狀態庫污染拒絕
- 趨勢 JSON／Markdown／HTML
- CI 最低健康與健康退化阻擋

## 2. 命令列端到端情境

使用範例專案建立健康基準，再加入反向依賴形成循環：

```text
基準健康：98.00（A / healthy）
退化健康：70.00（C / at_risk）
趨勢變化：-28.00
新循環：1
新 error：1
critical 元件：1
```

執行 baseline-aware gate：

```bash
repo-perspector check current-report \
  --baseline baseline-report \
  --new-only \
  --fail-on warning \
  --fail-on-new-cycle \
  --max-health-drop 1
```

結果程序碼為 `1`，並同時指出：

- finding severity 失敗
- 新循環失敗
- 健康退化失敗
- 基準線健康 `98 → 70`

## 3. 自我透視

v0.6 以 8 workers、跳過生成碼、關閉 Git 歷史分析自身，暖啟動結果：

```text
檔案：78
架構模組：45
內部依賴：87
符號：245
符號關係：380
工作區：6
架構 findings：0
健康：98.00（A / healthy）
快取：52 hit / 0 miss / 100%
```

唯一健康扣分來自 1 個 high-risk 元件，沒有 error、warning、note、循環、critical 元件、熱點或解析警告。

## 4. 格式與語法

- Python `compileall`：通過。
- JSON：19 份全部可解析。
- gzip 架構快照：2 份全部可解壓，schema 為 `repo-perspector.ir/v0.6`。
- SARIF：3 份，全部為 SARIF `2.1.0`。
- YAML：以 PyYAML 驗證 `.perspector.example.yml` 與所有 `mssp.config.yaml`，全部通過。
- HTML JavaScript：4 段可執行 script 以 `node --check` 驗證，全部通過。
- 趨勢 HTML 為單檔離線輸出，不需要外部 CDN。

## 5. wheel 與隔離安裝

建立：

```text
dist/repo_perspector-0.6.0-py3-none-any.whl
```

SHA-256：

```text
60741712bee37812f5b615bafb0226b7b037726064ed425661b0e0fa9e794ea7
```

在全新 virtual environment 中：

- `pip install --no-deps` 成功。
- `repo-perspector --version` 回傳 `0.6.0`。
- 安裝版成功分析範例專案並輸出九種報告。
- 安裝 `.xyz` 外部 parser plugin 成功。
- entry point 正確載入 `demo-xyz-parser@0.1.0`。
- `sample.xyz` 正確產生 `sample.hello` 符號。

## 6. 狀態庫與趨勢

- 完整報告以 gzip 儲存。
- 相同架構內容指紋可正確去重。
- 狀態庫首次記錄後鎖定 project key。
- 不同專案寫入同一狀態庫會拋出錯誤。
- retention 會移除最舊 manifest 項目與對應 gzip。
- 兩點趨勢範例正確呈現 `98 → 70` 與 `-28`。

## 7. 效能邊界

- 1,200 個 Python 模組：解析快取命中 100%，但端到端沒有加速，顯示圖與品質計算才是該樣本主要成本。
- 50 份完整自我報告快照：平均寫入約 38.654 ms。
- 50 點趨勢聚合：約 0.000690 秒。
- JSON／Markdown／HTML 趨勢渲染：約 0.008566 秒。

詳見 `BENCHMARK.md`。

## 8. 明確未完成邊界

- MCP 程式與既有介面保留，但依照本輪決定，未進行真實 MCP Host／Inspector 握手，因此不列為 v0.6 的完成主張。
- 非 Python 語言仍主要是宣告級結構解析；深層語義需外部 parser plugin。
- 健康分數是可解釋治理啟發式，不是可靠度或缺陷機率。
