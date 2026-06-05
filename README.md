# AVIP — Athlete Value Intelligence Platform

**Decision-support software for athletic departments, NIL collectives, and sports agents.**

Estimates NIL value and roster worth using athletic performance, social media reach, market opportunity, and retention risk — aligned with the 2025–26 House settlement ($20.5M revenue-share cap).

---

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the app
```bash
streamlit run app.py
```

The app opens in your browser at `http://localhost:8501`

---

## Features

### Single Player Mode
- Enter player details manually via a structured form
- Instant scoring across 4 dimensions (Athletic, Social, Market, Retention)
- Radar chart visualization
- Estimated NIL value range
- Revenue-share cap context (House settlement)
- **PDF report export** — one-page summary for ADs and compliance staff

### Roster Mode (CSV Upload)
- Upload a CSV with your full roster
- Batch-score every player in seconds
- 4 visualization tabs: Rankings, NIL Ranges, Athletic vs Social scatter, Data Table
- Export scored roster as CSV
- Expand individual player reports inline
- Download PDF for any player

---

## Scoring Model

| Dimension        | Weight | Key Inputs |
|-----------------|--------|------------|
| Athletic        | 35%    | Games, starts, recruiting stars, awards, conference tier |
| Social Media    | 30%    | Followers × engagement rate (log-scaled) |
| Market          | 25%    | School size, TV exposure, local market DMA |
| Retention (inv) | 10%    | Transfer risk, draft eligibility |

**NIL Range** = (weighted base score) × market multiplier — adjusted for retention risk

---

## CSV Template Columns

| Column | Example Values |
|--------|---------------|
| `name` | Marcus Hill |
| `school` | Univ. of Missouri |
| `sport` | Football |
| `position` | WR |
| `year` | Junior |
| `games` | 12 |
| `starts` | 10 |
| `stars` | 4 |
| `awards` | None / Team Award / Conference Award / All-American / National |
| `conference` | Power 4 / Mid-Major / D-II / D-III / NAIA |
| `ig_followers` | 18000 |
| `tiktok_followers` | 25000 |
| `twitter_followers` | 4500 |
| `engagement_pct` | 5.2 |
| `school_size` | 20,000+ / 8,000–20,000 / Under 8,000 |
| `tv_exposure` | National (ESPN, Fox) / Regional network / Streaming / local only |
| `market_size` | Top-25 DMA / Mid-size market / Small market |
| `transfer_risk` | Low — committed / Medium / High — exploring portal |
| `draft_risk` | 3+ years remaining / 1–2 years remaining / Draft-eligible now |

Download the template directly from the app.

---

## Tier Labels

| Score | Tier | Meaning |
|-------|------|---------|
| 80–100 | 🏆 Elite | Top NIL candidate — prioritize deals |
| 60–79 | ⭐ High Value | Strong roster asset with brand upside |
| 40–59 | 📈 Developing | Growing player — monitor and invest |
| 0–39 | 🌱 Entry Level | Early stage — focus on athletic development |

---

## Compliance Note

> All NIL agreements must document fair market value with proof of services rendered.  
> Revenue-share deals are separate from NIL deals under the House v. NCAA settlement.  
> Consult your institution's compliance office before structuring any agreements.

---

## Deployment Options

| Option | Cost | Ease |
|--------|------|------|
| **Streamlit Community Cloud** | Free | ⭐⭐⭐⭐⭐ |
| **Render** | Free / $7/mo | ⭐⭐⭐⭐ |
| **Railway** | ~$5/mo | ⭐⭐⭐⭐ |
| **Your own server** | VPS cost | ⭐⭐⭐ |

### Deploy to Streamlit Community Cloud (recommended for demos)
1. Push this folder to a GitHub repo
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your repo → select `app.py`
4. Done — shareable URL in minutes

---

## Roadmap (v2)

- [ ] Auto-pull stats from Sports Reference API
- [ ] On3 / 247Sports recruiting data integration
- [ ] Collective ROI calculator (cost vs. exposure value)
- [ ] Multi-season trend tracking
- [ ] Sponsor matching engine (local business × player brand fit)
- [ ] Slack / email alerts for high transfer-risk players

---

*AVIP · Confidential — For Internal Athletic Department Use Only*
