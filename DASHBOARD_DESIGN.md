# Real Dashboard Design Requirements

**Status**: Prototype (current `render_html` / `render_trend_html` in `observability.py`) is complete and functional for the spine. It is a self-contained, zero-dependency HTML+SVG artifact suitable for offline use, tickets, emails, and basic ops readouts.

**User Feedback on Prototype**:
- "Plain, boring, and flat."
- "It all feels like a report. This is not compelling at all!"
- "When we build the real dashboard, we need a better layout, color, theme, style etc."

The prototype prioritizes the original constraint: "The dashboard has no external dependencies: inline CSS and SVG only, so it opens offline and renders the same anywhere."

## Goals for the Real Dashboard
- **Compelling visualization**, not a report or readout.
- Make the reliability story *feel alive*: high-value passes stand out dramatically, recoveries read as rescues, providers as a living system.
- Support the full observability needs: single-run status, historical trends, per-provider reliability, error budget, SLO compliance.
- Usable in real operations: for a monitor loop, post-pass analysis, team dashboards, or exported artifacts.
- Modern, professional mission-control aesthetic (space/ground-segment theme) without being gimmicky.

## Constraints & Considerations
- **Self-containment**: Prototype must remain fully offline/single-file. Real version *may* relax this (e.g., small web app, TUI, or richer static site with optional assets) if it enables better UX. Provide an "export" path back to self-contained HTML.
- **Data sources**: Built on `ReconcileReport` (from reconciler), `Metrics`, and persisted JSON reports. Support single report + list of historical reports for trends.
- **Performance**: Handle realistic data volumes (dozens of passes per run, hundreds of historical runs). Keep rendering fast.
- **Extensibility**: Easy to add new visual elements (e.g., cost views, per-satellite trends, predicted vs actual).
- **Integration**: Usable from Python (library call to generate), CLI, or embedded in larger ops tools. Works with the existing spine (no changes to visibility/scheduler/reconciler/providers needed).
- **Theming & Accessibility**: Support dark (default, space ops) + light themes. High contrast. Colorblind-friendly palettes. Respect the existing `--zenith`, `--horizon`, `--ok`, `--fail`, `--recover` semantic colors as a starting point.
- **No flight-critical dependency**: Purely for visibility/observability.

## Core Visual Language & Theme
- **Overall aesthetic**: Dark "mission control" / "ground segment ops" — deep blacks/blues, subtle starfield or grid backgrounds, HUD-like elements (thin lines, monospaced data, glowing accents). Professional, not sci-fi cartoon.
- **Colors** (expand on current vars):
  - Backgrounds: Very dark (#05070F to #0B0F1C), with subtle radial gradients or noise for depth.
  - Accents: Zenith/cyan for high-value/nominal (#67F6FF), Horizon/orange for lower value (#FFAA33), Indigo for recoveries (#818CF8).
  - Status: Green (#22C55E) for nominal/SLO met, Red (#EF4444) for degraded/breached. Use saturation + glow for emphasis.
  - Text: High-contrast off-white for data, muted grays for labels. Avoid pure black/white.
  - Gradients: Subtle multi-stop for depth (e.g., on status orbs, pass bars, provider "signal" meters). Avoid flat fills.
- **Typography**: Mix of clean sans (for labels/headers) + monospace (for data, times, IDs). Strong hierarchy: huge numbers for key metrics (yield %), smaller for details.
- **Motion (if runtime allows)**: Subtle CSS animations or SVG for "live" feel — gentle pulsing on current/nominal elements, slow "scan" lines on timelines, fade-ins for recoveries. Disable for static exports.
- **Depth & Polish**: Layered shadows (soft outer + inner highlights), rounded corners (8-16px), glassmorphism or subtle borders on cards/panels. Avoid 2010s flat design. Use elevation (z-index + shadows) to create focal points.

## Layout & Structure
- **Single-run view** (replaces current `render_html`):
  - Hero / Top: Large status "orb" or gauge (SVG) showing overall yield % + SLO verdict (NOMINAL / DEGRADED). Big, centered, glowing. Side-by-side with high-level summary strip (planned, recoveries executed, stations involved).
  - Main Visualization: Expanded "Pass Array" or "Contact Timeline" — artistic SVG. Stations as vertical lanes or a "ground array". Passes as glowing horizontal bars or signal beams (height/brightness/color intensity = peak elevation). Recoveries as prominent curved "rescue vectors" with arrows/glows connecting failed → recovery pass. Time axis with clear labels. Make it the visual centerpiece — less "bars on lanes", more dynamic/immersive (e.g., slight curvature for passes, background "sky" gradient or orbital hints).
  - Provider Fleet / Constellation: Visual row or grid of providers. Each as a "signal meter" or mini constellation node (bar + glow + success count). Clicking/hovering (if interactive) shows details. Color by recent reliability.
  - Supporting Info: Minimal, contextual only. Hover tooltips on every visual element for full pass details (satellite, times, peak, duration, provider, outcome). Optional collapsible "raw log" or per-attempt list at bottom. No primary data tables.
  - Footer: Generation timestamp, SLO target, run ID, "exported from space-orchestrator".

- **Trends / Multi-run view** (replaces `render_trend_html`):
  - Hero: Overall performance "chronicle" graphic (main SVG chart showing yield trajectory over runs, with area fills, markers, and overlaid SLO line).
  - Secondary Charts: 
    - Rescue intensity / recovery volume over time.
    - Per-provider reliability "constellation evolution" (multiple lines or small multiples showing success rates over runs).
    - Error budget burn or unrecovered trend.
  - Summary strip: Aggregates (avg yield, total rescues, SLO compliance % across window).
  - Timeline strip or sparklines: Quick visual history selector.
  - Detail on demand: Clicking a run in the chart surfaces the single-run viz (or links to it). Table of runs only as fallback/secondary.
  - Narrative elements: Subtle callouts like "Peak recovery window" or "Provider X degradation detected".

- **General Layout Principles**:
  - Generous whitespace, strong focal points (the big orb + main viz).
  - Responsive but optimized for desktop/ops screens (wide timeline).
  - Grid or flex with clear sections; avoid dense "report" stacking.
  - Dark-first, with good contrast. Subtle backgrounds (starfield/grid) for interest without distraction.
  - Consistent iconography (simple SVG symbols for passes, recoveries, providers).

## Key Features & Interactions (for Real Version)
- **Visual Encoding**:
  - Pass quality: Height + color saturation + glow intensity (higher peak = taller/brighter).
  - Outcome: Color (green nominal, red failed) + stroke/glow for recoveries.
  - Time: Horizontal positioning + labels. Support zooming/panning if interactive.
  - Providers: Color per provider, size/glow by volume or reliability.
- **Interactivity** (if not pure static):
  - Hover/tooltip on every element (pass, arc, provider bar, chart point).
  - Click to highlight related elements (e.g., click recovery → highlight original failure).
  - Filters: By provider, satellite, time range, outcome.
  - Time-scrubber for trends.
- **Export**: Button to generate the current self-contained prototype HTML from the rich view.
- **Real-time / Updates**: Support streaming updates (e.g., poll outcomes and refresh viz without full reload).
- **Multi-fleet / Comparison**: Support comparing two satellites/runs side-by-side.
- **Accessibility**: ARIA labels on SVG, keyboard nav, screen-reader friendly text alternatives.
- **Performance**: Virtualize long timelines if needed; efficient SVG updates.

## Technical Approach Options for Real Dashboard
1. **Enhanced Self-Contained Static** (quick win): Keep inline but push SVG/CSS much further (more complex paths, CSS variables for easy theming, embedded small fonts if allowed, advanced filters/animations). Good for the "export artifact" use case.
2. **Small Web App / Dashboard Server** (recommended for "real"): 
   - FastAPI or similar backend serving the rich UI (HTML + small JS + CSS, perhaps Tailwind or custom modern CSS).
   - Frontend: Modern framework-light (vanilla + HTMX, or Svelte/Vue for components) or even pure JS with SVG + D3/Chart.js for charts.
   - Features: Live updates, historical browser, search/filter, dark/light toggle, shareable views.
   - Data: Load from persisted reports (JSON) or direct from Reconciler in-memory.
3. **Hybrid**: Rich web UI + "Export to standalone HTML" button that serializes current state into the prototype format.
4. **TUI Alternative**: For terminal-heavy ops, a Rich/Textual-based console dashboard (complementary to web).

**Recommendation**: Start with option 2 (light web app) for daily use, with option 1 as the offline/export path. The prototype can serve as the export target.

## Success Metrics
- Feels exciting and informative at a glance (not something you have to "read").
- Clearly communicates the value of the reconciler (recoveries as wins, not just numbers).
- Easy to customize/theme for different operators.
- Maintains (or improves) the prototype's strengths: reliability data, SLO focus, provider neutrality, offline capability via export.
- Positive user feedback on "compelling" vs. "report".

## Concrete Proposals for Layout, Color, Theme & Style

### Overall Aesthetic Direction
Move from "clean technical report" to "mission operations console / ground segment HUD".
- **Theme name idea**: "Orbit Control" — dark space black (#0A0F1A base) with deep navy panels, electric cyan/zenith accents, warm horizon oranges for lower-value passes, and recovery indigo as a "rescue" highlight.
- **Feel**: High-information-density but scannable at a glance. Subtle scanlines or faint grid (CSS background or SVG), soft glows on critical elements, no heavy borders or "cards" that scream "dashboard report".
- **Typography**: Primary sans (Inter or system) for headers, strict monospace (SF Mono / JetBrains) for all telemetry, times, IDs, and metrics. Large, bold numbers for key metrics (yield %), smaller for details. Minimal body text — let visuals carry the story.
- **Motion (if runtime allows)**: Very restrained — gentle 1-2s pulses on nominal elements, slow horizontal "data sweep" on timelines, fade-ins for recoveries. Disable for static exports.

### Color Palette (expand on current vars)
Keep `--zenith`, `--horizon`, `--ok`, `--fail`, `--recover` as the semantic core, but give them richer stops and use them for more than flat fills:

- Backgrounds: #05070F (deepest), #0A0F1A (panels), subtle #0F1626 with 1-2% white noise or radial vignette for "space" depth.
- Zenith (high-value / nominal): #67F6FF → #A5F3FF (brighter top of gradients).
- Horizon (lower value): #FFAA33 → #FFD580.
- Recoveries: #818CF8 with a secondary glow #C7D2FE.
- Nominal: #22C55E with soft glow.
- Degraded/Breached: #EF4444 with stronger warning glow.
- Text: #E8F0FE (primary), #94A3B8 (secondary), #64748B (labels).
- Accents: Very sparing use of #6366F1 for interactive or "selected" states.

Use gradients and glows liberally on status elements (orb, pass bars, provider "signal" meters). Flat colors only for secondary data.

### Layout — Single-Run View (replaces current `render_html`)
**Goal**: One powerful focal visual + supporting context, minimal text.

Proposed structure (desktop-first, ~1200px wide):

1. **Minimal masthead** (20-30px): Project name + "Ground Segment Ops" + timestamp + "SLO: 95%" pill. Very low visual weight.
2. **Hero status row** (centered or left-heavy):
   - Large SVG "Yield Orb" (140-180px): Concentric rings or segmented circle. Center = big yield % (e.g. 100%). Ring segments or radial gradient show error budget consumption. Glow color = SLO health. Click/hover for quick facts.
   - To the right or below: 3-4 ultra-compact metrics in a horizontal strip (Planned / Recovered / Unrecovered / Stations). Use monospace, tiny labels.
3. **Main Visual — Pass Array / Contact Waterfall** (the star of the page):
   - Much larger artistic SVG (full width, 300-400px tall).
   - Re-imagine stations not as flat horizontal lanes but as a stylized "antenna array" (vertical elements or curved ground stations at bottom).
   - Passes rendered as glowing, slightly curved "beams" or signal paths from satellite (top) to station. 
     - Width or opacity = duration.
     - Height / brightness / saturation = peak elevation (use the zenith/horizon palette).
     - Recovery arcs become thick, dashed, glowing "rescue paths" with arrowheads or fade-out, connecting failure to successful recovery. Make them visually dominant.
   - Time axis at bottom with major ticks + "now" marker if live.
   - Subtle background: faint orbital arc or starfield.
   - Hover any beam → rich tooltip (or side panel) with full telemetry + "value" calculation.
   - Optional: small satellite icons or dots at TCA for each pass.
4. **Provider Constellation strip** (below or side-by-side):
   - Horizontal or 2x2 grid of provider "nodes".
   - Each node: small SVG icon (antenna dish or signal bars) + reliability % + recent success count.
   - Visual weight by volume or impact. Color + glow by current reliability.
   - Clicking a node filters/highlights the Pass Array to that provider.
5. **Supporting context** (bottom, collapsible or very compact):
   - "Key Events" list (only the 3-5 most important: outages, big recoveries, SLO breaches). One-line each.
   - No full per-pass table in the default view. "Export full log" or "Show raw telemetry" button that reveals a clean monospace list.
6. **Footer**: Tiny — generation time, run ID, "exported from space-orchestrator".

**Mobile**: Stack hero orb + metrics, collapse the Pass Array to a simplified vertical list with color-coded bars, keep providers as compact row.

### Layout — Trends / Multi-Run View
- Top: "Performance Chronicle" header + date range selector (if interactive).
- Hero graphic: Large SVG "Yield Trajectory" — main line/area chart with SLO threshold as a strong horizontal reference line. Markers for each run sized by number of recoveries.
- Below in a responsive grid:
  - "Rescue Flow" — stacked or grouped bar/area showing recoveries per run, colored by provider.
  - "Constellation Health" — small-multiples or overlaid lines for per-provider success rate over time (the "evolution" the user wants).
  - "Error Budget Burn" sparkline or small chart.
- Bottom: Compact run selector / filmstrip (tiny cards or dots). Clicking one can overlay or link to the single-run view.
- Avoid long tables entirely in the primary view. "Data table" is an export or "details" drawer.

### Additional Style & Polish Ideas
- **Visual metaphors**:
  - Passes = "downlink beams" or "data streams".
  - Recoveries = "redirected beams" or "rescue links".
  - Providers = nodes in a network/constellation (connections between providers when recoveries switch).
  - Overall health = a "constellation brightness" or single glowing orb per run.
- **Depth without clutter**: Use multiple subtle layers (background grid faint, main elements with soft shadows/glows, top highlights on bars).
- **Data ink**: Maximize information per pixel — encode multiple dimensions in one mark (color + height + width + glow).
- **Export artifacts**: The current prototype can become the "print/PDF-friendly" or "ticket attachment" version. The real dashboard can have a "Generate standalone view" button that renders a simplified but still visually rich version of the same data.
- **Theming system**: Expose a small set of CSS custom properties (or a Python theme dict for the prototype) so operators can brand it (e.g., their company accent color, different "night ops" vs "day ops" palettes).
- **Example references for inspiration** (to be refined with user):
  - SpaceX/NASA mission control displays (clean data overlays on dark, high contrast telemetry).
  - Modern SRE tools with custom dark themes (e.g., Grafana with specific panels, Honeycomb traces, but less dense).
  - Artistic but functional: things like "satellite pass" visualizations on sites such as n2yo.com or SatNOGS, but with reliability overlays.

### Open Design Questions for Real Dashboard
- How interactive should the primary artifact be? (Pure static SVG vs. small amount of vanilla JS for filtering/hovering?)
- Should the real version target a browser tab, an embedded iframe in an existing ops UI, or a standalone desktop/TUI companion?
- Any hard constraints on file size or rendering time for the rich version?
- Preferred fidelity for the Pass Array visual (realistic 2D ground track projection, or purely abstract artistic beams)?

This expanded section gives concrete, actionable direction beyond the high-level goals. When we build the real dashboard we can treat this doc as the starting spec and iterate visually from there (Figma mock, then code).

---
*Expanded June 2026 based on iterative user feedback.*
