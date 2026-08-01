from __future__ import annotations

from collections import Counter
from pathlib import PurePosixPath


IGNORE_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode", ".venv", "venv", "env",
    "node_modules", "vendor", "dist", "build", "target", "coverage", ".coverage",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    "site-packages", "Pods", ".next", ".nuxt", ".cache", ".repo-perspector-cache",
    "architecture-report", "architecture-diff", "change-impact", "baseline-report", "current-report",
    "demo_output", "monorepo_demo", "self_report", "diff_demo", "change_impact_demo",
    "state_demo", "trend_demo", "architecture-trend", ".perspector-state",
}

SOURCE_ROOT_NAMES = {"src", "lib", "app", "apps", "packages", "crates", "cmd", "internal", "pkg"}

ROLE_RULES: list[tuple[set[str], str, str]] = [
    ({"test", "tests", "spec", "specs"}, "tests", "測試、驗證與回歸保護"),
    ({"doc", "docs", "documentation"}, "documentation", "文件、教學與架構說明"),
    ({"example", "examples", "demo", "demos", "sample", "samples"}, "examples", "範例、展示與使用情境"),
    ({"plugin", "plugins", "extension", "extensions", "contrib", "integration", "integrations"}, "extension", "可插拔功能或外部整合"),
    ({"api", "routes", "router", "endpoint", "endpoints", "http", "web"}, "interface", "外部介面、路由或協定邊界"),
    ({"cli", "command", "commands"}, "cli", "命令列入口與操作介面"),
    ({"builder", "orchestrator", "orchestration", "pipeline"}, "orchestration", "低狀態的流程編排、階段組合與報告建構"),
    ({"model", "models", "entity", "entities", "schema", "schemas"}, "data_model", "資料模型、實體與結構定義"),
    ({"db", "database", "storage", "repository", "repositories", "persistence", "orm"}, "persistence", "資料持久化與儲存抽象"),
    ({"service", "services", "usecase", "usecases", "application"}, "service", "應用服務、用例編排與業務流程"),
    ({"domain", "core", "kernel", "engine", "runtime"}, "core", "核心領域、執行引擎或系統內核"),
    ({"controller", "controllers", "handler", "handlers"}, "controller", "請求協調、控制與事件處理"),
    ({"view", "views", "ui", "frontend", "components"}, "presentation", "使用者介面與呈現層"),
    ({"auth", "security", "permission", "permissions"}, "security", "身份、權限與安全控制"),
    ({"config", "configuration", "settings"}, "configuration", "設定、環境與組態管理"),
    ({"util", "utils", "common", "shared", "helper", "helpers"}, "utility", "共用工具與跨模組輔助功能"),
    ({"adapter", "adapters", "port", "ports", "gateway", "gateways"}, "adapter", "外部系統適配與邊界轉換"),
    ({"event", "events", "queue", "messaging", "worker", "workers", "jobs"}, "async", "事件、佇列與背景工作"),
]


def tokens_for(path: str) -> set[str]:
    values: set[str] = set()
    for part in PurePosixPath(path).parts:
        stem = part.rsplit(".", 1)[0].lower()
        values.add(stem)
        values.update(token for token in stem.replace("-", "_").split("_") if token)
    return values


def infer_role(path: str) -> tuple[str, str, list[str]]:
    tokens = tokens_for(path)
    for keywords, role, description in ROLE_RULES:
        overlap = sorted(tokens & keywords)
        if overlap:
            return role, description, [f"path keyword: {', '.join(overlap)}"]
    return "module", "一般功能模組；需要進一步語義分析確認職責", ["no strong path keyword evidence"]


def infer_stability(
    path: str,
    incoming: int,
    outgoing: int,
    max_incoming: int,
    history: dict[str, object] | None = None,
) -> tuple[str, list[str]]:
    tokens = tokens_for(path)
    reasons: list[str] = []
    history = history or {}
    change_frequency = float(history.get("change_frequency", 0.0) or 0.0)
    normalized_churn = float(history.get("normalized_churn", 0.0) or 0.0)
    age_days = history.get("age_days")

    if tokens & {"experimental", "experiment", "labs", "lab", "prototype", "alpha", "beta", "playground", "sandbox"}:
        return "experimental", ["experimental path keyword"]
    if tokens & {"plugin", "plugins", "extension", "extensions", "contrib", "examples", "demo", "integration", "integrations"}:
        return "evolving", ["optional/extension path keyword"]
    if change_frequency >= 0.55 or normalized_churn >= 0.80:
        return "evolving", [
            f"high Git change frequency: {change_frequency:.3f}",
            f"high normalized churn: {normalized_churn:.3f}",
        ]
    if tokens & {"core", "kernel", "runtime", "engine", "domain"}:
        reasons.append("core path keyword")
        return "core", reasons
    if max_incoming > 0 and incoming >= max(2, round(max_incoming * 0.6)):
        reasons.append(f"high incoming dependency count: {incoming}")
        return "core", reasons
    if incoming + outgoing >= 4:
        reasons.append(f"structurally connected: in={incoming}, out={outgoing}")
    if isinstance(age_days, int):
        reasons.append(f"days since last Git change: {age_days}")
    if change_frequency:
        reasons.append(f"Git change frequency: {change_frequency:.3f}")
    if reasons:
        return "stable", reasons
    return "stable", ["default stable classification; no experimental evidence"]


def infer_architecture_pattern(paths: list[str], config_files: list[str]) -> dict[str, object]:
    token_counter: Counter[str] = Counter()
    for path in paths:
        token_counter.update(tokens_for(path))
    evidence: list[str] = []

    if all(token_counter[token] for token in ("domain", "adapter")) or token_counter["ports"]:
        evidence.append("domain + adapter/ports directories")
        return {"primary": "hexagonal/clean architecture candidate", "confidence": 0.82, "evidence": evidence}
    if token_counter["controllers"] and token_counter["models"] and token_counter["views"]:
        evidence.append("controllers + models + views")
        return {"primary": "MVC candidate", "confidence": 0.86, "evidence": evidence}
    if token_counter["services"] and (token_counter["controllers"] or token_counter["api"]) and token_counter["models"]:
        evidence.append("interface + services + models layering")
        return {"primary": "layered architecture candidate", "confidence": 0.78, "evidence": evidence}
    manifests = [f for f in config_files if f.endswith(("package.json", "pyproject.toml", "Cargo.toml", "go.mod"))]
    if len(manifests) >= 3 and (token_counter["packages"] or token_counter["services"] or token_counter["crates"]):
        evidence.append(f"multiple manifests: {len(manifests)}")
        return {"primary": "monorepo/workspace candidate", "confidence": 0.76, "evidence": evidence}
    if token_counter["plugins"] or token_counter["extensions"]:
        evidence.append("plugin/extension directories")
        return {"primary": "plugin-oriented modular architecture candidate", "confidence": 0.72, "evidence": evidence}
    if token_counter["src"] and token_counter["tests"]:
        evidence.append("separated source and test roots")
        return {"primary": "modular package/library candidate", "confidence": 0.62, "evidence": evidence}
    return {"primary": "unclassified modular repository", "confidence": 0.35, "evidence": ["insufficient structural evidence"]}
