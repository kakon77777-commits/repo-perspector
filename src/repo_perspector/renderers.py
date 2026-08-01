from __future__ import annotations

import html
import json
from pathlib import Path

from .indexer import build_query_index
from .models import ArchitectureReport
from .sarif import render_sarif


def _safe_id(value: str) -> str:
    return "n_" + "".join(character if character.isalnum() else "_" for character in value)


def render_mermaid(report: ArchitectureReport, max_nodes: int = 100) -> str:
    components = report.components[:max_nodes]
    included = {component.path for component in components}
    lines = ["flowchart LR"]
    for component in components:
        label = component.path.replace('"', "'")
        hotspot = float(component.metrics.get("hotspot_score", 0.0))
        lines.append(f'  {_safe_id(component.path)}["{label}<br/>{component.role} · {component.stability}<br/>risk {component.impact.get("risk_tier", "?")} · hotspot {hotspot:.2f}"]')
    for dependency in report.dependencies:
        if dependency.source in included and dependency.target in included:
            lines.append(f"  {_safe_id(dependency.source)} -->|{dependency.count}| {_safe_id(dependency.target)}")
    lines.extend([
        "  classDef core fill:#ffddd8,stroke:#b42318,stroke-width:2px,color:#3d0d08;",
        "  classDef stable fill:#fff0bf,stroke:#b58105,stroke-width:1.5px,color:#3d2c00;",
        "  classDef evolving fill:#d8f3dc,stroke:#2d6a4f,stroke-width:1.5px,color:#123524;",
        "  classDef experimental fill:#dbeafe,stroke:#2563eb,stroke-width:1.5px,color:#102a56;",
    ])
    for component in components:
        lines.append(f"  class {_safe_id(component.path)} {component.stability};")
    if len(report.components) > max_nodes:
        lines.append(f"  %% Truncated to {max_nodes} of {len(report.components)} components")
    return "\n".join(lines) + "\n"


def render_summary(report: ArchitectureReport) -> str:
    project = report.project
    pattern = report.architecture["pattern"]
    finding_counts = report.quality.get("finding_summary", {})
    lines = [
        f"# {project['name']} 架構透視摘要",
        "",
        f"- 檔案：{project['file_count']}",
        f"- 模組：{project['component_count']}",
        f"- 工作區：{project.get('workspace_count', 1)}（monorepo：{project.get('monorepo', False)}）",
        f"- 內部依賴：{project['dependency_count']}",
        f"- 符號：{project.get('symbol_count', 0)}",
        f"- 符號呼叫關係：{project.get('symbol_relationship_count', 0)}",
        f"- 候選架構：{pattern['primary']}",
        f"- 架構信心：{pattern['confidence']}",
        f"- 循環依賴群：{len(report.cycles)}",
        f"- Git 分析提交：{report.history.get('repository', {}).get('commit_count_analyzed', 0)}",
        f"- 增量快取：{report.analysis.get('cache', {}).get('hits', 0)} hit / {report.analysis.get('cache', {}).get('misses', 0)} miss（{float(report.analysis.get('cache', {}).get('hit_rate', 0.0)):.1%}）",
        f"- 分析耗時：{float(report.analysis.get('timing_seconds', {}).get('total', 0.0)):.4f} 秒",
        f"- 解析工作執行緒：{report.analysis.get('concurrency', {}).get('workers', 1)}",
        f"- 報告是否部分完成：{report.analysis.get('partial', False)}",
        f"- 發現：error {finding_counts.get('error', 0)} / warning {finding_counts.get('warning', 0)} / note {finding_counts.get('note', 0)}",
        f"- 架構健康：{float((report.quality.get('health') or {}).get('score', 0.0)):.2f}（{(report.quality.get('health') or {}).get('grade', '?')} / {(report.quality.get('health') or {}).get('status', 'unknown')}）",
        "",
        "## 最高風險與演化熱點",
        "",
        "| 模組 | 職責 | 穩定性 | 風險 | 熱點 | 複雜度 | 符號 | churn | 爆炸半徑 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for component in report.components[:15]:
        lines.append(
            f"| `{component.path}` | {component.description} | {component.stability} | "
            f"{component.impact.get('risk_tier', 'unknown')} ({float(component.impact.get('risk_score', 0.0)):.3f}) | "
            f"{float(component.metrics.get('hotspot_score', 0.0)):.3f} | {component.metrics.get('complexity', 0)} | "
            f"{component.metrics.get('symbol_count', 0)} | {component.history.get('churn', 0)} | "
            f"{float(component.impact.get('blast_radius', 0.0)):.3f} |"
        )
    if report.history.get("cochange"):
        lines.extend(["", "## 最高共同變更耦合", "", "| 模組 A | 模組 B | 共同提交 | 信心 | Jaccard |", "|---|---|---:|---:|---:|"])
        for pair in report.history["cochange"][:12]:
            lines.append(f"| `{pair['left']}` | `{pair['right']}` | {pair['joint_commits']} | {pair['confidence']:.3f} | {pair['jaccard']:.3f} |")
    if report.workspaces:
        lines.extend(["", "## 工作區／套件邊界", "", "| 路徑 | 名稱 | 生態 | 檔案 | 模組 |", "|---|---|---|---:|---:|"])
        for workspace in report.workspaces[:30]:
            lines.append(f"| `{workspace.get('path')}` | {workspace.get('name')} | {workspace.get('ecosystem')} | {len(workspace.get('files', []))} | {len(workspace.get('components', []))} |")
    lines.extend(["", "## 架構判斷證據", ""])
    lines.extend(f"- {item}" for item in pattern.get("evidence", []))
    if report.policy.get("loaded"):
        lines.extend(["", "## 架構政策", "", f"- 來源：`{report.policy.get('source')}`", f"- 分層數：{report.policy.get('layer_count', 0)}", f"- 政策違規：{report.policy.get('finding_count', 0)}"])
    if report.warnings:
        lines.extend(["", "## 警告", ""])
        lines.extend(f"- {warning}" for warning in report.warnings)
    return "\n".join(lines) + "\n"


def render_findings(report: ArchitectureReport) -> str:
    lines = [f"# {report.project['name']} 架構發現", ""]
    if not report.findings:
        return "\n".join(lines + ["未發現架構規則問題。", ""])
    for finding in report.findings:
        location = f"`{finding.path}`" if finding.path else "無精確檔案位置"
        if finding.line:
            location += f":{finding.line}"
        lines.extend([
            f"## [{finding.severity.upper()}] {finding.title}",
            "",
            f"- 規則：`{finding.rule_id}`",
            f"- 模組：`{finding.component}`" if finding.component else "- 模組：未指定",
            f"- 位置：{location}",
            f"- 說明：{finding.message}",
        ])
        if finding.evidence:
            lines.append("- 證據：")
            lines.extend(f"  - `{evidence}`" for evidence in finding.evidence[:20])
        lines.append("")
    return "\n".join(lines)


MSSP_SETS = ("FMS", "SCL", "SMS", "TMS", "DMS")


def detect_declared_mssp(report: ArchitectureReport) -> dict[str, list]:
    """Group components by the MSSP set their own path declares.

    A project that puts modules under src/SMS/ and src/TMS/ has already stated
    where each capability belongs. Inferring that placement from centrality and
    churn — and then printing the answer under MSSP's own labels — overrides the
    author with a guess, and the guess is wrong in a predictable direction:
    a declared TMS with high centrality gets reported as SMS.

    Declaration wins where it exists. Inference is the fallback, and
    render_mssp() records which one produced the output.
    """
    grouped: dict[str, list] = {name: [] for name in MSSP_SETS}
    for component in report.components:
        segments = component.path.replace("\\", "/").split("/")
        for name in MSSP_SETS:
            if name in segments:
                grouped[name].append(component)
                break
    return grouped


def render_mssp(report: ArchitectureReport) -> str:
    project = report.project
    pattern = report.architecture["pattern"]

    declared = detect_declared_mssp(report)
    declared_sets = [name for name in MSSP_SETS if declared[name]]
    # Two or more declared sets is a structure; one could be coincidence — a
    # repository with an unrelated directory called "DMS", for instance.
    use_declared = len(declared_sets) >= 2

    if use_declared:
        core = declared["SMS"]
        optional = declared["TMS"]
        detection = "declared"
    else:
        core = [component for component in report.components if component.stability in {"core", "stable"}]
        optional = [component for component in report.components if component.stability in {"evolving", "experimental"}]
        detection = "inferred"

    def quote(value: object) -> str:
        return json.dumps(value, ensure_ascii=False)

    lines = [
        "# Generated by repo-perspector v0.6",
        "# Evidence-derived architecture intermediate representation.",
        "meta:",
        f"  name: {quote(project['name'])}",
        '  version: "0.6.0-derived"',
        f"  source: {quote(project.get('origin_url') or project.get('root'))}",
        f"  commit: {quote(project.get('commit'))}",
        "context:",
        f"  inferred_architecture: {quote(pattern['primary'])}",
        f"  confidence: {pattern['confidence']}",
        f"  symbols_indexed: {project.get('symbol_count', 0)}",
        f"  findings: {project.get('finding_count', 0)}",
        "mssp_detection:",
        f"  source: {quote(detection)}",
        f"  declared_sets: {quote(declared_sets)}",
        "  note: " + quote(
            "Set membership was read from the repository's own directory names."
            if use_declared
            else "No MSSP directories were found; membership below is inferred from stability and centrality, not declared by the project."
        ),
        "architecture:",
        f"  pattern: {quote(pattern['primary'])}",
    ]

    # The other three sets only appear when the project actually declares them.
    if use_declared:
        for name in ("FMS", "SCL", "DMS"):
            if not declared[name]:
                continue
            lines.append(f"  {name}:")
            for component in declared[name]:
                lines.extend([
                    f"    - module: {quote(component.path)}",
                    f"      role: {quote(component.role)}",
                    f"      stability: {quote(component.stability)}",
                    f"      centrality: {component.centrality}",
                    "      dependencies:",
                ])
                if component.internal_dependencies:
                    lines.extend(f"        - {quote(dep)}" for dep in component.internal_dependencies)
                else:
                    lines.append("        []")

    lines.append("  SMS:")
    if not core:
        lines.append("    []")
    for component in core:
        lines.extend([
            f"    - module: {quote(component.path)}",
            f"      role: {quote(component.role)}",
            f"      description: {quote(component.description)}",
            f"      stability: {quote(component.stability)}",
            f"      centrality: {component.centrality}",
            f"      instability: {component.metrics.get('instability', 0.0)}",
            f"      hotspot_score: {component.metrics.get('hotspot_score', 0.0)}",
            f"      risk_tier: {quote(component.impact.get('risk_tier', 'unknown'))}",
            "      dependencies:",
        ])
        lines.extend(f"        - {quote(dep)}" for dep in component.internal_dependencies) if component.internal_dependencies else lines.append("        []")
    lines.append("  TMS:")
    for component in optional:
        lines.extend([
            f"    - subset: {quote(component.path)}",
            f"      role: {quote(component.role)}",
            "      optional: true",
            f"      stability: {quote(component.stability)}",
            f"      hotspot_score: {component.metrics.get('hotspot_score', 0.0)}",
            "      dependencies:",
        ])
        lines.extend(f"        - {quote(dep)}" for dep in component.internal_dependencies) if component.internal_dependencies else lines.append("        []")
    if not optional:
        lines.append("    []")
    lines.extend([
        "evidence:",
        f"  generated_at: {quote(report.generated_at)}",
        f"  files_scanned: {project['file_count']}",
        f"  dependencies_resolved: {project['dependency_count']}",
        f"  symbols_indexed: {project.get('symbol_count', 0)}",
        f"  cycles_detected: {len(report.cycles)}",
        f"  git_commits_analyzed: {report.history.get('repository', {}).get('commit_count_analyzed', 0)}",
        f"  policy_loaded: {str(report.policy.get('loaded', False)).lower()}",
    ])
    return "\n".join(lines) + "\n"


def render_html(report: ArchitectureReport) -> str:
    payload = json.dumps(report.to_dict(), ensure_ascii=False).replace("</", "<\\/")
    title = html.escape(f"{report.project['name']} · Architecture Perspector")
    return f'''<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
:root{{--bg:#f4f6fa;--panel:#fff;--text:#172033;--muted:#667085;--line:#d7dce5;--accent:#5b4bc4;--error:#b42318;--warn:#b58105;--note:#2563eb}}
@media(prefers-color-scheme:dark){{:root{{--bg:#0f1117;--panel:#171a22;--text:#edf1f7;--muted:#a5adba;--line:#343b49;--accent:#c5b3ff}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 system-ui,-apple-system,"Noto Sans TC",sans-serif}}header{{padding:18px 22px;background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}}h1{{margin:0 0 4px;font-size:22px}}.muted{{color:var(--muted)}}.stats,.tabs,.toolbar{{display:flex;gap:8px;flex-wrap:wrap;align-items:center}}.stats{{margin-top:10px}}.pill,.tab{{border:1px solid var(--line);border-radius:999px;padding:5px 10px;background:var(--bg)}}.tab{{cursor:pointer}}.tab.active{{background:var(--accent);color:white}}main{{padding:14px}}.view{{display:none}}.view.active{{display:block}}.grid{{display:grid;grid-template-columns:minmax(0,1fr) 380px;gap:14px}}.panel{{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}}.toolbar{{padding:11px;border-bottom:1px solid var(--line)}}input,select,button{{color:var(--text);background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px 10px}}button{{cursor:pointer}}#graph{{height:68vh;min-height:520px;overflow:auto;background-image:radial-gradient(var(--line) .7px,transparent .7px);background-size:18px 18px}}svg{{width:1500px;height:1000px}}.edge{{stroke:var(--muted);stroke-opacity:.42;fill:none}}.node{{cursor:pointer}}.node rect{{rx:9;ry:9;stroke-width:1.5}}.node text{{font-size:11px;fill:#172033;pointer-events:none}}.node.dim,.edge.dim{{opacity:.1}}.node.selected rect{{stroke-width:4}}.core rect{{fill:#ffddd8;stroke:#b42318}}.stable rect{{fill:#fff0bf;stroke:#b58105}}.evolving rect{{fill:#d8f3dc;stroke:#2d6a4f}}.experimental rect{{fill:#dbeafe;stroke:#2563eb}}aside{{padding:14px;overflow:auto;max-height:75vh}}.cards{{display:grid;gap:9px}}.card{{border:1px solid var(--line);border-radius:10px;padding:10px}}.error{{border-left:4px solid var(--error)}}.warning{{border-left:4px solid var(--warn)}}.note{{border-left:4px solid var(--note)}}table{{width:100%;border-collapse:collapse;background:var(--panel);border-radius:12px;overflow:hidden}}th,td{{padding:8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}code{{word-break:break-all}}@media(max-width:900px){{.grid{{grid-template-columns:1fr}}aside{{max-height:none}}#graph{{height:55vh}}}}
</style></head><body>
<header><h1 id="title"></h1><div id="subtitle" class="muted"></div><div id="stats" class="stats"></div><div class="tabs" style="margin-top:12px"><button class="tab active" data-view="architecture">架構圖</button><button class="tab" data-view="findings">發現</button><button class="tab" data-view="hotspots">熱點</button><button class="tab" data-view="symbols">符號</button><button class="tab" data-view="cochange">共同變更</button></div></header>
<main>
<section id="architecture" class="view active"><div class="grid"><section class="panel"><div class="toolbar"><input id="search" placeholder="搜尋模組…"><select id="stability"><option value="all">全部穩定性</option><option>core</option><option>stable</option><option>evolving</option><option>experimental</option></select><button id="reset">重設</button></div><div id="graph"><svg id="svg" viewBox="0 0 1500 1000"></svg></div></section><section class="panel"><aside id="details"></aside></section></div></section>
<section id="findings" class="view"><div class="toolbar"><select id="findingSeverity"><option value="all">全部嚴重度</option><option>error</option><option>warning</option><option>note</option></select><input id="findingSearch" placeholder="搜尋規則或模組…"></div><div id="findingCards" class="cards" style="margin-top:12px"></div></section>
<section id="hotspots" class="view"><table><thead><tr><th>模組</th><th>熱點</th><th>風險</th><th>複雜度</th><th>churn</th><th>不穩定度</th></tr></thead><tbody id="hotspotRows"></tbody></table></section>
<section id="symbols" class="view"><div class="toolbar"><input id="symbolSearch" placeholder="搜尋符號、檔案或類型…"></div><table><thead><tr><th>符號</th><th>類型</th><th>檔案</th><th>行</th><th>複雜度</th></tr></thead><tbody id="symbolRows"></tbody></table></section>
<section id="cochange" class="view"><table><thead><tr><th>模組 A</th><th>模組 B</th><th>共同提交</th><th>信心</th><th>Jaccard</th></tr></thead><tbody id="cochangeRows"></tbody></table></section>
</main>
<script type="application/json" id="data">{payload}</script><script>
const R=JSON.parse(document.getElementById('data').textContent), C=R.components.slice(0,100), CM=new Map(C.map(c=>[c.path,c])), D=R.dependencies.filter(d=>CM.has(d.source)&&CM.has(d.target));
const esc=v=>String(v??'').replace(/[&<>"']/g,ch=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
document.getElementById('title').textContent=R.project.name;document.getElementById('subtitle').textContent=R.architecture.pattern.primary;
document.getElementById('stats').innerHTML=[`檔案 ${{R.project.file_count}}`,`模組 ${{R.project.component_count}}`,`依賴 ${{R.project.dependency_count}}`,`符號 ${{R.project.symbol_count||0}}`,`發現 ${{R.project.finding_count||0}}`,`健康 ${{R.quality?.health?.score||0}} (${{R.quality?.health?.grade||'?'}})`,`工作區 ${{R.project.workspace_count||1}}`,`Git ${{R.history?.repository?.commit_count_analyzed||0}} commits`,`快取 ${{Math.round((R.analysis?.cache?.hit_rate||0)*100)}}%`,`耗時 ${{R.analysis?.timing_seconds?.total||0}}s`].map(x=>`<span class="pill">${{x}}</span>`).join('');
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{{document.querySelectorAll('.tab,.view').forEach(e=>e.classList.remove('active'));b.classList.add('active');document.getElementById(b.dataset.view).classList.add('active')}});
const svg=document.getElementById('svg'),NS='http://www.w3.org/2000/svg',cols={{core:140,stable:500,evolving:860,experimental:1200}},groups={{core:[],stable:[],evolving:[],experimental:[]}},pos=new Map();C.forEach(c=>groups[c.stability].push(c));Object.entries(groups).forEach(([k,l])=>l.forEach((c,i)=>pos.set(c.path,{{x:cols[k],y:50+i*Math.max(62,880/Math.max(1,l.length))}})));const el=(n,a={{}})=>{{const e=document.createElementNS(NS,n);Object.entries(a).forEach(([k,v])=>e.setAttribute(k,v));return e}};const edges=el('g'),nodes=el('g');svg.append(edges,nodes);D.forEach(d=>{{const a=pos.get(d.source),b=pos.get(d.target);if(!a||!b)return;edges.append(el('path',{{d:`M ${{a.x+220}} ${{a.y+23}} C ${{(a.x+b.x)/2}} ${{a.y+23}},${{(a.x+b.x)/2}} ${{b.y+23}},${{b.x}} ${{b.y+23}}`,class:'edge','data-source':d.source,'data-target':d.target}}))}});C.forEach(c=>{{const p=pos.get(c.path),g=el('g',{{class:`node ${{c.stability}}`,transform:`translate(${{p.x}},${{p.y}})`,'data-path':c.path}});g.append(el('rect',{{width:220,height:48}}));const t=el('text',{{x:9,y:17}}),a=el('tspan',{{x:9}}),b=el('tspan',{{x:9,dy:17}});a.textContent=c.path.length>32?c.path.slice(0,31)+'…':c.path;b.textContent=`${{c.role}} · ${{c.impact?.risk_tier||'?'}} · H ${{c.metrics?.hotspot_score||0}}`;t.append(a,b);g.append(t);g.onclick=()=>select(c.path);nodes.append(g)}});
function select(path){{const c=CM.get(path);document.querySelectorAll('.node').forEach(n=>{{n.classList.toggle('selected',n.dataset.path===path);n.classList.toggle('dim',!(n.dataset.path===path||c.internal_dependencies.includes(n.dataset.path)||c.dependents.includes(n.dataset.path)))}});document.querySelectorAll('.edge').forEach(e=>e.classList.toggle('dim',e.dataset.source!==path&&e.dataset.target!==path));document.getElementById('details').innerHTML=`<h2>${{esc(c.path)}}</h2><p>${{esc(c.description)}}</p><p><b>角色：</b>${{esc(c.role)}}<br><b>穩定性：</b>${{esc(c.stability)}}<br><b>風險：</b>${{esc(c.impact?.risk_tier)}} (${{c.impact?.risk_score}})<br><b>熱點：</b>${{c.metrics?.hotspot_score}}<br><b>複雜度：</b>${{c.metrics?.complexity}}<br><b>符號：</b>${{c.metrics?.symbol_count}}<br><b>不穩定度：</b>${{c.metrics?.instability}}<br><b>churn：</b>${{c.history?.churn||0}}</p><h3>依賴</h3>${{c.internal_dependencies.map(x=>`<div class="card">→ ${{esc(x)}}</div>`).join('')||'<p class="muted">無</p>'}}<h3>被依賴</h3>${{c.dependents.map(x=>`<div class="card">← ${{esc(x)}}</div>`).join('')||'<p class="muted">無</p>'}}<h3>檔案</h3>${{c.files.slice(0,80).map(x=>`<div><code>${{esc(x)}}</code></div>`).join('')}}`;}}
function overview(){{document.getElementById('details').innerHTML=`<h2>架構摘要</h2><p><b>${{esc(R.architecture.pattern.primary)}}</b><br>信心：${{R.architecture.pattern.confidence}}<br>循環：${{R.cycles.length}}<br>政策：${{R.policy?.loaded?'已載入':'未載入'}}<br>工作區：${{R.project.workspace_count||1}}<br>部分報告：${{R.analysis?.partial||false}}<br>快取：${{R.analysis?.cache?.hits||0}} hit / ${{R.analysis?.cache?.misses||0}} miss<br>總耗時：${{R.analysis?.timing_seconds?.total||0}} 秒</p><h3>最高熱點</h3>${{(R.quality?.hotspots||[]).slice(0,10).map(x=>`<div class="card"><b>${{esc(x.component)}}</b><br>hotspot ${{x.hotspot_score}} · risk ${{esc(x.risk_tier)}}</div>`).join('')}}`;}}overview();
function filterGraph(){{const q=document.getElementById('search').value.toLowerCase(),s=document.getElementById('stability').value;document.querySelectorAll('.node').forEach(n=>{{const c=CM.get(n.dataset.path),hit=(!q||(c.path+' '+c.role+' '+c.description).toLowerCase().includes(q))&&(s==='all'||c.stability===s);n.classList.toggle('dim',!hit)}})}}document.getElementById('search').oninput=filterGraph;document.getElementById('stability').onchange=filterGraph;document.getElementById('reset').onclick=()=>{{document.getElementById('search').value='';document.getElementById('stability').value='all';document.querySelectorAll('.dim,.selected').forEach(e=>e.classList.remove('dim','selected'));overview()}};
function renderFindings(){{const s=document.getElementById('findingSeverity').value,q=document.getElementById('findingSearch').value.toLowerCase();document.getElementById('findingCards').innerHTML=(R.findings||[]).filter(f=>(s==='all'||f.severity===s)&&(!q||(f.rule_id+' '+f.title+' '+f.message+' '+(f.component||'')).toLowerCase().includes(q))).map(f=>`<div class="card ${{f.severity}}"><b>[${{esc(f.severity)}}] ${{esc(f.title)}}</b><div class="muted">${{esc(f.rule_id)}} · ${{esc(f.component||'')}}</div><p>${{esc(f.message)}}</p>${{f.path?`<code>${{esc(f.path)}}${{f.line?':'+f.line:''}}</code>`:''}}</div>`).join('')||'<p class="muted">沒有符合條件的發現。</p>'}}document.getElementById('findingSeverity').onchange=renderFindings;document.getElementById('findingSearch').oninput=renderFindings;renderFindings();
document.getElementById('hotspotRows').innerHTML=C.map(c=>`<tr><td><code>${{esc(c.path)}}</code></td><td>${{c.metrics?.hotspot_score||0}}</td><td>${{esc(c.impact?.risk_tier||'')}}</td><td>${{c.metrics?.complexity||0}}</td><td>${{c.history?.churn||0}}</td><td>${{c.metrics?.instability||0}}</td></tr>`).join('');
function renderSymbols(){{const q=document.getElementById('symbolSearch').value.toLowerCase();document.getElementById('symbolRows').innerHTML=(R.symbols||[]).filter(s=>!q||(s.qualified_name+' '+s.path+' '+s.kind).toLowerCase().includes(q)).slice(0,1000).map(s=>`<tr><td><code>${{esc(s.qualified_name)}}</code><br><span class="muted">${{esc(s.signature)}}</span></td><td>${{esc(s.kind)}}</td><td><code>${{esc(s.path)}}</code></td><td>${{s.line_start}}</td><td>${{s.complexity}}</td></tr>`).join('')}}document.getElementById('symbolSearch').oninput=renderSymbols;renderSymbols();
document.getElementById('cochangeRows').innerHTML=(R.history?.cochange||[]).map(p=>`<tr><td><code>${{esc(p.left)}}</code></td><td><code>${{esc(p.right)}}</code></td><td>${{p.joint_commits}}</td><td>${{p.confidence}}</td><td>${{p.jaccard}}</td></tr>`).join('');
</script></body></html>'''


def write_outputs(report: ArchitectureReport, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "json": output_dir / "architecture.json",
        "mermaid": output_dir / "architecture.mmd",
        "html": output_dir / "architecture.html",
        "mssp": output_dir / "mssp.config.yaml",
        "summary": output_dir / "summary.md",
        "findings": output_dir / "findings.md",
        "sarif": output_dir / "architecture.sarif",
        "symbols": output_dir / "symbols.json",
        "index": output_dir / "architecture.index.json",
    }
    outputs["json"].write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    outputs["mermaid"].write_text(render_mermaid(report), encoding="utf-8")
    outputs["html"].write_text(render_html(report), encoding="utf-8")
    outputs["mssp"].write_text(render_mssp(report), encoding="utf-8")
    outputs["summary"].write_text(render_summary(report), encoding="utf-8")
    outputs["findings"].write_text(render_findings(report), encoding="utf-8")
    outputs["sarif"].write_text(render_sarif(report), encoding="utf-8")
    outputs["symbols"].write_text(json.dumps({
        "schema_version": "repo-perspector.symbols/v0.6",
        "symbols": [vars(symbol) if hasattr(symbol, "__dict__") else {
            "id": symbol.id, "qualified_name": symbol.qualified_name, "name": symbol.name,
            "kind": symbol.kind, "path": symbol.path, "component": symbol.component,
            "language": symbol.language, "line_start": symbol.line_start, "line_end": symbol.line_end,
            "signature": symbol.signature, "visibility": symbol.visibility, "parent": symbol.parent,
            "complexity": symbol.complexity, "docstring": symbol.docstring,
        } for symbol in report.symbols],
        "relationships": [{
            "source": relationship.source, "target": relationship.target, "kind": relationship.kind,
            "evidence": relationship.evidence, "count": relationship.count,
        } for relationship in report.symbol_relationships],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs["index"].write_text(json.dumps(build_query_index(report), ensure_ascii=False, indent=2), encoding="utf-8")
    return outputs
