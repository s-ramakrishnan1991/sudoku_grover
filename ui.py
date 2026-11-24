"""Look and feel of the in-circuit Grover app: SVG puzzle board, CSS, charts."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

TEAL, CORAL, AMBER, INK, SAND = "#0e7c86", "#e4572e", "#d9a21b", "#1c2b30", "#ebe4d3"
FAMILY_COLOR = {"IBM": "#3b6fd4", "IQM": "#c2417a", "Google": "#d9a21b", "IonQ": "#7b4fc4", "Quantinuum": "#0e7c86",
                "Reference": "#7a8a8f", "Real hardware": "#e4572e"}

CSS = """
<style>
  .block-container {padding-top: 2.2rem; max-width: 1180px;}
  h1, h2, h3 {letter-spacing: -0.02em;}
  .hero {border: 2px solid currentColor; padding: 1.1rem 1.4rem; margin-bottom: 1.2rem;
         display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: .6rem;}
  .hero .t {font-size: 1.9rem; font-weight: 800; line-height: 1.1;}
  .hero .s {opacity: .75; font-size: .92rem;}
  .tag {display: inline-block; border: 1.5px solid currentColor; padding: 0 .5rem; margin-right: .35rem;
        font-size: .78rem; font-weight: 700; letter-spacing: .04em; text-transform: uppercase;}
  .tag.good {color: #1d8f5c;} .tag.bad {color: #e4572e;} .tag.warn {color: #b8860b;}
  .card {border: 1.5px solid rgba(128,128,128,.45); padding: .8rem 1rem; height: 100%;}
  .card .k {font-size: .72rem; letter-spacing: .08em; text-transform: uppercase; opacity: .7;}
  .card .v {font-size: 1.7rem; font-weight: 800; line-height: 1.15;}
  .card .n {font-size: .8rem; opacity: .7;}
  .flow {display: flex; flex-wrap: wrap; gap: .35rem; align-items: stretch; margin: .5rem 0 1rem;}
  .flow div {border: 1.5px solid currentColor; padding: .35rem .7rem; font-size: .85rem;}
  .flow .arr {border: none; padding: .35rem .1rem; opacity: .6;}
  .flow .hot {background: #0e7c86; color: #fff; border-color: #0e7c86;}
  .rank {display: grid; grid-template-columns: 2rem 1fr auto; gap: .6rem; align-items: center;
         border-bottom: 1px dashed rgba(128,128,128,.4); padding: .45rem 0;}
  .rank .no {font-weight: 800; opacity: .6;}
  .rank .bar {height: .55rem; background: rgba(128,128,128,.25); position: relative; margin-top: .25rem;}
  .rank .bar i {position: absolute; left: 0; top: 0; bottom: 0;}
  .rank .nm {font-weight: 700;} .rank .sub {font-size: .76rem; opacity: .7;}
  .rank .pct {font-size: 1.25rem; font-weight: 800;}
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def hero(title: str, sub: str):
    st.markdown(f'<div class="hero"><span class="t">{title}</span><span class="s">{sub}</span></div>',
                unsafe_allow_html=True)


def stat(label: str, value: str, note: str = ""):
    st.markdown(f'<div class="card"><div class="k">{label}</div><div class="v">{value}</div>'
                f'<div class="n">{note}</div></div>', unsafe_allow_html=True)


def board_svg(fixed: dict, rows=None, status: str = "ok", size: int = 270) -> str:
    """3x3 board as SVG tokens. Clues are solid dark discs; decoded cells are rings (teal valid / coral invalid)."""
    ring = TEAL if status == "ok" else CORAL
    cell = size / 3
    out = [f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg" '
           f'role="img" aria-label="3 by 3 puzzle board">']
    out.append(f'<rect x="1" y="1" width="{size-2}" height="{size-2}" fill="none" stroke="currentColor" '
               f'stroke-width="3" opacity=".85"/>')
    for k in (1, 2):
        out.append(f'<line x1="{k*cell}" y1="6" x2="{k*cell}" y2="{size-6}" stroke="currentColor" opacity=".25"/>')
        out.append(f'<line x1="6" y1="{k*cell}" x2="{size-6}" y2="{k*cell}" stroke="currentColor" opacity=".25"/>')
    for r in range(3):
        for c in range(3):
            cx, cy = c * cell + cell / 2, r * cell + cell / 2
            if (r, c) in fixed:
                out.append(f'<circle cx="{cx}" cy="{cy}" r="{cell*.36}" fill="{INK}"/>')
                out.append(f'<text x="{cx}" y="{cy+cell*.13}" text-anchor="middle" font-size="{cell*.38}" '
                           f'font-weight="800" fill="#f6f2e9" font-family="monospace">{fixed[(r, c)]}</text>')
            elif rows is not None and rows[r][c] is not None:
                out.append(f'<circle cx="{cx}" cy="{cy}" r="{cell*.34}" fill="none" stroke="{ring}" stroke-width="5"/>')
                out.append(f'<text x="{cx}" y="{cy+cell*.13}" text-anchor="middle" font-size="{cell*.36}" '
                           f'font-weight="800" fill="{ring}" font-family="monospace">{rows[r][c]}</text>')
            else:
                out.append(f'<circle cx="{cx}" cy="{cy}" r="4" fill="currentColor" opacity=".35"/>')
    out.append("</svg>")
    return "".join(out)


def show_board(fixed, rows=None, status="ok", size=270):
    st.markdown(f'<div style="display:flex;justify-content:center">{board_svg(fixed, rows, status, size)}</div>',
                unsafe_allow_html=True)


def ranking_html(records: list[dict]) -> str:
    """Leaderboard rows: rank, name, bar, success."""
    rows = []
    for i, r in enumerate(records, 1):
        pct = r["success"] * 100
        col = FAMILY_COLOR.get(r["family"], TEAL)
        valid = '<span class="tag good">valid</span>' if r["best_valid"] else '<span class="tag bad">wrong grid</span>'
        rows.append(
            f'<div class="rank"><div class="no">{i:02d}</div><div><div class="nm">{r["name"]} {valid}</div>'
            f'<div class="sub">{r["note"]}</div><div class="bar"><i style="width:{pct:.1f}%;background:{col}"></i></div></div>'
            f'<div class="pct">{pct:.0f}%</div></div>')
    return "".join(rows)


def dot_plot(df: pd.DataFrame, baseline: float):
    """Cleveland dot plot of success per backend with the random-guess baseline."""
    order = df.sort_values("success", ascending=False)["name"].tolist()
    base = alt.Chart(pd.DataFrame({"x": [baseline]})).mark_rule(strokeDash=[5, 4], color=CORAL, size=2).encode(x="x:Q")
    pts = alt.Chart(df).mark_circle(size=330, opacity=1).encode(
        x=alt.X("success:Q", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%", title="Success probability")),
        y=alt.Y("name:N", sort=order, title=None),
        color=alt.Color("family:N", legend=alt.Legend(title=None, orient="bottom"),
                        scale=alt.Scale(domain=list(FAMILY_COLOR), range=list(FAMILY_COLOR.values()))),
        tooltip=["name", alt.Tooltip("success:Q", format=".1%"), "two_q", "seconds"])
    stem = alt.Chart(df).mark_rule(size=2, opacity=.5).encode(
        x=alt.value(0), x2="success:Q", y=alt.Y("name:N", sort=order),
        color=alt.Color("family:N", legend=None,
                        scale=alt.Scale(domain=list(FAMILY_COLOR), range=list(FAMILY_COLOR.values()))))
    return (stem + pts + base).properties(height=34 * len(df) + 60)


def cost_scatter(df: pd.DataFrame):
    """Two-qubit gates versus success: how circuit size is paid for in noise."""
    pts = alt.Chart(df).mark_point(filled=True, size=160, opacity=.95).encode(
        x=alt.X("two_q:Q", title="Two-qubit gates after transpiling"),
        y=alt.Y("success:Q", axis=alt.Axis(format="%"), title="Success probability", scale=alt.Scale(domain=[0, 1])),
        color=alt.Color("family:N", legend=None,
                        scale=alt.Scale(domain=list(FAMILY_COLOR), range=list(FAMILY_COLOR.values()))),
        tooltip=["name", alt.Tooltip("success:Q", format=".1%"), "two_q"])
    lab = alt.Chart(df).mark_text(dx=9, align="left", fontSize=11).encode(
        x="two_q:Q", y="success:Q", text="name:N")
    return (pts + lab).properties(height=320)


def outcomes_chart(rows: list[dict]):
    """Top measured outcomes as ranked horizontal lollipops (valid grids in teal, others in coral)."""
    df = pd.DataFrame(rows)
    order = df["label"].tolist()
    stem = alt.Chart(df).mark_rule(size=3).encode(
        y=alt.Y("label:N", sort=order, title=None), x=alt.value(0), x2="share:Q",
        color=alt.Color("valid:N", legend=None, scale=alt.Scale(domain=[True, False], range=[TEAL, CORAL])))
    head = alt.Chart(df).mark_circle(size=200).encode(
        y=alt.Y("label:N", sort=order), x=alt.X("share:Q", axis=alt.Axis(format="%", title="Share of shots")),
        color=alt.Color("valid:N", title="valid grid", scale=alt.Scale(domain=[True, False], range=[TEAL, CORAL])),
        tooltip=["label", alt.Tooltip("share:Q", format=".1%"), "valid"])
    return (stem + head).properties(height=30 * len(df) + 50)
