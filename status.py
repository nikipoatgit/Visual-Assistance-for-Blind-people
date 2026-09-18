"""Live processing status, shown at /status.

Plain in-memory counters + a rolling window of recent frame diagnostics.
Nothing here is persisted -- it resets every time the process restarts.
Updated by pipeline.py (per frame) and app.py (per aggregation cycle).
This exists specifically so "bus not detecting" / "route not describing"
can be diagnosed by watching what the pipeline actually saw, instead of
guessing from the phone screen alone.
"""

import time
from collections import deque

STARTED_AT = time.time()
MAX_RECENT = 20

_state = {
    "warmup_done": False,
    "warmup_seconds": None,
    "frames_processed": 0,
    "cycles_completed": 0,
    "announcements_made": 0,
    "last_frame": None,
    "last_verdict": None,
}
_recent_frames = deque(maxlen=MAX_RECENT)


def mark_warmup_done():
    _state["warmup_done"] = True
    _state["warmup_seconds"] = round(time.time() - STARTED_AT, 1)


def record_frame(result, ocr_texts=None):
    """Called once per processed frame from pipeline.process_frame()."""
    _state["frames_processed"] += 1
    snapshot = dict(result)
    snapshot["ocr_texts"] = ocr_texts or []
    snapshot["t"] = round(time.time() - STARTED_AT, 1)
    _state["last_frame"] = snapshot
    _recent_frames.append(snapshot)


def record_cycle(verdict, announced):
    """Called once per completed FRAMES_PER_CYCLE burst, from app.on_frame()."""
    _state["cycles_completed"] += 1
    if announced:
        _state["announcements_made"] += 1
    v = dict(verdict)
    v["announced"] = announced
    v["t"] = round(time.time() - STARTED_AT, 1)
    _state["last_verdict"] = v


def snapshot():
    d = dict(_state)
    d["uptime_seconds"] = round(time.time() - STARTED_AT, 1)
    d["recent_frames"] = list(_recent_frames)
    return d


# --------------------------------------------------------------------------
# HTML rendering (auto-refreshing, no JS framework needed)
# --------------------------------------------------------------------------
def _fmt_uptime(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m}m {s}s" if h else f"{m}m {s}s"


def _row(f):
    ocr = ", ".join(f.get("ocr_texts") or []) or "-"
    return (
        "<tr>"
        f"<td>{f.get('t', '')}s</td>"
        f"<td>{f.get('status', '')}</td>"
        f"<td>{f.get('reason', '') or '-'}</td>"
        f"<td>{f.get('bus_number', '') or '-'}</td>"
        f"<td>{f.get('destination', '') or '-'}</td>"
        f"<td>{f.get('confidence', '')}</td>"
        f"<td class='ocr'>{ocr}</td>"
        "</tr>"
    )


def render_html():
    d = snapshot()
    last_frame = d["last_frame"] or {}
    last_verdict = d["last_verdict"] or {}
    rows = "".join(_row(f) for f in reversed(d["recent_frames"])) or (
        "<tr><td colspan='7'>No frames processed yet.</td></tr>"
    )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta http-equiv="refresh" content="2">
<title>Bus Recognition - Status</title>
<style>
  body {{ font-family: -apple-system, Arial, sans-serif; background:#111; color:#eee;
         margin:0; padding:20px; }}
  h1 {{ font-size:20px; margin-bottom:4px; }}
  .sub {{ color:#888; margin-bottom:20px; font-size:13px; }}
  .cards {{ display:flex; flex-wrap:wrap; gap:12px; margin-bottom:24px; }}
  .card {{ background:#1c1c1c; border-radius:8px; padding:12px 16px; min-width:150px; }}
  .card .label {{ font-size:12px; color:#999; }}
  .card .value {{ font-size:22px; font-weight:700; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid #333; }}
  th {{ color:#999; font-weight:600; }}
  td.ocr {{ color:#9cf; max-width:260px; overflow-wrap:anywhere; }}
  .ok {{ color:#6f6; }} .bad {{ color:#f66; }} .warn {{ color:#fc6; }}
  .msg {{ font-size:16px; margin:8px 0 20px; }}
</style>
</head>
<body>
  <h1>AI Bus Recognition - Live Status</h1>
  <div class="sub">Auto-refreshes every 2s. Uptime: {_fmt_uptime(d['uptime_seconds'])}</div>

  <div class="cards">
    <div class="card"><div class="label">Model warmup</div>
      <div class="value {'ok' if d['warmup_done'] else 'warn'}">
        {'Ready (' + str(d['warmup_seconds']) + 's)' if d['warmup_done'] else 'Loading...'}
      </div></div>
    <div class="card"><div class="label">Frames processed</div>
      <div class="value">{d['frames_processed']}</div></div>
    <div class="card"><div class="label">Cycles completed</div>
      <div class="value">{d['cycles_completed']}</div></div>
    <div class="card"><div class="label">Announcements made</div>
      <div class="value">{d['announcements_made']}</div></div>
  </div>

  <h3>Last verdict (10-frame vote)</h3>
  <div class="msg">
    {last_verdict.get('message', '-')}
    &nbsp; <span class="sub">status={last_verdict.get('status','-')},
    confidence={last_verdict.get('confidence','-')},
    announced={last_verdict.get('announced','-')},
    t={last_verdict.get('t','-')}s</span>
  </div>

  <h3>Recent frames (newest first)</h3>
  <table>
    <tr><th>t</th><th>status</th><th>reason</th><th>route</th>
        <th>destination</th><th>conf</th><th>raw OCR text</th></tr>
    {rows}
  </table>
</body>
</html>"""
