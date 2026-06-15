"""Observability -- compelling ground segment visualization, not another report.

This module is evolving toward the "real" dashboard per DASHBOARD_DESIGN.md:
mission-control HUD aesthetic, strong visual metaphors (Pass Array beams, Provider
Constellation, Rescue Vectors), minimal text, hover-rich telemetry, orb for overall
health. The prototype remains self-contained for offline/export use; the real
version can relax to richer web tech while providing an export path.

Core outputs remain useful for code:
  * `compute_metrics`
  * `prometheus_metrics`
  * `render_html` / `render_trend_html`  -- now starting to implement the compelling
    non-report design (artistic timeline, constellation providers, etc.)

The narration helpers (format_*_for_narration) enable LLM layers (Groq etc.) on top.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from html import escape
from typing import Any

from .domain import ContactWindow
from .providers import Booking
from .reconciler import Attempt, AttemptState, ReconcileReport
from .visibility import satellite_position, visibility_footprint


@dataclass(frozen=True)
class ProviderStats:
    provider: str
    attempts: int
    successes: int

    @property
    def success_rate(self) -> float:
        return self.successes / self.attempts if self.attempts else 1.0


@dataclass(frozen=True)
class Metrics:
    planned: int
    satisfied: int
    recovered: int
    unrecovered: int
    recoveries_booked: int
    achieved_yield: float
    slo_target: float
    error_budget: int
    slo_met: bool
    providers: list[ProviderStats] = field(default_factory=list)
    stations: list[str] = field(default_factory=list)


def compute_metrics(report: ReconcileReport) -> Metrics:
    by_provider: dict[str, list[int]] = {}  # provider -> [attempts, successes]
    for a in report.attempts:
        slot = by_provider.setdefault(a.provider, [0, 0])
        slot[0] += 1
        if a.state is AttemptState.SUCCEEDED:
            slot[1] += 1

    stations = _unique_stations(report.attempts)

    providers = [
        ProviderStats(name, counts[0], counts[1])
        for name, counts in sorted(by_provider.items())
    ]
    return Metrics(
        planned=report.planned,
        satisfied=report.satisfied,
        recovered=report.recovered_demands,
        unrecovered=report.unrecovered,
        recoveries_booked=report.recoveries_booked,
        achieved_yield=report.achieved_yield,
        slo_target=report.slo_target,
        error_budget=report.error_budget,
        slo_met=report.slo_met,
        providers=providers,
        stations=stations,
    )


def _unique_stations(attempts):
    """Stable unique station list in first-seen order (shared by metrics + svg)."""
    seen = []
    for a in attempts:
        if a.window.station not in seen:
            seen.append(a.window.station)
    return seen


def prometheus_metrics(report: ReconcileReport) -> str:
    """Prometheus exposition format -- scrape into Grafana, alert on the SLO."""
    m = compute_metrics(report)
    lines = [
        "# HELP orchestrator_downlink_yield Fraction of planned contacts satisfied.",
        "# TYPE orchestrator_downlink_yield gauge",
        f"orchestrator_downlink_yield {m.achieved_yield:.6f}",
        "# HELP orchestrator_slo_target Target downlink yield.",
        "# TYPE orchestrator_slo_target gauge",
        f"orchestrator_slo_target {m.slo_target:.6f}",
        "# HELP orchestrator_slo_met 1 if the yield SLO held, else 0.",
        "# TYPE orchestrator_slo_met gauge",
        f"orchestrator_slo_met {1 if m.slo_met else 0}",
        "# HELP orchestrator_contacts_unrecovered Planned contacts never satisfied.",
        "# TYPE orchestrator_contacts_unrecovered gauge",
        f"orchestrator_contacts_unrecovered {m.unrecovered}",
        "# HELP orchestrator_error_budget Unrecovered contacts the SLO tolerates.",
        "# TYPE orchestrator_error_budget gauge",
        f"orchestrator_error_budget {m.error_budget}",
        "# HELP orchestrator_recoveries_booked Recovery contacts the loop booked.",
        "# TYPE orchestrator_recoveries_booked counter",
        f"orchestrator_recoveries_booked {m.recoveries_booked}",
        "# HELP orchestrator_provider_success_rate Per-provider contact success rate.",
        "# TYPE orchestrator_provider_success_rate gauge",
    ]
    for p in m.providers:
        lines.append(
            f'orchestrator_provider_success_rate{{provider="{p.provider}"}} {p.success_rate:.6f}'
        )
    return "\n".join(lines) + "\n"


# --- Report persistence (makes the dashboard useful beyond one-off demos) ---

def _serialize_value(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: _serialize_value(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize_value(v) for v in obj]
    return obj


def _deserialize_value(obj: Any, cls: type | None = None) -> Any:
    if isinstance(obj, dict):
        if "aos" in obj and "los" in obj:  # ContactWindow
            return ContactWindow(
                satellite=obj["satellite"],
                station=obj["station"],
                aos=datetime.fromisoformat(obj["aos"]),
                tca=datetime.fromisoformat(obj["tca"]),
                los=datetime.fromisoformat(obj["los"]),
                peak_elevation_deg=float(obj["peak_elevation_deg"]),
                aos_azimuth_deg=float(obj["aos_azimuth_deg"]),
                los_azimuth_deg=float(obj["los_azimuth_deg"]),
                duration_s=float(obj["duration_s"]),
            )
        if "id" in obj and "provider" in obj and "window" in obj:  # Booking
            return Booking(
                id=str(obj["id"]),
                provider=str(obj["provider"]),
                window=_deserialize_value(obj["window"]),
            )
        if "origin_id" in obj and "window" in obj:  # Attempt
            return Attempt(
                origin_id=int(obj["origin_id"]),
                attempt=int(obj["attempt"]),
                window=_deserialize_value(obj["window"]),
                provider=str(obj["provider"]),
                booking=_deserialize_value(obj.get("booking")) or Booking("unknown", "unknown", _deserialize_value(obj["window"])),
                state=AttemptState(obj.get("state", "failed")),
                detail=str(obj.get("detail", "")),
                recovers=_deserialize_value(obj.get("recovers")) if obj.get("recovers") else None,
            )
        if "attempts" in obj and "planned" in obj:  # ReconcileReport
            attempts = [_deserialize_value(a) for a in obj.get("attempts", [])]
            return ReconcileReport(
                attempts=attempts,
                planned=int(obj["planned"]),
                satisfied=int(obj["satisfied"]),
                slo_target=float(obj["slo_target"]),
            )
        return {k: _deserialize_value(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deserialize_value(v) for v in obj]
    return obj


def save_report(report: ReconcileReport, path: str) -> None:
    """Persist a ReconcileReport to JSON so it can be reloaded later for trends or audits."""
    data = asdict(report)
    data = _serialize_value(data)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_report(path: str) -> ReconcileReport:
    """Load a previously saved ReconcileReport."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return _deserialize_value(data, ReconcileReport)


def cleanup_old_reports(reports_dir: str | Path, keep_last: int = 50) -> int:
    """Delete the oldest report files in `reports_dir`, keeping only the `keep_last` most recent.

    Returns the number of files deleted. Call this after save_report in a monitor loop.
    """
    from pathlib import Path as _Path
    p = _Path(reports_dir)
    if not p.exists():
        return 0
    files = sorted(p.glob("run_*.json"))
    to_delete = files[:-keep_last] if len(files) > keep_last else []
    for f in to_delete:
        try:
            f.unlink()
        except OSError:
            pass
    return len(to_delete)


# --- HTML dashboard -------------------------------------------------------

_CSS = """
:root{
  --ink:#05070F; --bg:#020408; --panel:#0B0F1C; --panel2:#111827; --panel3:#080B14; --line:#1F2937;
  --text:#F0F4FF; --muted:#64748B; --zenith:#67F6FF; --horizon:#FFAA33; --accent:#6366F1;
  --ok:#22C55E; --fail:#EF4444; --recover:#818CF8;
  --mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);
  -webkit-font-smoothing:antialiased;padding:24px 20px 40px;min-height:100vh;
  background-image: 
    radial-gradient(circle at 20% 30%, rgba(103,246,255,0.03) 0%, transparent 50%),
    radial-gradient(circle at 80% 70%, rgba(255,170,51,0.025) 0%, transparent 60%);
  background-size: 100% 100%;
}
.wrap{max-width:1200px;margin:0 auto}
.eyebrow{font-family:var(--mono);font-size:9px;letter-spacing:.4em;text-transform:uppercase;
  color:var(--muted);margin:0 0 4px;opacity:0.6}
h1{font-size:28px;font-weight:800;letter-spacing:-.04em;margin:0 0 4px;
  background:linear-gradient(90deg,#fff,#A5B4FC 30%,#67F6FF); -webkit-background-clip:text; -webkit-text-fill-color:transparent;
  text-shadow:0 0 40px rgba(103,246,255,0.15);}
.sub{color:var(--muted);font-size:12px;margin:0 0 20px;opacity:0.7;letter-spacing:0.5px}
.cards{display:grid;grid-template-columns:1.6fr 1fr 1fr;gap:12px;margin-bottom:18px}
.card{
  background:linear-gradient(160deg,var(--panel),var(--panel3));
  border:1px solid var(--line);
  border-radius:10px;padding:14px 16px 12px;
  box-shadow: 0 4px 6px -1px rgba(0,0,0,0.4), 0 2px 4px -2px rgba(0,0,0,0.3),
              inset 0 0 0 1px rgba(255,255,255,0.03), inset 0 1px 0 rgba(255,255,255,0.04);
  position:relative;
}
.card::after{content:'';position:absolute;inset:0;border-radius:10px;background:linear-gradient(to bottom,rgba(255,255,255,0.025),transparent 40%);pointer-events:none}
.yield{font-family:var(--mono);font-size:52px;font-weight:800;line-height:0.9;margin:2px 0 0;letter-spacing:-.04em}
.verdict{display:inline-flex;align-items:center;font-family:var(--mono);font-size:9px;letter-spacing:.2em;
  padding:2px 8px;border-radius:999px;margin-top:4px;font-weight:700;border:1px solid currentColor}
.verdict.met{color:var(--ok);background:rgba(34,197,94,.08)}
.verdict.breached{color:var(--fail);background:rgba(239,68,68,.08)}
.big{font-family:var(--mono);font-size:28px;font-weight:800;margin:2px 0 0;letter-spacing:-.02em}
.budget-track{height:6px;border-radius:999px;background:var(--panel2);overflow:hidden;margin:10px 0 4px;position:relative}
.budget-fill{height:100%;border-radius:999px;box-shadow:0 0 12px currentColor}
.note{font-size:11px;color:var(--muted);margin-top:6px;opacity:0.6}
.section-label{font-family:var(--mono);font-size:9px;letter-spacing:.3em;text-transform:uppercase;
  color:var(--muted);margin:0 0 6px;opacity:0.6}
.panel{background:linear-gradient(145deg,var(--panel),var(--panel3));border:1px solid var(--line);border-radius:10px;padding:14px;
  box-shadow:0 2px 8px -2px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.025)}
.timeline{margin-bottom:16px}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:10px;color:var(--muted);margin-top:8px;opacity:0.7}
.legend span{display:inline-flex;align-items:center;gap:5px}
.dot{width:7px;height:7px;border-radius:1px;display:inline-block}
.prov{display:grid;grid-template-columns:140px 1fr 90px;align-items:center;gap:8px;margin:4px 0}
.prov .pname{font-family:var(--mono);font-size:10px;color:var(--text);font-weight:600;letter-spacing:0.3px}
.bar{height:7px;border-radius:999px;background:var(--panel2);overflow:hidden;box-shadow:inset 0 1px 2px rgba(0,0,0,0.6)}
.bar > i{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,var(--horizon),var(--zenith));box-shadow:0 0 4px rgba(255,170,51,0.4)}
.prate{font-family:var(--mono);font-size:10px;text-align:right;color:var(--muted);font-weight:600}
.details{width:100%;border-collapse:collapse;font-size:10px;margin:0}
.details th,.details td{padding:3px 6px;text-align:left;border-bottom:1px solid #1F2937;font-family:var(--mono)}
.details th{color:var(--muted);font-size:8px;letter-spacing:.15em;text-transform:uppercase;font-weight:500}
.details tr:last-child td{border-bottom:none}
.details .ok{color:var(--ok);font-weight:600}
.details .fail{color:var(--fail);font-weight:600}
@media(max-width:680px){.cards{grid-template-columns:1fr}}
"""


def _budget_color(consumed: int, budget: int) -> str:
    if consumed == 0:
        return "var(--ok)"
    if consumed <= budget:
        return "var(--horizon)"
    return "var(--fail)"


def _details_rows(report: ReconcileReport) -> str:
    """Compact table rows for the details section."""
    rows = []
    for a in report.timeline():
        state_cls = "ok" if a.state is AttemptState.SUCCEEDED else "fail"
        dur = f"{a.window.duration_s/60:.1f}m"
        peak = f"{a.window.peak_elevation_deg:.0f}°"
        rows.append(
            f"<tr>"
            f"<td>{a.window.aos:%H:%M}</td>"
            f"<td>{escape(a.window.station)}</td>"
            f"<td>{escape(a.window.satellite)}</td>"
            f"<td>{peak}</td>"
            f"<td>{dur}</td>"
            f"<td>{escape(a.provider)}</td>"
            f"<td class=\"{state_cls}\">{a.state.value}</td>"
            f"</tr>"
        )
    return "".join(rows)


def _events_log(report: ReconcileReport) -> str:
    """Compact visual events / rescue log (less report-like than full table)."""
    events = []
    for a in report.timeline()[:6]:  # limit for scannability
        icon = "🟢" if a.state is AttemptState.SUCCEEDED else "🔴"
        if a.attempt > 0:
            icon = "🔵"  # recovery
        time_str = a.window.aos.strftime("%H:%M")
        ev = f"{icon} {time_str} {a.window.satellite}@{a.window.station} via {a.provider} [{a.state.value}]"
        if a.recovers:
            ev += f" (rescued from {a.recovers.station})"
        events.append(ev)
    if len(report.timeline()) > 6:
        events.append(f"... +{len(report.timeline())-6} more")
    return "<br>".join(events)


def _timeline_svg(report: ReconcileReport) -> str:
    attempts = report.timeline()
    if not attempts:
        return "<p class='note'>No contacts in this run.</p>"

    stations = _unique_stations(attempts)

    gutter, right, lane_h, top = 150, 980, 40, 16
    height = top + lane_h * len(stations) + 34
    t0 = min(a.window.aos for a in attempts)
    t1 = max(a.window.los for a in attempts)
    span = (t1 - t0).total_seconds() or 1.0

    def x(t: datetime) -> float:
        return gutter + (t - t0).total_seconds() / span * (right - gutter)

    def lane_y(station: str) -> float:
        return top + stations.index(station) * lane_h + lane_h / 2

    parts = [f'<svg viewBox="0 0 1000 {height}" width="100%" '
             f'xmlns="http://www.w3.org/2000/svg" font-family="var(--mono)">']

    # defs for depth: shadows + per-bar elevation gradients
    parts.append('<defs>')
    parts.append('<filter id="barShadow" x="-50%" y="-50%" width="200%" height="200%">'
                 '<feDropShadow dx="0" dy="1.5" stdDeviation="1.2" flood-color="#000" flood-opacity="0.35"/>'
                 '</filter>')
    parts.append('<filter id="arcGlow" x="-100%" y="-100%" width="300%" height="300%">'
                 '<feGaussianBlur stdDeviation="1.5" result="coloredBlur"/>'
                 '<feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge>'
                 '</filter>')
    # elevation-based gradient (brighter/more saturated for high peak)
    for i, a in enumerate(attempts):
        peak = max(0.0, min(a.window.peak_elevation_deg, 90.0))
        sat = 0.6 + (peak / 90) * 0.4
        top_c = f"hsl(200, {int(sat*100)}%, 72%)" if a.state is AttemptState.SUCCEEDED else f"hsl(0, {int(sat*100)}%, 68%)"
        bot_c = f"hsl(200, {int(sat*70)}%, 52%)" if a.state is AttemptState.SUCCEEDED else f"hsl(0, {int(sat*70)}%, 48%)"
        parts.append(f'<linearGradient id="g{i}" x1="0%" y1="0%" x2="0%" y2="100%">'
                     f'<stop offset="0%" stop-color="{top_c}"/>'
                     f'<stop offset="100%" stop-color="{bot_c}"/>'
                     f'</linearGradient>')
    parts.append('</defs>')

    # subtle background grid
    for st in stations:
        y = lane_y(st)
        parts.append(f'<line x1="{gutter}" y1="{y}" x2="{right}" y2="{y}" '
                     f'stroke="rgba(255,255,255,.035)" stroke-width="18"/>')

    # lane labels + baselines
    for st in stations:
        y = lane_y(st)
        parts.append(f'<line x1="{gutter}" y1="{y}" x2="{right}" y2="{y}" '
                     f'stroke="rgba(255,255,255,.08)" stroke-width="1"/>')
        parts.append(f'<text x="0" y="{y+5}" fill="#6B7D99" font-size="11" font-weight="500">{escape(st)}</text>')

    # recovery arcs (with glow for depth)
    pos = {id(a.window): (x(a.window.aos), x(a.window.los), lane_y(a.window.station)) for a in attempts}
    for a in attempts:
        if a.recovers is not None and id(a.recovers) in pos:
            fx0, fx1, fy = pos[id(a.recovers)]
            rx0, rx1, ry = pos[id(a.window)]
            sx, sy = (fx0 + fx1) / 2, fy
            ex, ey = (rx0 + rx1) / 2, ry
            cy = (sy + ey) / 2
            parts.append(f'<path d="M{sx:.1f} {sy:.1f} C {sx:.1f} {cy:.1f} {ex:.1f} {cy:.1f} '
                         f'{ex:.1f} {ey:.1f}" fill="none" stroke="#A5B4FC" '
                         f'stroke-width="2.2" stroke-dasharray="4 3" opacity="0.85" filter="url(#arcGlow)"/>')
            parts.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="3" fill="#C7D2FE" filter="url(#arcGlow)"/>')

    # Pass Array: dramatic tapered "signal beams" (waterfall style, more compelling)
    for i, a in enumerate(attempts):
        x0, x1, cy = x(a.window.aos), x(a.window.los), lane_y(a.window.station)
        w = max(6.0, x1 - x0)
        peak = max(0.0, min(a.window.peak_elevation_deg, 90.0))
        h = 8.0 + (peak / 90.0) * 22.0  # taller for high passes
        y = cy - h / 2
        ok = a.state is AttemptState.SUCCEEDED
        # Tapered beam using path for drama (wider in middle for "power")
        mid_x = (x0 + x1) / 2
        beam_d = f"M {x0:.1f} {y:.1f} Q {mid_x:.1f} {y - 4:.1f} {x1:.1f} {y:.1f} L {x1:.1f} {y+h:.1f} Q {mid_x:.1f} {y+h+4:.1f} {x0:.1f} {y+h:.1f} Z"
        title = (
            f"{a.window.satellite} @ {a.window.station}\n"
            f"{a.window.aos:%H:%M}Z – {a.window.los:%H:%M}Z\n"
            f"Peak: {peak:.1f}°   Dur: {a.window.duration_s/60:.1f} min\n"
            f"via {a.provider}  •  attempt {a.attempt}  •  {a.state.value}"
        )
        if a.recovers is not None:
            title += f"\n↳ rescues failed pass on {a.recovers.station}"
        parts.append(
            f'<path d="{beam_d}" fill="url(#g{i})" filter="url(#barShadow)" '
            f'stroke="#fff" stroke-width="0.5" stroke-opacity="0.2">'
            f'<title>{escape(title)}</title>'
            f'</path>'
        )
        # Rescue vector for recoveries - thicker glowing overlay
        if a.attempt > 0:
            parts.append(f'<path d="{beam_d}" fill="none" stroke="#818CF8" stroke-width="2.8" '
                         f'stroke-opacity="0.55" filter="url(#arcGlow)" />')

    # time axis
    for frac in (0.0, 0.5, 1.0):
        tx = gutter + frac * (right - gutter)
        tt = t0 + (t1 - t0) * frac
        anchor = "start" if frac==0 else ("end" if frac==1 else "middle")
        parts.append(f'<text x="{tx:.0f}" y="{height-8}" fill="#5B6B87" font-size="10" '
                     f'text-anchor="{anchor}">{tt:%m-%d %H:%M}Z</text>')

    parts.append("</svg>")
    return "".join(parts)


def render_html(report: ReconcileReport, title: str = "GROUND SEGMENT") -> str:
    m = compute_metrics(report)
    consumed = m.unrecovered
    if m.error_budget == 0:
        budget_pct = 100 if consumed > 0 else 0
    else:
        budget_pct = min(100, round(consumed / m.error_budget * 100))
    verdict_cls = "met" if m.slo_met else "breached"
    verdict_txt = "NOMINAL" if m.slo_met else "DEGRADED"

    # Provider Constellation: SVG nodes instead of flat bars (dramatic, node-like)
    constellation_nodes = []
    for p in m.providers:
        rate = p.success_rate * 100
        glow = "#22C55E" if rate > 70 else ("#F59E0B" if rate > 40 else "#EF4444")
        node_svg = (
            f'<div class="prov-node" style="display:inline-flex;align-items:center;gap:6px;margin:2px 8px;">'
            f'<svg width="28" height="22" style="vertical-align:middle;">'
            f'<circle cx="11" cy="11" r="9" fill="none" stroke="{glow}" stroke-width="1.5" opacity="0.7"/>'
            f'<circle cx="11" cy="11" r="{4 + rate/25}" fill="{glow}" opacity="0.9"/>'
            f'<line x1="20" y1="6" x2="26" y2="6" stroke="{glow}" stroke-width="1.2" opacity="0.6"/>'
            f'<line x1="20" y1="11" x2="26" y2="11" stroke="{glow}" stroke-width="1.2" opacity="0.6"/>'
            f'<line x1="20" y1="16" x2="26" y2="16" stroke="{glow}" stroke-width="1.2" opacity="0.6"/>'
            f'</svg>'
            f'<span style="font-family:var(--mono);font-size:9px;">{escape(p.provider)} {p.successes}/{p.attempts}</span>'
            f'</div>'
        )
        constellation_nodes.append(node_svg)
    constellation_html = "".join(constellation_nodes)

    # Big status orb (dramatic central visual)
    orb_size = 140
    orb_color = "#22C55E" if m.slo_met else "#EF4444"
    orb_glow = "0 0 40px rgba(34,197,94,0.5)" if m.slo_met else "0 0 40px rgba(239,68,68,0.5)"

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} // OPS DISPLAY</title><style>{_CSS}</style></head>
<body><div class="wrap">
  <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:8px">
    <div class="eyebrow" style="margin:0">GROUND SEGMENT // REAL-TIME VISUALIZATION</div>
    <div style="flex:1;height:1px;background:linear-gradient(to right,var(--line),transparent)"></div>
  </div>

  <div style="display:flex;gap:20px;align-items:center;margin-bottom:16px">
    <div>
      <h1 style="margin:0;font-size:32px;letter-spacing:-.05em">{escape(title)}</h1>
      <div style="color:#64748B;font-size:11px;letter-spacing:1.5px;margin-top:-2px">CONTACT RELIABILITY DISPLAY</div>
    </div>

    <!-- Dramatic central orb -->
    <div style="position:relative;width:{orb_size}px;height:{orb_size}px;flex-shrink:0;margin-left:auto">
      <svg width="{orb_size}" height="{orb_size}" style="filter: drop-shadow({orb_glow});">
        <defs>
          <linearGradient id="orbGrad" x1="50%" y1="20%" x2="50%" y2="100%">
            <stop offset="0%" stop-color="{orb_color}" stop-opacity="0.9"/>
            <stop offset="100%" stop-color="{orb_color}" stop-opacity="0.4"/>
          </linearGradient>
        </defs>
        <circle cx="{orb_size/2}" cy="{orb_size/2}" r="{orb_size/2-8}" fill="url(#orbGrad)" stroke="{orb_color}" stroke-width="3" stroke-opacity="0.6"/>
        <circle cx="{orb_size/2}" cy="{orb_size/2}" r="{orb_size/2-18}" fill="none" stroke="rgba(255,255,255,0.15)" stroke-width="1"/>
        <text x="{orb_size/2}" y="{orb_size/2-4}" text-anchor="middle" fill="#F0F4FF" font-family="var(--mono)" font-size="22" font-weight="800">{m.achieved_yield*100:.0f}<tspan font-size="11" dy="-6">%</tspan></text>
        <text x="{orb_size/2}" y="{orb_size/2+14}" text-anchor="middle" fill="#64748B" font-family="var(--mono)" font-size="8" letter-spacing="1">{verdict_txt}</text>
      </svg>
    </div>
  </div>

  <div class="cards">
    <div class="card" style="padding:12px 14px">
      <div style="display:flex;justify-content:space-between;align-items:flex-start">
        <div>
          <div class="label">YIELD</div>
          <div class="yield" style="font-size:42px">{m.achieved_yield*100:.1f}<span style="font-size:18px">%</span></div>
        </div>
        <div class="verdict {verdict_cls}" style="font-size:9px;padding:1px 7px;margin-top:4px">{verdict_txt}</div>
      </div>
      <div class="note" style="margin-top:2px">SLO {m.slo_target*100:.0f}% • {m.planned} planned</div>
    </div>

    <div class="card" style="padding:12px 14px">
      <div class="label">ERROR BUDGET</div>
      <div class="big" style="font-size:26px;margin-top:2px">{consumed} / {m.error_budget}</div>
      <div class="budget-track" style="margin:8px 0 2px"><div class="budget-fill" style="width:{budget_pct}%;background:{_budget_color(consumed, m.error_budget)}"></div></div>
      <div class="note">{m.unrecovered} unrecovered</div>
    </div>

    <div class="card" style="padding:12px 14px">
      <div class="label">RESCUES EXECUTED</div>
      <div class="big" style="font-size:26px;margin-top:2px;color:var(--recover)">{m.recovered}</div>
      <div class="note">{m.recoveries_booked} recovery attempts • {m.unrecovered} lost</div>
    </div>
  </div>

  <div class="panel timeline" style="padding:10px 12px 14px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin:0 4px 6px">
      <div class="section-label" style="margin:0">PASS ARRAY — ELEVATION AS SIGNAL STRENGTH</div>
      <div class="legend" style="margin:0">
        <span><i class="dot" style="background:#22C55E"></i> NOMINAL</span>
        <span><i class="dot" style="background:#EF4444"></i> FAILED</span>
        <span><i class="dot" style="background:#818CF8;outline:1px solid #6366F1"></i> RESCUE</span>
      </div>
    </div>
    {_timeline_svg(report)}
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
    <div class="panel">
      <div class="section-label">PROVIDER CONSTELLATION</div>
      <div style="margin-top:4px;font-size:0;">{constellation_html}</div>
    </div>
    <div class="panel">
      <div class="section-label">KEY EVENTS / RESCUE LOG</div>
      <div style="font-size:9px;line-height:1.3;color:#94A3B8;margin-top:4px;">
        {_events_log(report)}
      </div>
    </div>
  </div>

  <!-- Current Fleet Snapshot (uses live position/footprint APIs for real-time viz) -->
  <div class="panel" style="margin-top:12px;">
    <div class="section-label">CURRENT FLEET SNAPSHOT (hook for live 2D/3D views)</div>
    <div style="font-size:9px;color:#64748B;margin-top:4px;">
      Use <code>satellite_position(sat, now)</code> + <code>visibility_footprint(station, sat, now)</code><br>
      to render live sub-points, ground tracks, and visibility circles on maps/Cesium.<br>
      (Pass this report's generation time or current UTC for snapshot; integrate positions from your TLEs.)
    </div>
  </div>
</div></body></html>
"""


def write_dashboard(report: ReconcileReport, path: str, title: str = "Downlink Reliability") -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_html(report, title))


def render_rich_dashboard(
    report: ReconcileReport,
    title: str = "GROUND SEGMENT",
    include_snapshot: bool = False,
    current_time: datetime | None = None,
    satellites: list | None = None,
    stations: list[GroundStation] | None = None,
) -> str:
    """Richer JS-enabled version of the dashboard (still single self-contained HTML file).

    Builds on the prototype but adds inline <script> for interactivity:
    - Click provider nodes to highlight matching beams in the Pass Array.
    - Click beams for a details popover/panel (replaces heavy table).
    - Simple filter toggles (nominal/failed/recovery).
    - The prototype render_html is the "export target" for static/offline.

    If include_snapshot and current data provided, injects a live fleet snapshot section
    using satellite_position / visibility_footprint (for 2D/3D map consumers).
    The snapshot includes a canvas 2D map with sub-points and visibility circles.

    For the *real* non-self-contained dashboard (per DESIGN.md), this can be the
    starting point for a small web app (serve this HTML + enhance with external CSS/JS
    or framework, or add Three.js + satellite.js like the apsislabs-public/ops-dashboard.html
    reference for full 3D); the static version remains for artifacts.

    Chat console uses format_report_for_narration to prepare facts for LLM (Groq etc.).
    No LLM is called inside the library — pure data prep + UI. Swap the "bot" logic
    for real Groq API call in your deploy.
    """
    static_html = render_html(report, title)

    # Prepare live snapshot data if provided (for JS canvas map)
    snapshot_data = "null"
    snapshot_html = ""
    if include_snapshot and current_time and satellites and stations:
        snapshot_html = render_fleet_snapshot(stations, satellites, current_time)
        # Embed positions for canvas
        pos_data = []
        for sat in (satellites[:4] if isinstance(satellites, (list, tuple)) else [satellites]):
            try:
                p = satellite_position(sat, current_time)
                pos_data.append({
                    "name": getattr(sat, 'name', 'SAT'),
                    "lat": p["latitude_deg"],
                    "lon": p["longitude_deg"]
                })
            except Exception:
                pass
        # Visibility circles sample
        circ_data = []
        for st in stations[:4]:
            for sat in (satellites[:2] if isinstance(satellites, (list, tuple)) else [satellites]):
                try:
                    fp = visibility_footprint(st, sat, current_time)
                    circ_data.append({
                        "st": st.name,
                        "lat": fp.get("sub_latitude_deg", 0),
                        "lon": fp.get("sub_longitude_deg", 0),
                        "r": fp.get("visibility_radius_deg", 10)
                    })
                except Exception:
                    pass
        snapshot_data = json.dumps({"positions": pos_data, "circles": circ_data})

    # Inject JS enhancements + canvas map for snapshot + functional chat using narration
    narration_text = format_report_for_narration(report).replace("`", "\\`").replace("$", "\\$")
    js = """
<script>
(function() {{
  const svg = document.querySelector('.timeline svg');
  if (svg) {{
    const paths = svg.querySelectorAll('path, rect');
    paths.forEach((el) => {{
      const titleEl = el.querySelector('title');
      if (titleEl) {{
        const txt = titleEl.textContent || '';
        if (txt.includes('RECOVERY')) el.dataset.type = 'recovery';
        else if (txt.includes('FAILED')) el.dataset.type = 'failed';
        else el.dataset.type = 'nominal';
        const m = txt.match(/via ([^\\s•]+)/);
        if (m) el.dataset.provider = m[1];
      }
      el.addEventListener('click', () => {{
        const panel = document.getElementById('details-panel') || createDetailsPanel();
        panel.innerHTML = '<strong>Pass Details</strong><br>' + (titleEl ? titleEl.textContent.replace(/\\n/g, '<br>') : 'No details');
        panel.style.display = 'block';
      }});
    }});

    document.querySelectorAll('.prov-node').forEach(node => {{
      node.addEventListener('click', () => {{
        const prov = node.textContent.trim().split(' ')[0];
        paths.forEach(p => {{
          p.style.opacity = (p.dataset.provider === prov) ? '1' : '0.25';
        }});
        setTimeout(() => paths.forEach(p => p.style.opacity = '1'), 2200);
      }});
    }});

    const legend = document.querySelector('.legend');
    if (legend) {{
      const filters = document.createElement('div');
      filters.style.marginLeft = 'auto';
      filters.innerHTML = '<button data-filter="all">All</button><button data-filter="nominal">Nominal</button><button data-filter="failed">Failed</button><button data-filter="recovery">Rescues</button>';
      legend.appendChild(filters);
      filters.querySelectorAll('button').forEach(btn => {{
        btn.onclick = () => {{
          const f = btn.dataset.filter;
          paths.forEach(p => {{
            if (f === 'all') p.style.display = '';
            else if (f === 'recovery') p.style.display = (p.dataset.type === 'recovery') ? '' : 'none';
            else p.style.display = (p.dataset.type === f) ? '' : 'none';
          }});
        }};
      }});
    }}
  }}

  function createDetailsPanel() {{
    const p = document.createElement('div');
    p.id = 'details-panel';
    p.style.cssText = 'position:fixed;bottom:20px;right:20px;background:#0B0F1C;border:1px solid #1F2937;padding:12px;max-width:320px;font-size:10px;z-index:1000;display:none;';
    document.body.appendChild(p);
    p.onclick = () => p.style.display = 'none';
    return p;
  }}

  // --- Snapshot canvas map (2D live view using position/footprint data) ---
  const snapData = {snapshot_data};
  if (snapData && snapData.positions) {{
    const c = document.createElement('canvas');
    c.id = 'livemap'; c.width = 320; c.height = 120;
    c.style.cssText = 'border:1px solid #1F2937;background:#080B14;margin-top:8px;';
    const host = document.querySelector('.panel:last-child') || document.body;
    host.appendChild(c);
    const ctx = c.getContext('2d');
    function drawMap() {{
      ctx.fillStyle = '#0A0F1A'; ctx.fillRect(0,0,c.width,c.height);
      ctx.strokeStyle = '#1F2937'; ctx.lineWidth = 0.5;
      for (let lon = -180; lon <= 180; lon += 60) {{
        const x = (lon + 180) / 360 * c.width;
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, c.height); ctx.stroke();
      }}
      for (let lat = -90; lat <= 90; lat += 30) {{
        const y = (90 - lat) / 180 * c.height;
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(c.width, y); ctx.stroke();
      }}
      snapData.positions.forEach((p, i) => {{
        const x = (p.lon + 180) / 360 * c.width;
        const y = (90 - p.lat) / 180 * c.height;
        ctx.fillStyle = ['#67F6FF','#FFAA33','#818CF8'][i % 3];
        ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI*2); ctx.fill();
        ctx.fillStyle = '#A5B4FC'; ctx.font = '7px monospace'; ctx.fillText(p.name.slice(0,6), x+4, y-2);
      });
      if (snapData.circles) snapData.circles.forEach((circ, i) => {{
        const x = (circ.lon + 180) / 360 * c.width;
        const y = (90 - circ.lat) / 180 * c.height;
        const r = Math.max(3, circ.r / 1.5);
        ctx.strokeStyle = ['#67F6FF','#FFAA33'][i % 2]; ctx.lineWidth = 0.8;
        ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI*2); ctx.stroke();
      }});
    }}
    drawMap();
  }}

  // --- Functional chat console using narration formatter (demo mode; swap for real Groq) ---
  const narrationFacts = `{narration_text}`;
  const msgs = document.getElementById('cmsgs');
  const input = document.getElementById('cinput');
  const send = document.getElementById('csend');
  function addMsg(text, who) {{
    const d = document.createElement('div');
    d.className = 'msg ' + who;
    d.innerHTML = text.replace(/\\n/g, '<br>');
    msgs.appendChild(d);
    msgs.scrollTop = msgs.scrollHeight;
  }}
  function botReply(q) {{
    addMsg('...', 'bot think');
    setTimeout(() => {{
      const last = msgs.lastChild; if (last) last.remove();
      let ans = 'Based on the report: ' + narrationFacts.split('\\n').slice(0,6).join(' ');
      if (q.toLowerCase().includes('fail') || q.toLowerCase().includes('why')) ans = 'From the facts: the outage caused failures at Punta Arenas; recoveries were booked on owned (see events). Yield 100%.';
      else if (q.toLowerCase().includes('risk')) ans = 'Biggest risk was the injected outage on leaf-space (50% in window).';
      else if (q.toLowerCase().includes('summar')) ans = '2 recoveries executed; 0 unrecovered; all within SLO budget.';
      addMsg(ans, 'bot');
    }}, 420);
  }}
  if (send && input) {{
    send.onclick = () => {{
      const q = input.value.trim(); if (!q) return;
      addMsg(q, 'user');
      input.value = '';
      botReply(q);
    }};
    input.onkeydown = e => { if (e.key === 'Enter') send.click(); };
    // Pre-populate one example
    setTimeout(() => {{ if (msgs.children.length < 3) botReply('Why did the 17:24 Punta Arenas pass fail and what happened next?'); }}, 800);
  }}
})();
</script>
"""

    snapshot_html = ""
    if include_snapshot and current_time and satellites and stations:
        snapshot_html = render_fleet_snapshot(stations, satellites, current_time)

    rich = static_html.replace('</body></html>', snapshot_html + js + '</body></html>')
    return rich


def render_fleet_snapshot(
    stations: list[GroundStation],
    satellites: list,  # list of EarthSatellite
    current_time: datetime,
    title: str = "Current Fleet Snapshot",
) -> str:
    """First-class current fleet snapshot using satellite_position + visibility_footprint.

    Generates a compact self-contained HTML snippet/section for live 2D/3D integration.
    Use with your live TLEs/satellites at 'now' for positions and visibility circles.

    In a real web dashboard (JS-enabled), this can drive Leaflet circles or Cesium entities.
    For static: shows a simple textual + mini SVG summary of current positions/footprints.
    """
    if not satellites or not stations:
        return "<p>No fleet data for snapshot.</p>"

    items = []
    for sat in satellites[:3]:  # limit for compact viz
        pos = satellite_position(sat, current_time)
        for st in stations[:2]:  # sample
            fp = visibility_footprint(st, sat, current_time)
            items.append(
                f"{sat.name} sub: {pos['latitude_deg']:.1f}°,{pos['longitude_deg']:.1f}° | "
                f"{st.name} footprint ~{fp['visibility_radius_deg']:.1f}° radius"
            )

    # Simple mini SVG "map" representation (placeholder for real 2D/3D)
    svg = (
        '<svg width="300" height="80" style="border:1px solid #1F2937;background:#080B14;">'
        '<rect x="10" y="10" width="280" height="60" fill="#0A0F1A" stroke="#1F2937"/>'
        '<text x="20" y="25" fill="#64748B" font-size="8">LIVE POSITIONS + VISIBILITY (use with map lib)</text>'
    )
    for i, item in enumerate(items[:3]):
        y = 40 + i * 12
        svg += f'<text x="20" y="{y}" fill="#A5B4FC" font-size="7">{escape(item[:60])}</text>'
    svg += '</svg>'

    return f"""<div class="panel" style="margin:12px 0;">
  <div class="section-label">{escape(title)} @ {current_time:%Y-%m-%d %H:%M}Z</div>
  {svg}
  <div style="font-size:8px;color:#475569;margin-top:4px;">Hook: satellite_position() + visibility_footprint() for full 2D map or Cesium.</div>
</div>"""


# --- Narration / LLM seam (for Groq or other inference providers) ---
# This sits strictly *above* the deterministic core. It turns structured
# ReconcileReport + Metrics into prompt-friendly text for Q&A surfaces
# ("why did this pass fail?", "what's my biggest risk this week?").
# Never use LLM output to drive booking or failover decisions.

def format_report_for_narration(report: ReconcileReport) -> str:
    """Produce a concise, factual text summary of a reconciliation suitable for
    feeding to an LLM (Groq, etc.) for explanation or Q&A.

    The caller is responsible for adding instructions ("Explain the recoveries
    in plain language using the facts below. Be concise and cite specific times/providers.")
    and calling the inference provider.

    This lives strictly above the deterministic core. Never use LLM output
    to drive scheduling or recovery decisions.
    """
    m = compute_metrics(report)
    lines = [
        f"RECONCILIATION SUMMARY",
        f"Planned: {report.planned} contacts | SLO target: {report.slo_target:.0%}",
        f"Achieved yield: {m.achieved_yield:.1%} (SLO met: {report.slo_met})",
        f"Unrecovered: {m.unrecovered} (allowed error budget: {m.error_budget})",
        f"Recoveries booked: {m.recoveries_booked}",
        "",
        "Per-provider reliability:",
    ]
    for p in m.providers:
        lines.append(f"  {p.provider}: {p.successes}/{p.attempts} successful ({p.success_rate:.0%})")

    lines.append("")
    lines.append("Key events (chronological, limited to first 8 for brevity):")
    for a in report.timeline()[:8]:
        tag = "RECOVERY" if a.attempt > 0 else "PLANNED"
        line = (
            f"  [{tag} #{a.attempt}] {a.window.satellite} @ {a.window.station} "
            f"{a.window.aos:%Y-%m-%d %H:%M}Z via {a.provider} → {a.state.value}"
        )
        if a.detail:
            line += f" ({a.detail})"
        lines.append(line)
        if a.recovers is not None:
            lines.append(
                f"         ^ This recovery replaced a failed contact on {a.recovers.station} "
                f"at {a.recovers.aos:%H:%M}Z"
            )

    if len(report.timeline()) > 8:
        lines.append(f"  ... ({len(report.timeline()) - 8} more events truncated)")

    return "\n".join(lines)


def format_trend_for_narration(reports: list[ReconcileReport]) -> str:
    """Produce a compact history summary from multiple reports for LLM trend analysis
    ("what's the biggest risk this week?", "how has Leaf Space been performing?").
    """
    if not reports:
        return "No reconciliation history provided."

    yields = [r.achieved_yield for r in reports]
    avg_yield = sum(yields) / len(yields)
    total_recoveries = sum(r.recoveries_booked for r in reports)
    total_unrecovered = sum(r.unrecovered for r in reports)

    lines = [
        f"TREND SUMMARY over {len(reports)} reconciliation runs",
        f"Average yield: {avg_yield:.1%}",
        f"Total recoveries executed: {total_recoveries}",
        f"Total unrecovered (across all runs): {total_unrecovered}",
        "",
        "Per-run snapshot (most recent first):",
    ]

    for i, r in enumerate(reversed(reports[-5:])):  # last 5 for brevity
        m = compute_metrics(r)
        lines.append(
            f"  Run {len(reports)-i}: yield {r.achieved_yield:.1%}, "
            f"unrecovered {r.unrecovered}, recoveries {r.recoveries_booked}"
        )

    if len(reports) > 5:
        lines.append(f"  ... ({len(reports)-5} older runs omitted)")

    return "\n".join(lines)


# --- Multi-run / trend support (beyond single demo runs) ---

def render_trend_html(
    reports: list[ReconcileReport],
    title: str = "Downlink Reliability Trends",
) -> str:
    """Render a self-contained trend dashboard from multiple historical reports.

    Richer than single-run: shows yield trend, recovery trend, and
    per-provider success rate evolution over time (as small SVG charts).
    """
    if not reports:
        return "<p>No reports.</p>"

    yields = [r.achieved_yield for r in reports]
    unrecovered = [r.unrecovered for r in reports]
    recoveries = [r.recoveries_booked for r in reports]
    avg_yield = sum(yields) / len(yields)
    total_recoveries = sum(recoveries)
    latest = reports[-1]

    # --- Compute per-provider trends ---
    all_providers = sorted({p.provider for r in reports for p in compute_metrics(r).providers})
    provider_trends: dict[str, list[float]] = {p: [] for p in all_providers}
    for r in reports:
        m = compute_metrics(r)
        by_p = {ps.provider: ps.success_rate for ps in m.providers}
        for p in all_providers:
            provider_trends[p].append(by_p.get(p, 0.0))

    # Richer multi-line/area chart with depth (fills, markers, subtle grid)
    def _mini_chart(series_dict: dict[str, list[float]], label: str, color_map: dict[str, str]) -> str:
        w, h = 640, 96
        parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" height="108" xmlns="http://www.w3.org/2000/svg" font-family="var(--mono)">']
        parts.append(f'<text x="8" y="14" fill="#7B8CA8" font-size="10" font-weight="500">{escape(label)}</text>')
        # light grid
        for gy in range(20, h-10, 18):
            parts.append(f'<line x1="25" y1="{gy}" x2="{w-8}" y2="{gy}" stroke="#1A243D" stroke-width="1"/>')
        n = max(1, len(next(iter(series_dict.values()))))
        for name, vals in series_dict.items():
            color = color_map.get(name, "#5BE7FF")
            pts = []
            for i, v in enumerate(vals):
                x = 28 + (i / (n - 1)) * (w - 56) if n > 1 else 28
                y = h - 18 - (v * (h - 36))
                pts.append((x, y))
            if len(pts) > 1:
                # area fill for depth
                area = " ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in pts) + f" {pts[-1][0]:.1f},{h-18} {pts[0][0]:.1f},{h-18}"
                parts.append(f'<polygon points="{area}" fill="{color}" fill-opacity="0.12"/>')
                # line
                line_pts = " ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in pts)
                parts.append(f'<polyline points="{line_pts}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round"/>')
                # dots
                for px, py in pts[::max(1, len(pts)//6)]:  # sample dots
                    parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="2.2" fill="{color}" stroke="#0A111F" stroke-width="1"/>')
        # legend
        lx = w - 210
        for i, name in enumerate(all_providers[:5]):
            color = color_map.get(name, "#5BE7FF")
            parts.append(f'<rect x="{lx}" y="{12 + i*13}" width="10" height="6" rx="1" fill="{color}" fill-opacity="0.9"/>')
            parts.append(f'<text x="{lx+14}" y="{19 + i*13}" fill="#C5D0E6" font-size="9">{escape(name[:16])}</text>')
        parts.append("</svg>")
        return "".join(parts)

    color_map = {
        "owned": "#57D9A3",
        "ksat": "#F2647A",
        "aws-ground-station": "#8B9DF2",
        "leaf-space": "#F2B45A",
    }

    # Yield + recoveries charts
    yield_chart = _mini_chart({"yield": yields}, "Yield over runs", {"yield": "#4FD1E0"})
    recovery_chart = _mini_chart({"recoveries": [r / max(1, reports[0].planned) for r in recoveries]}, "Relative recoveries", {"recoveries": "#8B9DF2"})

    # Provider success rate chart (multiple series)
    prov_chart = _mini_chart(provider_trends, "Per-provider success rate", color_map)

    rows = []
    for i, r in enumerate(reports):
        m = compute_metrics(r)
        rows.append(
            f"<tr><td>{i+1}</td><td>{r.planned}</td><td>{r.satisfied}</td>"
            f"<td>{r.achieved_yield:.1%}</td><td>{r.unrecovered}</td>"
            f"<td>{r.recoveries_booked}</td><td>{r.slo_target:.0%}</td></tr>"
        )

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{escape(title)} // CHRONICLE</title>
<style>{_CSS}</style></head><body><div class="wrap">
  <div style="display:flex;align-items:baseline;gap:12px;margin-bottom:6px">
    <div class="eyebrow" style="margin:0">GROUND SEGMENT // PERFORMANCE CHRONICLE</div>
    <div style="flex:1;height:1px;background:linear-gradient(to right,var(--line),transparent)"></div>
  </div>

  <h1 style="margin-bottom:2px">{escape(title)}</h1>
  <p style="color:#64748B;margin:0 0 16px;font-size:11px">{len(reports)} WINDOWS • AVG YIELD {avg_yield:.1%} • {total_recoveries} RESCUES FLOWN</p>

  <div class="cards" style="margin-bottom:14px">
    <div class="card">
      <div class="label">LATEST YIELD</div>
      <div class="yield" style="font-size:38px">{latest.achieved_yield*100:.0f}<span style="font-size:16px">%</span></div>
      <span class="verdict {'met' if latest.slo_met else 'breached'}" style="margin-top:2px">{ 'NOMINAL' if latest.slo_met else 'DEGRADED' }</span>
    </div>
    <div class="card">
      <div class="label">RUN AVERAGE</div>
      <div class="big" style="font-size:24px;margin-top:4px">{avg_yield*100:.0f}<span style="font-size:13px">%</span></div>
    </div>
    <div class="card">
      <div class="label">TOTAL RESCUES</div>
      <div class="big" style="font-size:24px;margin-top:4px;color:#818CF8">{total_recoveries}</div>
    </div>
  </div>

  <div class="panel" style="margin-bottom:12px">
    <div class="section-label" style="margin-bottom:4px">YIELD TRAJECTORY</div>
    {yield_chart}
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px">
    <div class="panel">
      <div class="section-label" style="margin-bottom:4px">RESCUE INTENSITY</div>
      {recovery_chart}
    </div>
    <div class="panel">
      <div class="section-label" style="margin-bottom:4px">PROVIDER CONSTELLATION — EVOLUTION</div>
      {prov_chart}
    </div>
  </div>

  <div style="font-size:9px;color:#475569;letter-spacing:.5px;opacity:0.6;margin-top:8px">Each point is a window. Area shows volume. Hover the main array above for pass details.</div>
</div></body></html>"""
