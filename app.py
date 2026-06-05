import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import io
import math
from datetime import datetime

from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors as rl_colors
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                 Paragraph, Spacer, HRFlowable)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT

st.set_page_config(
    page_title="AVIP – Athlete Value Intelligence Platform",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  .main .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
  .tier-elite  { background:#d1fae5;color:#065f46;padding:4px 12px;border-radius:99px;font-weight:600;font-size:13px; }
  .tier-high   { background:#dbeafe;color:#1e40af;padding:4px 12px;border-radius:99px;font-weight:600;font-size:13px; }
  .tier-dev    { background:#fef3c7;color:#92400e;padding:4px 12px;border-radius:99px;font-weight:600;font-size:13px; }
  .tier-entry  { background:#fee2e2;color:#991b1b;padding:4px 12px;border-radius:99px;font-weight:600;font-size:13px; }
  .bluechip    { background:#f3e8ff;color:#6b21a8;padding:4px 12px;border-radius:99px;font-weight:600;font-size:13px; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# LOOKUP MAPS
# ─────────────────────────────────────────────────────────────────────────────
CONF_TIER_MAP  = {"Power 4": 1, "Mid-Major": 2, "D-II / D-III / NAIA": 3}
AWARD_MAP      = {"None": 0, "Team Award": 1, "Conference Award": 2, "All-American / National": 3}
SIZE_MAP       = {"20,000+": 3, "8,000–20,000": 2, "Under 8,000": 1}
TV_MAP         = {"National (ESPN, Fox)": 3, "Regional network": 2, "Streaming / local only": 1}
MKT_MAP        = {"Top-25 DMA": 3, "Mid-size market": 2, "Small market": 1}
TRANSFER_MAP   = {"Low — committed": 0, "Medium": 1, "High — exploring portal": 2}
DRAFT_MAP      = {"0 — Not projected": 0, "3 — 2nd round proj.": 3, "2 — Late 1st rd (15-30)": 2, "1 — Lottery pick (1-14)": 1}
RECRUIT_MAP    = {"Unranked": 0, "Top 300": 250, "Top 100": 75, "Top 30": 20, "Top 10": 5}

# ─────────────────────────────────────────────────────────────────────────────
# SCORING ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def athletic_score(games, starts, stars, awards_val, conf_val):
    sc = 0
    if games > 0:
        sc += min((starts / games) * 30, 30)
    sc += min((int(stars) - 1) * 10, 40)
    sc += [0, 8, 16, 26][min(int(awards_val), 3)]
    sc += [10, 5, 2][min(int(conf_val) - 1, 2)]
    return round(min(max(sc, 0), 100))

def social_score(ig, tt, xf, eng_pct):
    total = ig + tt + xf
    if total == 0:
        return 0
    eff = total * (eng_pct / 100 + 1)
    raw = math.log10(max(eff, 1)) / 7 * 100
    return round(min(max(raw, 0), 100))

def market_score(size_val, tv_val, mkt_val):
    raw = ((size_val - 1) + (tv_val - 1) + (mkt_val - 1)) / 6 * 100
    return round(min(max(raw + 5, 0), 100))

def retention_risk(transfer_val, draft_val):
    raw = (transfer_val + draft_val) / 4 * 100
    return round(min(max(raw, 0), 100))

def overall_score(ath, soc, mkt, risk):
    return round(ath * 0.35 + soc * 0.30 + mkt * 0.25 + (100 - risk) * 0.10)

def nil_range(ath, soc, mkt, risk, recruit_rank=0, draft_round=0):
    """
    recruit_rank: national ranking number (5 = top 5, 0 = unranked)
    draft_round:  1=Lottery, 2=Late 1st, 3=2nd round, 0=undrafted
    """
    base = (ath * 0.35 + soc * 0.30 + mkt * 0.25) * (1 - risk / 200)

    # Base NIL — calibrated so avg D1 starter = $10–50k
    lo = max(1000, round((math.exp(base / 22) - 1) * 600 / 1000) * 1000)

    # Blue Chip recruiting multiplier
    if 1 <= recruit_rank <= 10:    recruit_mult = 25.0
    elif recruit_rank <= 30:        recruit_mult = 14.0
    elif recruit_rank <= 100:       recruit_mult = 5.0
    elif recruit_rank <= 300:       recruit_mult = 2.0
    else:                           recruit_mult = 1.0

    # Draft projection multiplier
    if draft_round == 1:            draft_mult = 18.0
    elif draft_round == 2:          draft_mult = 8.0
    elif draft_round == 3:          draft_mult = 3.0
    else:                           draft_mult = 1.0

    primary   = max(recruit_mult, draft_mult)
    secondary = min(recruit_mult, draft_mult)
    combined  = 1 + (primary - 1) + (secondary - 1) * 0.35

    lo = round(lo * combined / 1000) * 1000
    hi = round(lo * 1.75 / 1000) * 1000
    return lo, hi

def tier_label(score, recruit_rank=0, draft_round=0):
    if (recruit_rank > 0 and recruit_rank <= 30) or draft_round == 1:
        return "Blue Chip"
    if score >= 80: return "Elite"
    if score >= 60: return "High Value"
    if score >= 40: return "Developing"
    return "Entry Level"

def score_row(player: dict) -> dict:
    ath  = athletic_score(player.get("games",10), player.get("starts",8),
                          player.get("stars",3), player.get("awards_val",0),
                          player.get("conf_val",1))
    soc  = social_score(player.get("ig",0), player.get("tt",0),
                        player.get("xf",0), player.get("eng",2.0))
    mkt  = market_score(player.get("mSize",2), player.get("mTV",2), player.get("mMkt",2))
    risk = retention_risk(player.get("rTransfer",0), player.get("rDraft",0))
    ovr  = overall_score(ath, soc, mkt, risk)
    rrank  = player.get("recruit_rank", 0)
    dround = player.get("draft_round", 0)
    lo, hi = nil_range(ath, soc, mkt, risk, rrank, dround)
    t = tier_label(ovr, rrank, dround)
    return {**player, "ath":ath, "soc":soc, "mkt":mkt, "risk":risk,
            "overall":ovr, "nil_lo":lo, "nil_hi":hi, "tier":t}

# ─────────────────────────────────────────────────────────────────────────────
# PDF EXPORT
# ─────────────────────────────────────────────────────────────────────────────

def build_pdf(p: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=0.75*inch, rightMargin=0.75*inch,
                            topMargin=0.75*inch, bottomMargin=0.75*inch)
    styles = getSampleStyleSheet()
    W = letter[0] - 1.5*inch
    BLUE  = rl_colors.HexColor("#185FA5")
    LBLUE = rl_colors.HexColor("#E6F1FB")
    LGRAY = rl_colors.HexColor("#F1EFE8")
    DARK  = rl_colors.HexColor("#1a1a1a")
    MID   = rl_colors.HexColor("#555555")
    PURP  = rl_colors.HexColor("#6b21a8")

    h1   = ParagraphStyle("h1",  parent=styles["Normal"], fontSize=20, fontName="Helvetica-Bold", textColor=DARK, spaceAfter=2)
    h2   = ParagraphStyle("h2",  parent=styles["Normal"], fontSize=13, fontName="Helvetica-Bold", textColor=BLUE, spaceBefore=12, spaceAfter=4)
    sub  = ParagraphStyle("sub", parent=styles["Normal"], fontSize=10, textColor=MID, spaceAfter=6)
    body = ParagraphStyle("body",parent=styles["Normal"], fontSize=9,  textColor=DARK, leading=14, spaceAfter=4)
    foot = ParagraphStyle("foot",parent=styles["Normal"], fontSize=8,  textColor=MID, alignment=TA_CENTER)

    story = []

    banner_data = [[Paragraph(
        f'<font color="white" size="14"><b>AVIP — Athlete Value Intelligence Report</b></font><br/>'
        f'<font color="#B5D4F4" size="8">Generated {datetime.now().strftime("%B %d, %Y")}  ·  Confidential</font>',
        ParagraphStyle("banner", fontSize=14, fontName="Helvetica-Bold",
                       textColor=rl_colors.white, alignment=TA_LEFT)
    )]]
    banner = Table(banner_data, colWidths=[W])
    banner.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),BLUE),
        ("TOPPADDING",(0,0),(-1,-1),12),("BOTTOMPADDING",(0,0),(-1,-1),12),
        ("LEFTPADDING",(0,0),(-1,-1),16),
    ]))
    story.append(banner)
    story.append(Spacer(1, 12))

    story.append(Paragraph(p.get("name","Athlete"), h1))
    sub_text = "  ·  ".join(filter(None,[p.get("pos",""),p.get("sport",""),p.get("year",""),p.get("school","")]))
    story.append(Paragraph(sub_text, sub))

    tier_color = PURP if p["tier"]=="Blue Chip" else BLUE
    ovr_data = [
        [Paragraph("<b>Overall Score</b>",body), Paragraph("<b>Tier</b>",body),
         Paragraph("<b>Est. NIL Value / yr</b>",body), Paragraph("<b>Blue Chip Factors</b>",body)],
        [Paragraph(f'<font size="16"><b>{p["overall"]}/100</b></font>',
                   ParagraphStyle("big",fontSize=16,fontName="Helvetica-Bold",textColor=BLUE)),
         Paragraph(f'<font size="13"><b>{p["tier"]}</b></font>',
                   ParagraphStyle("tier",fontSize=13,fontName="Helvetica-Bold",textColor=tier_color)),
         Paragraph(f'<font size="13"><b>${p["nil_lo"]:,} – ${p["nil_hi"]:,}</b></font>',
                   ParagraphStyle("nil",fontSize=13,fontName="Helvetica-Bold",textColor=BLUE)),
         Paragraph(
             f'Recruiting: {_rank_label(p.get("recruit_rank",0))}<br/>'
             f'Draft proj: {_draft_label(p.get("draft_round",0))}',
             ParagraphStyle("bc",fontSize=9,textColor=DARK,leading=14)
         )],
    ]
    ovr_tbl = Table(ovr_data, colWidths=[W*0.18,W*0.18,W*0.32,W*0.32])
    ovr_tbl.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),LBLUE),
        ("GRID",(0,0),(-1,-1),0.5,rl_colors.HexColor("#B5D4F4")),
        ("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("LEFTPADDING",(0,0),(-1,-1),10),
    ]))
    story.append(ovr_tbl)
    story.append(Spacer(1,12))

    story.append(Paragraph("Score Breakdown", h2))
    tbl_data = [["Dimension","Score","Weight","Key Inputs"]] + [
        ("Athletic Performance", p["ath"],       "35%", "Stars · Start rate · Awards · Conference"),
        ("Social Media Reach",   p["soc"],       "30%", "Followers × engagement (log-scaled)"),
        ("Market Opportunity",   p["mkt"],       "25%", "School size · TV exposure · DMA market"),
        ("Retention (inverted)", 100-p["risk"],  "10%", "Transfer risk · Draft eligibility"),
    ]
    score_tbl = Table(tbl_data, colWidths=[W*0.30,W*0.10,W*0.10,W*0.50])
    score_tbl.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),BLUE),("TEXTCOLOR",(0,0),(-1,0),rl_colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),9),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[rl_colors.white,LGRAY]),
        ("GRID",(0,0),(-1,-1),0.4,rl_colors.HexColor("#D3D1C7")),
        ("ALIGN",(1,0),(2,-1),"CENTER"),
        ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("LEFTPADDING",(0,0),(-1,-1),8),
    ]))
    story.append(score_tbl)
    story.append(Spacer(1,12))

    story.append(Paragraph("Key Insights", h2))
    total_soc = p.get("ig",0)+p.get("tt",0)+p.get("xf",0)
    start_rate = round(p.get("starts",0)/max(p.get("games",1),1)*100)
    cap_pct = p["nil_hi"]/20_500_000*100
    insights = [
        f"<b>NIL Estimate Basis:</b> Fair-market floor. Bidding-war premiums (e.g. competitive recruiting) may push actual deals higher.",
        f"<b>Blue Chip Factors:</b> Recruiting rank: {_rank_label(p.get('recruit_rank',0))} · Draft projection: {_draft_label(p.get('draft_round',0))}",
        f"<b>Social Reach:</b> {total_soc:,} total followers with {p.get('eng',0):.1f}% avg engagement rate",
        f"<b>Start Rate:</b> {start_rate}% ({p.get('starts',0)} starts / {p.get('games',0)} games)",
        f"<b>Transfer Risk:</b> {['Low — prioritize retention','Medium — evaluate collective engagement','High — immediate NIL conversation needed'][p.get('rTransfer',0)]}",
        f"<b>Revenue-Share Context:</b> ~{cap_pct:.2f}% of the $20.5M House settlement cap",
        f"<b>Compliance:</b> All NIL agreements must document fair market value with proof of services rendered.",
    ]
    for ins in insights:
        story.append(Paragraph(f"• {ins}", body))

    story.append(Spacer(1,10))
    story.append(HRFlowable(width=W, thickness=0.5, color=rl_colors.HexColor("#D3D1C7")))
    story.append(Spacer(1,6))
    story.append(Paragraph("AVIP · Confidential — For Internal Athletic Department Use Only", foot))

    doc.build(story)
    return buf.getvalue()

def _rank_label(r):
    if r == 0: return "Unranked"
    if r <= 10: return f"Top 10 (#{r})"
    if r <= 30: return f"Top 30 (#{r})"
    if r <= 100: return f"Top 100 (#{r})"
    return f"Top 300 (#{r})"

def _draft_label(d):
    return ["Not projected","Lottery pick (1-14)","Late 1st round (15-30)","2nd round"][min(d,3)]

# ─────────────────────────────────────────────────────────────────────────────
# CSV TEMPLATE
# ─────────────────────────────────────────────────────────────────────────────

COLUMNS = [
    "name","school","sport","position","year",
    "games","starts","stars","awards","conference",
    "ig_followers","tiktok_followers","twitter_followers","engagement_pct",
    "school_size","tv_exposure","market_size",
    "transfer_risk","draft_risk","national_recruiting_rank","draft_projection",
]
SAMPLE_DATA = [
    ["Marcus Hill","Univ. of Missouri","Football","WR","Junior",12,10,4,"Conference Award","Power 4",18000,25000,4500,5.2,"20,000+","National (ESPN, Fox)","Top-25 DMA","Low — committed","0 — Not projected","Unranked","0 — Not projected"],
    ["Deja Williams","SLU","Basketball","PG","Senior",28,26,3,"None","Mid-Major",9000,12000,2200,7.8,"8,000–20,000","Regional network","Mid-size market","Medium","0 — Not projected","Unranked","0 — Not projected"],
    ["Carlos Reyes","SIUE","Baseball","SP","Sophomore",18,15,2,"Team Award","D-II / D-III / NAIA",3000,5000,800,3.1,"8,000–20,000","Streaming / local only","Mid-size market","Low — committed","0 — Not projected","Unranked","0 — Not projected"],
    ["Amara Knox","Mizzou","Soccer","FW","Junior",20,18,4,"Conference Award","Power 4",22000,30000,5500,6.4,"20,000+","National (ESPN, Fox)","Top-25 DMA","Low — committed","0 — Not projected","Top 100","2 — Late 1st rd (15-30)"],
    ["Milan Momcilovic","Sacramento Kings","Basketball","SF","Freshman",30,28,5,"All-American / National","Power 4",150000,200000,45000,6.8,"20,000+","National (ESPN, Fox)","Top-25 DMA","Low — committed","1 — Lottery pick (1-14)","Top 10","1 — Lottery pick (1-14)"],
]

def csv_row_to_player(row) -> dict:
    def safe_int(v, d=0):
        try: return int(float(v))
        except: return d
    def safe_float(v, d=0.0):
        try: return float(v)
        except: return d
    return {
        "name":       str(row.get("name","Athlete")),
        "school":     str(row.get("school","")),
        "sport":      str(row.get("sport","")),
        "pos":        str(row.get("position","")),
        "year":       str(row.get("year","")),
        "games":      safe_int(row.get("games",10)),
        "starts":     safe_int(row.get("starts",8)),
        "stars":      safe_int(row.get("stars",3)),
        "awards_val": AWARD_MAP.get(str(row.get("awards","None")), 0),
        "conf_val":   CONF_TIER_MAP.get(str(row.get("conference","Mid-Major")), 2),
        "ig":         safe_int(row.get("ig_followers",0)),
        "tt":         safe_int(row.get("tiktok_followers",0)),
        "xf":         safe_int(row.get("twitter_followers",0)),
        "eng":        safe_float(row.get("engagement_pct",2.0)),
        "mSize":      SIZE_MAP.get(str(row.get("school_size","8,000–20,000")), 2),
        "mTV":        TV_MAP.get(str(row.get("tv_exposure","Regional network")), 2),
        "mMkt":       MKT_MAP.get(str(row.get("market_size","Mid-size market")), 2),
        "rTransfer":  TRANSFER_MAP.get(str(row.get("transfer_risk","Low — committed")), 0),
        "rDraft":     DRAFT_MAP.get(str(row.get("draft_risk","0 — Not projected")), 0),
        "recruit_rank": RECRUIT_MAP.get(str(row.get("national_recruiting_rank","Unranked")), 0),
        "draft_round":  DRAFT_MAP.get(str(row.get("draft_projection","0 — Not projected")), 0),
    }

def make_sample_csv() -> bytes:
    return pd.DataFrame(SAMPLE_DATA, columns=COLUMNS).to_csv(index=False).encode()

# ─────────────────────────────────────────────────────────────────────────────
# CHARTS
# ─────────────────────────────────────────────────────────────────────────────

def radar_chart(p):
    cats   = ["Athletic","Social","Market","Retention\n(inv)"]
    values = [p["ath"], p["soc"], p["mkt"], 100-p["risk"]]
    fig = go.Figure(go.Scatterpolar(
        r=values+[values[0]], theta=cats+[cats[0]],
        fill="toself", fillcolor="rgba(55,138,221,0.15)",
        line=dict(color="#185FA5",width=2), marker=dict(color="#185FA5",size=6),
    ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True,range=[0,100],tickfont=dict(size=9))),
        showlegend=False, margin=dict(l=30,r=30,t=30,b=30), height=300,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig

def roster_bar_chart(df):
    df_s = df.sort_values("overall", ascending=True)
    cmap = {"Blue Chip":"#7c3aed","Elite":"#059669","High Value":"#2563eb",
            "Developing":"#d97706","Entry Level":"#dc2626"}
    fig = go.Figure(go.Bar(
        x=df_s["overall"], y=df_s["name"], orientation="h",
        marker_color=[cmap.get(t,"#888") for t in df_s["tier"]],
        text=[f"{v}/100" for v in df_s["overall"]], textposition="outside",
    ))
    fig.update_layout(
        xaxis=dict(range=[0,115],title="Overall Score"), yaxis=dict(title=""),
        height=max(300,len(df_s)*42), margin=dict(l=10,r=60,t=20,b=30),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig

def nil_range_chart(df):
    df_s = df.sort_values("nil_hi",ascending=False).head(15)
    fig = go.Figure()
    cmap = {"Blue Chip":"#7c3aed","Elite":"#059669","High Value":"#2563eb",
            "Developing":"#d97706","Entry Level":"#dc2626"}
    for _, row in df_s.iterrows():
        c = cmap.get(row["tier"],"#185FA5")
        fig.add_trace(go.Scatter(
            x=[row["nil_lo"],row["nil_hi"]], y=[row["name"],row["name"]],
            mode="lines+markers", line=dict(width=6,color=c),
            marker=dict(size=10,color=[c,c]),
            name=row["name"], showlegend=False,
        ))
    fig.update_layout(
        xaxis=dict(title="Estimated NIL Value ($)",tickformat="$,.0f"),
        yaxis=dict(autorange="reversed"),
        height=max(300,len(df_s)*46), margin=dict(l=10,r=20,t=20,b=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig

def scatter_chart(df):
    cmap = {"Blue Chip":"#7c3aed","Elite":"#059669","High Value":"#2563eb",
            "Developing":"#d97706","Entry Level":"#dc2626"}
    fig = px.scatter(
        df, x="soc", y="ath", size="overall", color="tier",
        hover_name="name",
        hover_data={"nil_hi":True,"mkt":True,"soc":False,"ath":False,"tier":False},
        color_discrete_map=cmap,
        labels={"soc":"Social Score","ath":"Athletic Score","nil_hi":"NIL High","mkt":"Market Score"},
        size_max=30,
    )
    fig.update_layout(
        height=400, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h",yanchor="bottom",y=1.02),
    )
    return fig

# ─────────────────────────────────────────────────────────────────────────────
# PLAYER REPORT UI
# ─────────────────────────────────────────────────────────────────────────────

TIER_HTML = {
    "Blue Chip":   '<span class="bluechip">💎 Blue Chip</span>',
    "Elite":       '<span class="tier-elite">🏆 Elite</span>',
    "High Value":  '<span class="tier-high">⭐ High Value</span>',
    "Developing":  '<span class="tier-dev">📈 Developing</span>',
    "Entry Level": '<span class="tier-entry">🌱 Entry Level</span>',
}

def show_player_report(p):
    st.markdown(f"## {p['name']}  {TIER_HTML.get(p['tier'],'')}", unsafe_allow_html=True)
    st.caption(f"{p.get('pos','')}  ·  {p.get('sport','')}  ·  {p.get('year','')}  ·  {p.get('school','')}")

    if p["tier"] == "Blue Chip":
        st.info(f"💎 **Blue Chip multiplier active** — Recruiting: {_rank_label(p.get('recruit_rank',0))} · Draft: {_draft_label(p.get('draft_round',0))}")

    st.markdown("---")
    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("Overall Score",   f"{p['overall']}/100")
    c2.metric("Athletic",        f"{p['ath']}/100")
    c3.metric("Social",          f"{p['soc']}/100")
    c4.metric("Market",          f"{p['mkt']}/100")
    c5.metric("Retention Risk",  f"{p['risk']}/100", delta="lower is better", delta_color="inverse")

    st.markdown(f"### 💰 Estimated NIL Value: `${p['nil_lo']:,} – ${p['nil_hi']:,}` / year")
    cap_pct = p['nil_hi'] / 20_500_000 * 100
    st.caption(f"Fair-market floor estimate · ~{cap_pct:.2f}% of $20.5M House settlement cap · Bidding-war deals may exceed this range")

    col_r, col_i = st.columns([1,1])
    with col_r:
        st.plotly_chart(radar_chart(p), use_container_width=True)
    with col_i:
        st.markdown("**Insights**")
        total_soc = p.get("ig",0)+p.get("tt",0)+p.get("xf",0)
        start_rate = round(p.get("starts",0)/max(p.get("games",1),1)*100)
        rows = [
            ("Recruiting Rank",  _rank_label(p.get("recruit_rank",0))),
            ("Draft Projection", _draft_label(p.get("draft_round",0))),
            ("Social Reach",     f"{total_soc:,} followers · {p.get('eng',0):.1f}% engagement"),
            ("Start Rate",       f"{start_rate}%"),
            ("Transfer Risk",    ["Low ✅","Medium ⚠️","High 🚨"][p.get("rTransfer",0)]),
            ("Recruiting Stars", "⭐"*p.get("stars",3)),
            ("Rev-Share %",      f"~{cap_pct:.2f}% of $20.5M cap"),
        ]
        for label, val in rows:
            st.markdown(f"**{label}:** {val}")

    st.markdown("---")
    pdf_bytes = build_pdf(p)
    st.download_button(
        "⬇️ Download PDF Report", data=pdf_bytes,
        file_name=f"AVIP_{p['name'].replace(' ','_')}.pdf",
        mime="application/pdf", use_container_width=True,
    )

# ─────────────────────────────────────────────────────────────────────────────
# ROSTER PAGE
# ─────────────────────────────────────────────────────────────────────────────

def show_roster(df_scored):
    st.markdown("## 📋 Roster Value Overview")
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Total Players",           len(df_scored))
    c2.metric("Avg. Overall Score",      f"{df_scored['overall'].mean():.1f}")
    c3.metric("Blue Chip / Elite",       len(df_scored[df_scored["tier"].isin(["Blue Chip","Elite"])]))
    c4.metric("Total Roster NIL (high)", f"${df_scored['nil_hi'].sum():,.0f}")

    tabs = st.tabs(["📊 Rankings","🎯 NIL Ranges","🔬 Athletic vs Social","📄 Data Table"])
    with tabs[0]:
        st.plotly_chart(roster_bar_chart(df_scored), use_container_width=True)
    with tabs[1]:
        st.plotly_chart(nil_range_chart(df_scored), use_container_width=True)
    with tabs[2]:
        st.plotly_chart(scatter_chart(df_scored), use_container_width=True)
        st.caption("Bubble size = overall score. Purple = Blue Chip. Hover for details.")
    with tabs[3]:
        disp = df_scored[["name","school","sport","tier","overall","ath","soc","mkt","risk","nil_lo","nil_hi"]].copy()
        disp.columns = ["Name","School","Sport","Tier","Overall","Athletic","Social","Market","Risk","NIL Low","NIL High"]
        disp["NIL Low"]  = disp["NIL Low"].apply(lambda x: f"${x:,}")
        disp["NIL High"] = disp["NIL High"].apply(lambda x: f"${x:,}")
        st.dataframe(disp, use_container_width=True, hide_index=True)
        st.download_button("⬇️ Export Roster CSV",
                           df_scored.to_csv(index=False).encode(),
                           "roster_scores.csv","text/csv",use_container_width=True)

# ─────────────────────────────────────────────────────────────────────────────
# MANUAL FORM
# ─────────────────────────────────────────────────────────────────────────────

def manual_form():
    with st.form("player_form"):
        c1,c2,c3 = st.columns(3)
        with c1:
            name   = st.text_input("Player Name", "Marcus Hill")
            school = st.text_input("School", "Univ. of Missouri")
            sport  = st.selectbox("Sport", ["Football","Basketball","Baseball","Soccer","Other"])
        with c2:
            pos    = st.text_input("Position", "WR")
            year   = st.selectbox("Year", ["Freshman","Sophomore","Junior","Senior","Grad Transfer"])
            conf   = st.selectbox("Conference Tier", list(CONF_TIER_MAP.keys()))
        with c3:
            games  = st.number_input("Games Played", 0, 82, 12)
            starts = st.number_input("Starts", 0, 82, 10)
            stars  = st.slider("Recruiting Stars", 1, 5, 4)

        st.markdown("---")
        c4,c5,c6 = st.columns(3)
        with c4:
            st.markdown("**Athletic**")
            awards = st.selectbox("Awards / Honors", list(AWARD_MAP.keys()))
        with c5:
            st.markdown("**Social Media**")
            ig  = st.number_input("Instagram Followers", 0, value=18000, step=500)
            tt  = st.number_input("TikTok Followers",    0, value=25000, step=500)
            xf  = st.number_input("Twitter/X Followers", 0, value=4500,  step=500)
            eng = st.number_input("Avg. Engagement %",   0.0, 100.0, 5.2, step=0.1)
        with c6:
            st.markdown("**Market & Risk**")
            mSize     = st.selectbox("School Enrollment",     list(SIZE_MAP.keys()))
            mTV       = st.selectbox("TV/Streaming Exposure", list(TV_MAP.keys()))
            mMkt      = st.selectbox("Local Market Size",     list(MKT_MAP.keys()))
            rTransfer = st.selectbox("Transfer Risk",         list(TRANSFER_MAP.keys()))
            rDraft    = st.selectbox("Draft Eligibility",     list(TRANSFER_MAP.keys()))

        st.markdown("---")
        st.markdown("**💎 Blue Chip Factors** — leave at defaults if not applicable")
        bc1, bc2 = st.columns(2)
        with bc1:
            recruit_rank_label = st.selectbox("National Recruiting Rank", list(RECRUIT_MAP.keys()))
        with bc2:
            draft_round_label  = st.selectbox("Draft Projection", list(DRAFT_MAP.keys()))

        submitted = st.form_submit_button("📊  Calculate Player Value", use_container_width=True)

    if submitted:
        return {
            "name":name,"school":school,"sport":sport,"pos":pos,"year":year,
            "games":games,"starts":starts,"stars":stars,
            "awards_val":AWARD_MAP[awards],"conf_val":CONF_TIER_MAP[conf],
            "ig":ig,"tt":tt,"xf":xf,"eng":eng,
            "mSize":SIZE_MAP[mSize],"mTV":TV_MAP[mTV],"mMkt":MKT_MAP[mMkt],
            "rTransfer":TRANSFER_MAP[rTransfer],
            "rDraft":DRAFT_MAP.get(rDraft, 0),
            "recruit_rank": RECRUIT_MAP[recruit_rank_label],
            "draft_round":  DRAFT_MAP[draft_round_label],
        }
    return None

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    with st.sidebar:
        st.markdown("## 🏆 AVIP")
        st.caption("Athlete Value Intelligence Platform")
        st.markdown("---")
        mode = st.radio("Mode", ["Single Player","Roster (CSV Upload)"], label_visibility="collapsed")
        st.markdown("---")
        st.markdown("**💎 Blue Chip Model**")
        st.caption(
            "Now includes recruiting rank and draft projection multipliers. "
            "Top-10 recruits and lottery picks can reach $500K–$2M+. "
            "Estimates reflect fair-market floor — bidding wars may exceed this."
        )
        st.markdown("---")
        st.caption("v2.0 · For internal AD use only")

    if mode == "Single Player":
        st.title("🏆 AVIP — Player Valuation")
        player_input = manual_form()
        if player_input:
            p = score_row(player_input)
            st.markdown("---")
            show_player_report(p)
    else:
        st.title("🏆 AVIP — Roster Valuation")
        col_dl, col_up = st.columns([1,2])
        with col_dl:
            st.download_button("⬇️ Download CSV Template",
                               data=make_sample_csv(),
                               file_name="avip_roster_template.csv",
                               mime="text/csv")
        with col_up:
            uploaded = st.file_uploader("Upload Roster CSV", type=["csv"])

        if uploaded:
            try:
                df = pd.read_csv(uploaded)
                df.columns = [c.strip().lower().replace(" ","_") for c in df.columns]
                players   = [csv_row_to_player(row) for _, row in df.iterrows()]
                scored    = [score_row(p) for p in players]
                df_scored = pd.DataFrame(scored)
                show_roster(df_scored)
                st.markdown("---")
                st.markdown("### Individual Reports")
                for p in scored:
                    with st.expander(f"{p['name']} — {p['tier']} ({p['overall']}/100)  ·  ${p['nil_lo']:,}–${p['nil_hi']:,}"):
                        show_player_report(p)
            except Exception as e:
                st.error(f"Error reading CSV: {e}. Please use the template format.")
        else:
            st.info("👆 Download the template, fill it in with your roster, then upload it here.")
            st.dataframe(
                pd.DataFrame(SAMPLE_DATA, columns=COLUMNS)[
                    ["name","school","sport","position","stars",
                     "national_recruiting_rank","draft_projection","ig_followers","engagement_pct"]
                ], hide_index=True
            )

if __name__ == "__main__":
    main()
