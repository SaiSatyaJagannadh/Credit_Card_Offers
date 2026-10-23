"""Page CSS: colors, pills and radius per the design brief; mobile stacking."""

import streamlit as st

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap');
:root {
  --co-page: #F7F8FA; --co-card: #FFFFFF; --co-border: #E5E7EB; --co-text: #111827;
  --co-muted: #4B5563; --co-accent: #0B6E4F; --co-radius: 14px;
}
html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
  background: var(--co-page); color: var(--co-text);
}
html, body, .stApp, .stApp p, .stApp label, .stApp input, .stApp textarea, .stApp button,
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp li, .stApp td, .stApp th {
  font-family: 'Manrope', system-ui, sans-serif;
}
.block-container { padding-top: 2.5rem; max-width: 1180px; }
.stApp h1 { font-size: 2rem; font-weight: 800; letter-spacing: -0.02em; }
.stApp h2, .stApp h3 { font-size: 1.2rem; font-weight: 700; margin-top: 0.6rem; }
[data-testid="stSidebarNavSeparator"] { display: none; }
[data-testid="stNavSectionHeader"] { color: var(--co-muted); font-weight: 700; }
[data-testid="stSidebar"] { background: var(--co-card); border-right: 1px solid var(--co-border); }
.mono, .co-value, [data-testid="stMetricValue"] { font-family: 'JetBrains Mono', monospace; }
.co-muted, [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * {
  color: var(--co-muted) !important;
}

a:focus-visible, button:focus-visible { outline: 2px solid var(--co-accent); outline-offset: 2px; }
/* touch targets */
.stButton button, .stFormSubmitButton button, .stLinkButton a, [data-testid="stPageLink"] a,
.stTextInput input, .stNumberInput input, [data-baseweb="select"] > div, a.co-btn {
  min-height: 44px;
}
.stButton button[kind="primary"], .stFormSubmitButton button[kind="primary"] {
  background: var(--co-accent); border-color: var(--co-accent); color: #FFFFFF;
}

[data-testid="stForm"], [class*="st-key-card"] {
  background: var(--co-card); border-color: var(--co-border) !important;
  border-radius: var(--co-radius) !important;
}
[data-testid="stPageLink"] a p { color: var(--co-accent); font-weight: 700; }
.co-acct > span:first-child { white-space: nowrap; font-weight: 600; }
.co-acct .co-pill { white-space: normal; text-align: right; }
[data-testid="stForm"]:has(input[placeholder^="Search or ask"]) {
  background: transparent; padding: 0;
}
.co-card {
  background: var(--co-card); border: 1px solid var(--co-border); border-radius: var(--co-radius);
  padding: 14px 16px; margin-bottom: 10px; color: var(--co-text);
}
.co-kpi .co-label { color: var(--co-muted); font-size: 0.85rem; font-weight: 600; }
.co-kpi .co-value { font-size: 1.6rem; font-weight: 700; margin-top: 4px; }
.co-kpi .co-sub { color: var(--co-muted); font-size: 0.85rem; margin-top: 2px; }

.co-pill {
  display: inline-block; border-radius: 999px; padding: 2px 10px; font-size: 0.78rem;
  font-weight: 600; margin: 2px 4px 2px 0; white-space: nowrap;
}
.co-green { background: #E7F5EE; color: #0B5E43; }
.co-amber { background: #FFF4E0; color: #8A4B00; }
.co-blue { background: #E8F0FE; color: #1E4FA3; }
.co-purple { background: #F1ECFE; color: #5B21B6; }
.co-gray { background: #F3F4F6; color: #4B5563; }

.co-offer { display: flex; gap: 12px; align-items: flex-start; }
.co-initial {
  flex: 0 0 40px; height: 40px; border-radius: 10px; background: #E7F5EE; color: #0B5E43;
  display: flex; align-items: center; justify-content: center; font-weight: 800;
}
.co-offer-main { flex: 1 1 auto; min-width: 0; }
.co-merchant { font-weight: 700; margin-right: 6px; }
.co-offer-side { flex: 0 0 auto; text-align: right; }
.co-offer-side .co-value { font-weight: 700; }
a.co-btn {
  display: inline-flex; align-items: center; color: var(--co-accent); font-weight: 700;
  text-decoration: none;
}
a.co-btn:hover { text-decoration: underline; }
.co-todo { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
.co-todo .co-title { font-weight: 700; }
.co-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px;
  margin: 4px 0 8px; }
.co-kpis .co-card { margin: 0; }
.co-acct { display: flex; justify-content: space-between; align-items: center; gap: 8px;
  padding: 8px 0; border-bottom: 1px solid var(--co-border); }
.co-acct:last-child { border-bottom: 0; }
.co-flow { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.co-flow .co-card { margin: 0; }
.co-when { color: var(--co-accent); font-weight: 600; font-size: 0.85rem; margin: 2px 0 6px; }
.co-flow-into { height: 28px; margin: 0 auto; width: 2px; background: var(--co-border); }
.co-flow-out { border-color: var(--co-accent); background: #E7F5EE; }
.co-title { font-weight: 700; }
.co-list { margin: 0; padding-left: 1.1rem; }
.co-list li { margin-bottom: 6px; }

@media (max-width: 640px) {
  [data-testid="stHorizontalBlock"] { flex-direction: column; gap: 0.5rem; }
  [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
    width: 100% !important; flex: 1 1 100% !important; min-width: 100% !important;
  }
  .co-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  .co-kpi .co-value { font-size: 1.3rem; }
  .co-flow { grid-template-columns: 1fr; }
  .co-offer { flex-wrap: wrap; }
  .co-offer-side { text-align: left; flex-basis: 100%; padding-left: 52px; }
  .block-container { padding-left: 16px; padding-right: 16px; }
}
"""


def inject() -> None:
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)
