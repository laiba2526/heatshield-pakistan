"""HeatShield Pakistan dashboard (Streamlit).

Run locally:   make -C src app        (or: streamlit run app/streamlit_app.py)
Hugging Face:  Docker Space, see Dockerfile / docs/DEPLOYMENT.md

The dashboard only reads the *trusted* Gold layer. A background thread runs
the hourly refresh (fetch -> quality gates -> promote); if a refresh fails
validation, the dashboard keeps showing the last trusted data and says so.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from heatshield import config  # noqa: E402
from heatshield.heat_index import risk_color  # noqa: E402

st.set_page_config(page_title="HeatShield Pakistan", page_icon="🌡️", layout="wide")

# In the static Hugging Face build the app runs inside the browser (Pyodide):
# no background threads or network fetches there - GitHub Actions refreshes the data hourly.
IN_BROWSER = sys.platform == "emscripten"
REFRESH_MINUTES = 0 if IN_BROWSER else int(os.environ.get("HEATSHIELD_REFRESH_MINUTES", "60"))
RISK_NAMES = [n for n, _, _ in config.RISK_LEVELS]
CITY_NAMES = {k: v["name"] for k, v in config.CITIES.items()}


# ============================================================ hourly refresh
@st.cache_resource
def start_scheduler() -> dict:
    """One background refresher per server process (not per browser session)."""
    state = {"started": datetime.now(timezone.utc), "last_result": None, "running": False}
    if REFRESH_MINUTES <= 0:
        state["disabled"] = True
        return state

    def loop():
        from heatshield import pipeline
        time.sleep(5)
        while True:
            status = pipeline.read_status()
            # Time since the last *download*: a `data` run rebuilds without fetching,
            # so it must not postpone the hourly refresh.
            last = (status.get("last_fetch") or {}).get("utc")
            age_min = (datetime.now(timezone.utc) - pd.Timestamp(last).to_pydatetime()).total_seconds() / 60 if last else 1e9
            if age_min >= REFRESH_MINUTES:
                state["running"] = True
                try:
                    rep = pipeline.run("update")
                    state["last_result"] = {"run_id": rep["run_id"], "status": rep["status"], "error": rep.get("error")}
                except Exception as exc:  # noqa: BLE001 - never kill the refresher
                    state["last_result"] = {"status": "error", "error": str(exc)}
                finally:
                    state["running"] = False
            time.sleep(60)

    threading.Thread(target=loop, name="heatshield-refresh", daemon=True).start()
    return state


# ================================================================== loaders
def _mtime(path: Path) -> float:
    return path.stat().st_mtime if path.exists() else 0.0


@st.cache_data(show_spinner=False)
def load_gold(stamp: float) -> dict:
    g = config.GOLD
    read = lambda n, **kw: pd.read_csv(g / n, **kw) if (g / n).exists() else pd.DataFrame()
    out = {
        "daily": read("heat_daily.csv", parse_dates=["date"]),
        "pred": read("predictions.csv", parse_dates=["issue_date", "target_date"]),
        "nwp_daily": read("forecast_daily.csv", parse_dates=["date"]),
        "agreement": read("source_agreement.csv"),
        "nwp_hourly": (pd.read_csv(g / "forecast_hourly.csv") if (g / "forecast_hourly.csv").exists()
                       else pd.read_parquet(g / "forecast_hourly.parquet") if (g / "forecast_hourly.parquet").exists()
                       else pd.DataFrame()),
    }
    return out


@st.cache_data(show_spinner=False)
def load_json(path: str, stamp: float):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@st.cache_data(show_spinner=False)
def load_jsonl_tail(path: str, stamp: float, n: int = 400) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    lines = p.read_text(encoding="utf-8").splitlines()[-n:]
    return pd.DataFrame([json.loads(x) for x in lines if x.strip()])


@st.cache_data(show_spinner=False)
def load_test_predictions(stamp: float) -> pd.DataFrame:
    p = config.REPORTS / "model_test_predictions.csv"
    return pd.read_csv(p, parse_dates=["issue_date", "target_date"]) if p.exists() else pd.DataFrame()


@st.cache_resource(show_spinner="Loading official documents…")
def load_assistant():
    from heatshield.rag.agent import HeatShieldAssistant
    try:
        return HeatShieldAssistant()
    except Exception:  # noqa: BLE001 - documents could not be fetched or indexed
        return None


# ================================================================== helpers
def badge(level: str, big: bool = False) -> str:
    color = risk_color(level)
    fg = "#111" if level in ("Caution",) else "#fff"
    size = "1.05rem" if big else "0.8rem"
    return (f"<span style='background:{color};color:{fg};padding:3px 10px;border-radius:999px;"
            f"font-weight:600;font-size:{size};white-space:nowrap'>{level}</span>")


def ago(iso_ts: str | None) -> str:
    if not iso_ts:
        return "never"
    mins = (datetime.now(timezone.utc) - pd.Timestamp(iso_ts).to_pydatetime()).total_seconds() / 60
    if mins < 90:
        return f"{mins:.0f} min ago"
    if mins < 60 * 48:
        return f"{mins / 60:.1f} h ago"
    return f"{mins / 1440:.1f} days ago"


def pkt(iso_ts: str | None) -> str:
    if not iso_ts:
        return "–"
    return pd.Timestamp(iso_ts).tz_convert(config.LOCAL_TZ).strftime("%d %b %Y, %H:%M PKT")


def add_risk_bands(fig: go.Figure, y_max: float) -> None:
    bounds = [lo for _, lo, _ in config.RISK_LEVELS][1:] + [max(y_max, 60)]
    lower = 0
    for (name, _, color), upper in zip(config.RISK_LEVELS, bounds):
        fig.add_hrect(y0=lower, y1=upper, fillcolor=color, opacity=0.10, line_width=0, layer="below",
                      annotation_text=name, annotation_position="top left", annotation_font_size=10,
                      annotation_font_color=color)
        lower = upper


# ==================================================================== page
scheduler = start_scheduler()
status = load_json(str(config.STATUS / "run_status.json"), _mtime(config.STATUS / "run_status.json")) or {}
gold = load_gold(_mtime(config.GOLD / "heat_daily.csv") + _mtime(config.GOLD / "predictions.csv"))
daily, pred, nwp_daily, nwp_hourly = gold["daily"], gold["pred"], gold["nwp_daily"], gold["nwp_hourly"]

st.title("🌡️ HeatShield Pakistan")
st.caption("Heat-stress early warning for Karachi, Lahore and Jacobabad · daily maximum heat index (NWS) · "
           "not an official warning — always follow PMD / NDMA / PDMA advisories.")

if daily.empty:
    st.error("No trusted Gold data yet. Run `make -C src data` (or wait for the first refresh).")
    st.stop()

# ----------------------------------------------------------- status strip
last_ok = status.get("last_run_status") == "success"
fresh = status.get("freshness", {})
obs_age = max((v.get("observation_age_hours") or 0) for v in fresh.values()) if fresh else None
fc_issued = max((v.get("forecast_issued_utc") or "") for v in fresh.values()) if fresh else None
stale = any(v.get("observations_stale") or v.get("forecast_stale") for v in fresh.values()) if fresh else True

c1, c2, c3, c4 = st.columns(4)
c1.metric("Quality status", "PASSED" if last_ok else "FAILED",
          "both quality gates passed" if last_ok else "serving last trusted data", delta_color="normal" if last_ok else "inverse")
c2.metric("Data freshness", "Stale" if stale else "Fresh",
          f"latest obs {ago(max(v['last_observation_utc'] for v in fresh.values() if v.get('last_observation_utc')))}"
          if fresh else "unknown", delta_color="inverse" if stale else "normal")
c3.metric("Last successful run", ago(status.get("last_success_utc")), pkt(status.get("last_success_utc")), delta_color="off")
c4.metric("Last run attempt", (status.get("last_run_status") or "–").replace("_", " "),
          f"{status.get('last_run_mode', '')} · {ago(status.get('last_run_utc'))}", delta_color="off")
if not last_ok and status.get("last_run_status"):
    st.error(f"The latest refresh ({status.get('last_run_id')}) did not pass validation: **{status.get('last_run_error')}**. "
             f"The dashboard is showing the last trusted dataset from run **{status.get('last_success_run_id')}**.")
elif stale:
    fetch = status.get("last_fetch") or {}
    why = (f"the last download had {len(fetch['failed'])} failure(s) - Open-Meteo may be unreachable"
           if fetch.get("failed") else
           f"the last download was {ago(fetch.get('utc'))}" if fetch.get("utc") else "no download has run yet")
    st.warning("Data is older than the freshness target (observations > "
               f"{config.FRESHNESS_STALE_HOURS} h or forecast > {config.FRESHNESS_FORECAST_STALE_HOURS} h): {why}. "
               + ("It refreshes when the hourly GitHub job publishes new data." if IN_BROWSER else
                  "Run `python run.py update` to download fresh data now."))

city = st.segmented_control("City", options=list(CITY_NAMES), format_func=CITY_NAMES.get,
                            default="jacobabad", label_visibility="collapsed") or "jacobabad"

tabs = st.tabs(["🔥 Forecast & risk", "📈 History", "🎯 Model evaluation", "🛡️ Data quality", "💬 Ask HeatShield", "ℹ️ About & sources"])

# =============================================================== forecast
with tabs[0]:
    cp = pred[pred["city"] == city].sort_values("target_date")
    cn = nwp_daily[nwp_daily["city"] == city].set_index("date") if len(nwp_daily) else pd.DataFrame()
    st.subheader(f"{CITY_NAMES[city]} — next days")
    if cp.empty:
        st.info("No model forecast available (train the model with `make -C src train`).")
    cols = st.columns(max(1, len(cp)))
    for col, (_, r) in zip(cols, cp.iterrows()):
        nwp_txt = ""
        if len(cn) and r["target_date"] in cn.index and pd.notna(cn.loc[r["target_date"], "hi_max_c"]):
            nwp_txt = f"<br><span style='opacity:.75'>Open-Meteo NWP: {cn.loc[r['target_date'], 'hi_max_c']:.1f} °C</span>"
        upper = "" if r["upper90_risk_level"] == r["predicted_risk_level"] else \
            f"<br><span style='opacity:.75'>could reach {badge(r['upper90_risk_level'])}</span>"
        col.markdown(
            f"<div style='border:1px solid rgba(128,128,128,.35);border-radius:12px;padding:14px'>"
            f"<div style='opacity:.7'>{r['target_date']:%a %d %b} · {int(r['horizon'])}-day lead</div>"
            f"<div style='font-size:2rem;font-weight:700'>{r['pred']:.1f} °C</div>"
            f"<div style='opacity:.75'>90 % range {r['lo90']:.1f}–{r['hi90']:.1f} °C</div>"
            f"<div style='margin-top:6px'>{badge(r['predicted_risk_level'], True)}</div>{upper}{nwp_txt}"
            f"<div style='opacity:.5;font-size:.7rem;margin-top:6px'>row {r['row_id']}</div></div>",
            unsafe_allow_html=True)
    st.caption("Max heat index for the local (PKT) day. The model is issued from the latest complete observed day "
               f"(**{cp['issue_date'].max():%d %b %Y}**)." if len(cp) else "")

    left, right = st.columns([3, 2])
    with left:
        st.markdown("**Hourly heat index — Open-Meteo forecast**")
        h = nwp_hourly[nwp_hourly["city"] == city].copy() if len(nwp_hourly) else pd.DataFrame()
        if len(h):
            h["local_time"] = pd.to_datetime(h["timestamp_utc"]).dt.tz_convert(config.LOCAL_TZ)
            fig = go.Figure()
            add_risk_bands(fig, float(h["heat_index_c"].max()) + 3)
            fig.add_scatter(x=h["local_time"], y=h["temperature_c"], name="Air temperature", line=dict(color="#888", dash="dot"))
            fig.add_scatter(x=h["local_time"], y=h["heat_index_c"], name="Heat index", line=dict(color="#d7263d", width=3))
            fig.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10), yaxis_title="°C",
                              yaxis_range=[max(0, h["temperature_c"].min() - 5), h["heat_index_c"].max() + 4],
                              legend=dict(orientation="h", y=-0.15))
            st.plotly_chart(fig, width="stretch")
            issued = h["issued_utc"].iloc[0] if "issued_utc" in h else None
            st.caption(f"Forecast issued {pkt(pd.to_datetime(issued, format='%Y%m%dT%H%M%SZ', utc=True).isoformat()) if issued else '–'}. "
                       "Weather data by [Open-Meteo.com](https://open-meteo.com/) (CC BY 4.0).")
    with right:
        st.markdown("**Last 21 days + forecast**")
        d = daily[(daily["city"] == city)].sort_values("date").tail(21)
        fig = go.Figure()
        add_risk_bands(fig, float(pd.concat([d["hi_max_c"], cp["hi90"]]).max()) + 3)
        fig.add_scatter(x=d["date"], y=d["hi_max_c"], mode="lines+markers", name="Observed", line=dict(color="#333"))
        if len(cp):
            fig.add_scatter(x=cp["target_date"], y=cp["pred"], mode="markers", name="Model (90 % range)",
                            marker=dict(size=10, color="#d7263d"),
                            error_y=dict(type="data", symmetric=False, array=cp["hi90"] - cp["pred"],
                                         arrayminus=cp["pred"] - cp["lo90"]))
        fig.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10), yaxis_title="Max heat index °C",
                          legend=dict(orientation="h", y=-0.15))
        st.plotly_chart(fig, width="stretch")

    st.markdown("**All cities**")
    rows = []
    for c in config.CITIES:
        pc = pred[(pred["city"] == c)].sort_values("target_date")
        last = daily[(daily["city"] == c) & daily["complete_day"]].sort_values("date").tail(1)
        rows.append({"City": CITY_NAMES[c],
                     "Last observed day": f"{last['date'].iloc[0]:%d %b}: {last['hi_max_c'].iloc[0]:.1f} °C" if len(last) else "–",
                     **{f"{r['target_date']:%a %d %b}": f"{r['pred']:.1f} °C · {r['predicted_risk_level']}" for _, r in pc.iterrows()},
                     "Obs. updated": ago(fresh.get(c, {}).get("last_observation_utc"))})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

# ================================================================ history
with tabs[1]:
    d = daily[daily["city"] == city].sort_values("date")
    lo, hi = d["date"].min().date(), d["date"].max().date()
    rng = st.slider("Period", min_value=lo, max_value=hi, value=(max(lo, hi.replace(year=hi.year - 1)), hi), format="MMM YYYY")
    dd = d[(d["date"].dt.date >= rng[0]) & (d["date"].dt.date <= rng[1])]
    fig = go.Figure()
    add_risk_bands(fig, float(dd["hi_max_c"].max()) + 3)
    fig.add_scatter(x=dd["date"], y=dd["tmax_c"], name="Max temperature", line=dict(color="#999", width=1))
    fig.add_scatter(x=dd["date"], y=dd["hi_max_c"], name="Max heat index", line=dict(color="#d7263d", width=2))
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10), yaxis_title="°C", legend=dict(orientation="h", y=-0.12))
    st.plotly_chart(fig, width="stretch")
    yearly = d[d["complete_day"]].assign(year=d["date"].dt.year)
    counts = yearly.groupby(["year", "risk_level"]).size().unstack(fill_value=0).reindex(columns=RISK_NAMES, fill_value=0)
    fig = go.Figure()
    for name in RISK_NAMES[2:]:
        fig.add_bar(x=counts.index.astype(str), y=counts[name], name=name, marker_color=risk_color(name))
    fig.update_layout(barmode="stack", height=300, margin=dict(l=10, r=10, t=30, b=10),
                      title="Days per year at Extreme Caution or worse (partial years at the ends)")
    st.plotly_chart(fig, width="stretch")
    with st.expander("Gold rows (heat_daily)"):
        st.dataframe(dd.sort_values("date", ascending=False), hide_index=True, width="stretch")

# ============================================================== evaluation
with tabs[2]:
    ev = load_json(str(config.REPORTS / "model_evaluation.json"), _mtime(config.REPORTS / "model_evaluation.json"))
    if not ev:
        st.info("Run `make -C src evaluate` to produce the evaluation report.")
    else:
        st.markdown(f"Unseen test period **{ev['test_period']['from']} → {ev['test_period']['to']}** — never used for "
                    "training, climatology, model selection or interval calibration.")
        rows, fig = [], go.Figure()
        labels = {"model": "HeatShield model", "persistence": "Persistence", "climatology": "Historical average"}
        colors = {"model": "#d7263d", "persistence": "#4c78a8", "climatology": "#9d9d9d"}
        for m in labels:
            hs = list(ev["horizons"])
            mae = [ev["horizons"][h]["overall"][m]["mae"] for h in hs]
            ci = [ev["horizons"][h]["overall"]["bootstrap_95ci_mae"][m] for h in hs]
            fig.add_bar(x=[f"{h} day" for h in hs], y=mae, name=labels[m], marker_color=colors[m],
                        error_y=dict(type="data", symmetric=False, array=[c[1] - v for c, v in zip(ci, mae)],
                                     arrayminus=[v - c[0] for c, v in zip(ci, mae)]))
        fig.update_layout(barmode="group", height=340, yaxis_title="MAE (°C) · 95 % CI",
                          margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=-0.15))
        st.plotly_chart(fig, width="stretch")
        for h, hr in ev["horizons"].items():
            o = hr["overall"]
            rows.append({"Horizon": f"{h} day", "Model MAE": round(o["model"]["mae"], 2),
                         "Persistence MAE": round(o["persistence"]["mae"], 2), "Hist. avg MAE": round(o["climatology"]["mae"], 2),
                         "Skill vs persistence": f"{o['skill_vs_persistence']:+.1%}", "Skill vs hist. avg": f"{o['skill_vs_climatology']:+.1%}",
                         "Model − best baseline (95 % CI)": "[{:+.2f}, {:+.2f}]".format(*o["bootstrap_95ci_mae"]["model_minus_best_baseline"]),
                         "RMSE": round(o["model"]["rmse"], 2), "Bias": round(o["model"]["bias"], 2),
                         "80 % interval coverage": f"{o['interval_80']['empirical_coverage']:.1%}",
                         "90 % interval coverage": f"{o['interval_90']['empirical_coverage']:.1%}",
                         "Danger POD / FAR": f"{o['model']['danger']['pod'] or 0:.2f} / {o['model']['danger']['far'] or 0:.2f}"})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption("A negative upper bound on *Model − best baseline* means the model beats both baselines with 95 % confidence. "
                   "Intervals: split-conformal, calibrated on the year before the test period.")
        tp = load_test_predictions(_mtime(config.REPORTS / "model_test_predictions.csv"))
        if len(tp):
            hsel = st.radio("Horizon", [1, 2, 3], horizontal=True, format_func=lambda x: f"{x}-day")
            t = tp[(tp["city"] == city) & (tp["horizon"] == hsel)].sort_values("target_date")
            fig = go.Figure()
            fig.add_scatter(x=t["target_date"], y=t["hi90"], line=dict(width=0), showlegend=False, hoverinfo="skip")
            fig.add_scatter(x=t["target_date"], y=t["lo90"], fill="tonexty", line=dict(width=0),
                            fillcolor="rgba(215,38,61,.15)", name="90 % interval")
            fig.add_scatter(x=t["target_date"], y=t["y"], name="Actual", line=dict(color="#222"))
            fig.add_scatter(x=t["target_date"], y=t["model"], name="Model", line=dict(color="#d7263d"))
            fig.add_scatter(x=t["target_date"], y=t["persistence"], name="Persistence", line=dict(color="#4c78a8", dash="dot"))
            fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10), yaxis_title="Max heat index °C",
                              title=f"{CITY_NAMES[city]} — test period, {hsel}-day ahead", legend=dict(orientation="h", y=-0.15))
            st.plotly_chart(fig, width="stretch")
        md = config.REPORTS / "model_evaluation.md"
        if md.exists():
            with st.expander("Full evaluation report"):
                st.markdown(md.read_text(encoding="utf-8"))

# ============================================================ data quality
with tabs[3]:
    runs = load_jsonl_tail(str(config.STATUS / "run_history.jsonl"), _mtime(config.STATUS / "run_history.jsonl"), 200)
    vdir = config.REPORTS / "validation"
    latest = sorted(vdir.glob("validation_*.json"))[-1] if vdir.exists() and any(vdir.glob("validation_*.json")) else None
    rep = load_json(str(latest), _mtime(latest)) if latest else None
    a, b = st.columns(2)
    for col, gate, title in ((a, "gate1", "Gate 1 — Bronze files"), (b, "gate2", "Gate 2 — publish")):
        with col:
            g = (rep or {}).get(gate)
            if not g:
                st.info(f"{title}: not reached in the latest run")
                continue
            st.markdown(f"**{title}: {'✅ PASS' if g['passed'] else '❌ FAIL'}**  ·  run `{rep['run_id']}`")
            st.dataframe(pd.DataFrame([{"": "✅" if c["passed"] else ("⚠️" if c["severity"] == "warning" else "❌"),
                                        "check": c["check"], "detail": c.get("detail", "")} for c in g["checks"]]),
                         hide_index=True, width="stretch", height=280)
    st.markdown("**Data Quality Agent — actions in the latest run**")
    acts = (rep or {}).get("agent_actions", {})
    st.dataframe(pd.DataFrame([{"rule": k, "records": v} for k, v in acts.items()]) if acts else
                 pd.DataFrame([{"rule": "no actions needed", "records": 0}]), hide_index=True)
    if len(runs):
        st.markdown("**Run history**")
        r = runs.sort_values("finished_utc", ascending=False).head(48)
        r = r.assign(note=r["note"].fillna("") if "note" in r else "")
        st.dataframe(r[["run_id", "mode", "note", "status", "gate1", "gate2", "duration_s", "error"]], hide_index=True,
                     width="stretch")
        if r["note"].str.startswith("fault drill").any():
            st.caption("Runs labelled *fault drill* failed on purpose: bad data was fed in to prove that the quality "
                       "gates stop it and the trusted data stays unchanged (`python run.py drill`).")
    audit = load_jsonl_tail(str(config.AUDIT / "audit_log.jsonl"), _mtime(config.AUDIT / "audit_log.jsonl"), 300)
    if len(audit):
        with st.expander("Audit log (latest entries)"):
            cols = [c for c in ["ts_utc", "run_id", "stage", "rule", "action", "city", "count", "reason"] if c in audit]
            st.dataframe(audit[cols].iloc[::-1], hide_index=True, width="stretch")
    if len(gold["agreement"]):
        st.markdown("**Cross-source agreement of daily Tmax** (primary Open-Meteo vs independent references)")
        st.dataframe(gold["agreement"], hide_index=True)
    comp = daily.groupby("city").agg(days=("row_id", "size"), complete_days=("complete_day", "sum"),
                                     days_with_filled_hours=("filled_hours", lambda s: int((s > 0).sum())))
    st.markdown("**Gold coverage**")
    st.dataframe(comp, width="stretch")
    if IN_BROWSER:
        st.caption("Static build: the data pipeline and both quality gates run hourly in GitHub Actions; "
                   "this page shows the last trusted result they published.")
    elif not scheduler.get("disabled"):
        st.caption(f"Automatic refresh every {REFRESH_MINUTES} min in this server process"
                   f"{' — running now…' if scheduler.get('running') else ''}.")

# ==================================================================== RAG
with tabs[4]:
    st.markdown("Ask about heat safety (answers come **only** from official NDMA / PDMA Sindh / PMD documents) "
                "or about the data (e.g. *heat risk in Lahore tomorrow*). Every answer is cited; if the documents "
                "do not cover a question, HeatShield says **I don't know**.")
    examples = ["What should I do if I feel dizzy in the heat?", f"What is the heat risk in {CITY_NAMES[city]} tomorrow?",
                "What should employers do to protect outdoor workers?", "What is the population of Lahore?"]
    ex_cols = st.columns(len(examples))
    clicked = None
    for col, ex in zip(ex_cols, examples):
        if col.button(ex, width="stretch"):
            clicked = ex
    if "chat" not in st.session_state:
        st.session_state.chat = []
    q = st.chat_input("Ask HeatShield…") or clicked
    assistant = load_assistant()
    if assistant is None:
        st.error("The official documents could not be loaded (the publishers' websites may be unreachable). "
                 "Data questions and the rest of the dashboard still work; try again later.")
    elif q:
        with st.spinner("Searching official documents…"):
            ans = assistant.ask(q)
        st.session_state.chat.append(ans)
    for ans in reversed(st.session_state.chat[-8:]):
        with st.chat_message("user"):
            st.write(ans.question)
        with st.chat_message("assistant", avatar="🌡️"):
            st.markdown(ans.text)
            if ans.citations:
                with st.expander(f"Sources ({len(ans.citations)})"):
                    for c in ans.citations:
                        if c["type"] == "document":
                            sec = f" — {c['section']}" if c["section"] else ""
                            st.markdown(f"**[{c['n']}]** {c['title']}, page {c['page']}{sec} · {c['publisher']} · [source PDF]({c['url']})")
                        else:
                            st.markdown(f"**[{c['n']}]** Gold row `{c['row_id']}` in `{c['table']}`")
    st.caption("Answers quote the official documents verbatim (no language model). Evaluation: reports/rag_evaluation.md")

# ================================================================== about
with tabs[5]:
    st.markdown("""
**What the numbers mean.** The *heat index* combines air temperature and humidity into a "feels-like" temperature
(US National Weather Service formula, with the official low/high-humidity adjustments). Risk levels follow the NWS
categories: Caution ≥ 26.7 °C, Extreme Caution ≥ 32.2 °C, Danger ≥ 39.4 °C, Extreme Danger ≥ 51.7 °C.
It assumes shade and light wind — in direct sun it can feel up to ~8 °C hotter.

**How it works.** Raw files (Bronze) pass *Quality Gate 1* (manifest hash, schema, units, timestamps); the *Data
Quality Agent* fixes, fills, flags or quarantines records (Silver); daily heat-stress tables are built (Gold) and
must pass *Quality Gate 2* before they replace the trusted data. The model forecasts the daily maximum heat index
1–3 days ahead and is evaluated against persistence and historical-average baselines on an unseen year.

**Data sources & attribution**
* Weather data by [Open-Meteo.com](https://open-meteo.com/) — CC BY 4.0 (forecast and historical APIs). Zippenfenig, P. (2023), doi:10.5281/zenodo.7970649.
* Contains modified Copernicus Climate Change Service information 2026 (ERA5, Hersbach et al. 2023, doi:10.24381/cds.adbb2d47), via Open-Meteo. Neither the European Commission nor ECMWF is responsible for any use that may be made of the Copernicus information or data it contains.
* The data was obtained from the NASA Langley Research Center POWER Project funded through the NASA Earth Science Division (hourly API, accessed Oct 2026).
* Heat-safety guidance: NDMA Heatwave Advisory (25 Apr 2025), PDMA Sindh Heatwave Alert incl. PMD Heatwave-Alert (15 May 2025), PDMA Sindh *SOPs Heatwave Management*. © the respective publishers; quoted for public-safety information with citation, PDFs fetched from the publishers' websites.

**Disclaimer.** HeatShield is a student prototype. It is not an official forecast or warning service.
""")
