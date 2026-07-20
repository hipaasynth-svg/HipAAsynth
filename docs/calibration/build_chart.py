# HipAAsynth — Synthetic health data fairness testing for invisible populations.
# Copyright (C) 2026 HipAAsynth Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""
HipAAsynth — Calibration vs Data Chart Builder
==============================================
Reads calibration_report.json and emits a self-contained, theme-aware HTML page
(``calibration_vs_data.html``) with a side-by-side Target (real-world anchor) vs
Actual (synthetic cohort) view for every calibration metric, faceted by module.

Usage:
    python3 docs/calibration/build_chart.py
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT = os.path.join(HERE, "calibration_report.json")
OUT = os.path.join(HERE, "calibration_vs_data.html")


def clean_label(metric):
    """Strip the trailing parenthetical target note from a metric label."""
    idx = metric.find("(")
    return metric[:idx].strip() if idx != -1 else metric.strip()


def build():
    with open(REPORT, encoding="utf-8") as fh:
        report = json.load(fh)

    modules = []
    for name, md in report["modules"].items():
        checks = []
        for c in md["checks"]:
            target = c["target"]
            actual = c["actual"]
            tol = c["tolerance"]
            is_prop = target <= 1.0 and tol <= 1.0
            checks.append({
                "label": clean_label(c["metric"]),
                "target": target,
                "actual": actual,
                "tol": tol,
                "diff": c["diff"],
                "status": c["status"],
                "is_prop": is_prop,
                # fraction of the allowed tolerance budget that the deviation consumes
                "budget": round(c["diff"] / tol, 4) if tol else 0.0,
            })
        modules.append({
            "name": name.upper(),
            "pass": md["pass"],
            "fail": md["fail"],
            "checks": checks,
        })

    payload = {
        "generated_utc": report["generated_utc"],
        "engine_version": report["engine_version"],
        "tolerance_default": report["tolerance_default"],
        "summary": report["summary"],
        "modules": modules,
    }

    fragment = TEMPLATE.replace("__DATA__", json.dumps(payload))
    standalone = (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "</head>\n<body>\n" + fragment + "\n</body>\n</html>\n"
    )
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(standalone)
    print(f"Wrote {OUT}")


TEMPLATE = r"""<title>HipAAsynth — Calibration vs Real-World Anchors</title>
<style>
  .viz-root{
    color-scheme:light;
    --surface-1:#fcfcfb; --plane:#f9f9f7;
    --text-primary:#0b0b0b; --text-secondary:#52514e; --muted:#898781;
    --grid:#e1e0d9; --baseline:#c3c2b7; --border:rgba(11,11,11,0.10);
    --target:#898781;        /* real-world anchor — neutral reference */
    --actual:#2a78d6;        /* synthetic cohort — blue slot 1 */
    --good:#0ca30c; --band:rgba(12,163,12,0.10);
    font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
    color:var(--text-primary); background:var(--plane);
  }
  @media (prefers-color-scheme:dark){
    :root:where(:not([data-theme="light"])) .viz-root{
      color-scheme:dark;
      --surface-1:#1a1a19; --plane:#0d0d0d;
      --text-primary:#fff; --text-secondary:#c3c2b7; --muted:#898781;
      --grid:#2c2c2a; --baseline:#383835; --border:rgba(255,255,255,0.10);
      --target:#898781; --actual:#3987e5; --good:#0ca30c; --band:rgba(12,163,12,0.14);
    }
  }
  :root[data-theme="dark"] .viz-root{
    color-scheme:dark;
    --surface-1:#1a1a19; --plane:#0d0d0d;
    --text-primary:#fff; --text-secondary:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --baseline:#383835; --border:rgba(255,255,255,0.10);
    --target:#898781; --actual:#3987e5; --good:#0ca30c; --band:rgba(12,163,12,0.14);
  }
  .viz-root{max-width:1000px;margin:0 auto;padding:32px 20px 64px;}
  .viz-root h1{font-size:1.55rem;line-height:1.2;margin:0 0 6px;}
  .viz-root .sub{color:var(--text-secondary);font-size:0.95rem;margin:0 0 20px;}
  .kpis{display:flex;flex-wrap:wrap;gap:12px;margin:0 0 24px;}
  .kpi{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;
       padding:12px 16px;min-width:120px;}
  .kpi .v{font-size:1.7rem;font-weight:650;}
  .kpi .l{font-size:0.78rem;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;}
  .legend{display:flex;gap:18px;align-items:center;margin:0 0 18px;font-size:0.85rem;
          color:var(--text-secondary);flex-wrap:wrap;}
  .legend .sw{display:inline-block;width:22px;height:10px;border-radius:3px;margin-right:6px;
              vertical-align:middle;}
  .legend .band-sw{background:var(--band);border:1px solid var(--good);}
  .facet{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;
         padding:18px 18px 8px;margin:0 0 20px;overflow-x:auto;}
  .facet h2{font-size:1.05rem;margin:0 0 2px;}
  .facet .fmeta{font-size:0.82rem;color:var(--muted);margin:0 0 14px;}
  .row{display:grid;grid-template-columns:230px 1fr;gap:14px;align-items:center;
       padding:7px 0;border-top:1px solid var(--grid);}
  .row:first-of-type{border-top:none;}
  .rlabel{font-size:0.82rem;color:var(--text-secondary);line-height:1.25;}
  .rlabel .unit{color:var(--muted);font-size:0.74rem;}
  .track{position:relative;}
  .bars{position:relative;}
  .bar{height:11px;border-radius:0 4px 4px 0;position:relative;}
  .bar.target{background:var(--target);margin-bottom:4px;}
  .bar.actual{background:var(--actual);}
  .bwrap{position:relative;display:flex;align-items:center;gap:8px;}
  .bval{font-size:0.74rem;color:var(--text-secondary);font-variant-numeric:tabular-nums;
        white-space:nowrap;}
  .tolband{position:absolute;top:-3px;bottom:-3px;background:var(--band);
           border-left:1px dashed var(--good);border-right:1px dashed var(--good);
           border-radius:2px;pointer-events:none;}
  .tmark{position:absolute;top:-5px;bottom:-5px;width:2px;background:var(--text-primary);
         opacity:.55;pointer-events:none;}
  .status{font-size:0.72rem;color:var(--good);font-weight:600;white-space:nowrap;}
  table.data{border-collapse:collapse;width:100%;font-size:0.8rem;margin-top:6px;}
  table.data th,table.data td{text-align:right;padding:5px 8px;border-bottom:1px solid var(--grid);
       font-variant-numeric:tabular-nums;}
  table.data th:first-child,table.data td:first-child{text-align:left;}
  table.data th{color:var(--muted);font-weight:600;text-transform:uppercase;font-size:0.68rem;
       letter-spacing:.04em;}
  .toggle{background:none;border:1px solid var(--border);color:var(--text-secondary);
       border-radius:7px;padding:5px 11px;font-size:0.8rem;cursor:pointer;margin-bottom:12px;}
  .note{font-size:0.8rem;color:var(--muted);margin:18px 0 0;line-height:1.5;}
  .hidden{display:none;}
</style>

<div class="viz-root">
  <h1>Calibration vs Real-World Anchors</h1>
  <p class="sub" id="sub"></p>

  <div class="kpis" id="kpis"></div>

  <div class="legend">
    <span><span class="sw" style="background:var(--target)"></span>Target (published real-world anchor)</span>
    <span><span class="sw" style="background:var(--actual)"></span>Actual (synthetic cohort, n=1000)</span>
    <span><span class="sw band-sw"></span>Acceptance tolerance band</span>
  </div>

  <button class="toggle" id="toggle">Show data table</button>

  <div id="charts"></div>
  <div id="tables" class="hidden"></div>

  <p class="note" id="note"></p>
</div>

<script>
const DATA = __DATA__;

function fmt(v, isProp){
  if(isProp) return (v*100).toFixed(1) + '%';
  return v.toFixed(v >= 100 ? 0 : 1);
}

// KPIs
const s = DATA.summary;
document.getElementById('sub').textContent =
  'Every HipAAsynth statistical anchor, synthetic cohort value beside the published target it was calibrated to. '
  + 'Engine ' + DATA.engine_version + ' · generated ' + DATA.generated_utc.slice(0,10) + ' (UTC).';
const kpis = [
  ['Checks passed', s.total_pass + ' / ' + (s.total_pass + s.total_fail)],
  ['Modules', DATA.modules.length],
  ['Cohort size', '1,000 / module'],
  ['Pass rate', Math.round(100*s.total_pass/(s.total_pass+s.total_fail)) + '%'],
];
document.getElementById('kpis').innerHTML = kpis.map(k =>
  '<div class="kpi"><div class="v">'+k[1]+'</div><div class="l">'+k[0]+'</div></div>').join('');

// Charts — per module, one row per metric with side-by-side target/actual bars.
// Proportion metrics share a 0..maxProp axis; continuous metrics are drawn on a
// per-metric axis scaled to max(target,actual)*1.15 so both bars stay comparable.
const chartsEl = document.getElementById('charts');
const tablesEl = document.getElementById('tables');

DATA.modules.forEach(mod => {
  const propMax = Math.max(0.01, ...mod.checks.filter(c=>c.is_prop).map(c=>Math.max(c.target,c.actual)));
  const axisMax = Math.min(1.0, propMax*1.15);

  const facet = document.createElement('div');
  facet.className = 'facet';
  facet.innerHTML = '<h2>'+mod.name+'</h2><div class="fmeta">'+mod.pass+' pass / '+mod.fail+' fail · '
                    + mod.checks.length + ' calibration checks</div>';

  mod.checks.forEach(c => {
    const scaleMax = c.is_prop ? axisMax : Math.max(c.target, c.actual)*1.15;
    const pct = v => Math.max(0, Math.min(100, 100*v/scaleMax));
    const tTarget = pct(c.target), tActual = pct(c.actual);
    const tolLo = pct(Math.max(0, c.target - c.tol));
    const tolHi = pct(c.target + c.tol);
    const unit = c.is_prop ? 'proportion' : 'value';

    const row = document.createElement('div');
    row.className = 'row';
    row.innerHTML =
      '<div class="rlabel">'+c.label+'<br><span class="unit">'+unit+'</span></div>'
      + '<div class="track">'
      +   '<div class="bars">'
      +     '<div class="tolband" style="left:'+tolLo+'%;width:'+(tolHi-tolLo)+'%"></div>'
      +     '<div class="tmark" style="left:'+tTarget+'%"></div>'
      +     '<div class="bwrap"><div class="bar target" style="width:'+tTarget+'%"></div>'
      +        '<span class="bval">'+fmt(c.target,c.is_prop)+' target</span></div>'
      +     '<div class="bwrap"><div class="bar actual" style="width:'+tActual+'%"></div>'
      +        '<span class="bval">'+fmt(c.actual,c.is_prop)+' actual</span>'
      +        '<span class="status">✓ '+c.status+'</span></div>'
      +   '</div>'
      + '</div>';
    facet.appendChild(row);
  });
  chartsEl.appendChild(facet);

  // table
  const tbl = document.createElement('div');
  tbl.className = 'facet';
  let rows = mod.checks.map(c =>
    '<tr><td>'+c.label+'</td><td>'+fmt(c.target,c.is_prop)+'</td><td>'+fmt(c.actual,c.is_prop)
    +'</td><td>'+fmt(c.tol,c.is_prop)+'</td><td>'+(c.budget*100).toFixed(0)+'%</td><td style="color:var(--good)">✓ '+c.status+'</td></tr>'
  ).join('');
  tbl.innerHTML = '<h2>'+mod.name+'</h2><table class="data"><thead><tr>'
    + '<th>Metric</th><th>Target</th><th>Actual</th><th>Tolerance</th><th>Tol used</th><th>Status</th>'
    + '</tr></thead><tbody>'+rows+'</tbody></table>';
  tablesEl.appendChild(tbl);
});

document.getElementById('note').textContent =
  'Bars share a per-metric axis; the dashed green region is the acceptance tolerance band around the target, '
  + 'the vertical tick marks the target. "Tol used" is the share of the allowed tolerance the synthetic value consumes '
  + '(lower is tighter; 100% would be the pass/fail boundary). Continuous metrics (age, BNP, EF, sodium, SpO2, FEV1%) '
  + 'are shown on their own value scale; all others are proportions.';

const toggle = document.getElementById('toggle');
toggle.addEventListener('click', () => {
  const showTable = tablesEl.classList.contains('hidden');
  tablesEl.classList.toggle('hidden');
  chartsEl.classList.toggle('hidden');
  toggle.textContent = showTable ? 'Show chart' : 'Show data table';
});
</script>
"""


if __name__ == "__main__":
    build()
