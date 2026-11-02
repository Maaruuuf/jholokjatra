"""Streamlit front-end.  Run:  streamlit run ui/app.py   (API must be running on :8000)"""
import datetime as dt
import os

import folium
import requests
import streamlit as st
from streamlit_folium import st_folium

API = os.getenv("API_URL", "http://localhost:8000")
ICON = {"go": "🟢", "caution": "🟡", "avoid": "🔴"}

st.set_page_config(page_title="JholokJatra", page_icon="🧭", layout="wide")
st.title("🧭 JholokJatra · যাত্রার সেরা দিন")
st.caption("Evidence-cited best-day-to-go advice for Bangladesh, built on free public APIs.")

try:
    dests = requests.get(f"{API}/destinations", timeout=10).json()
except requests.RequestException:
    st.error(f"API not reachable at {API}. Start it with: uvicorn app.main:app --reload")
    st.stop()

with st.sidebar:
    lang = st.radio("Language / ভাষা", ["en", "bn"], horizontal=True)
    def label(d):
        return d["name_bn"] if lang == "bn" else d["name"]

    choice = st.selectbox("Destination", dests, format_func=label)
    today = dt.date.today()
    rng = st.date_input("Date range (up to 16 days ahead)", (today, today + dt.timedelta(days=6)),
                        min_value=today, max_value=today + dt.timedelta(days=15))
    risk = st.select_slider("Risk tolerance", ["low", "medium", "high"], value="medium")
    st.subheader("Preferences")
    motion = st.checkbox("Motion sickness")
    kids = st.checkbox("Travelling with kids")
    elderly = st.checkbox("Elderly travellers")
    go = st.button("Find the best day", type="primary", use_container_width=True)

if go and isinstance(rng, tuple) and len(rng) == 2:
    requests.put(f"{API}/preferences/streamlit", timeout=10, json={
        "risk_tolerance": risk, "motion_sickness": motion, "traveling_with_kids": kids, "elderly_travelers": elderly})
    with st.spinner("Fetching live data and running the agents..."):
        r = requests.post(f"{API}/plan", timeout=120, json={
            "destination": choice["key"], "start_date": str(rng[0]), "end_date": str(rng[1]),
            "language": lang, "user_id": "streamlit"})
    if r.status_code != 200:
        st.error(r.json().get("detail", r.text))
    else:
        st.session_state["plan"] = r.json()

plan = st.session_state.get("plan")
if plan:
    if plan["status"] == "needs_approval":
        st.warning(plan["approval_question"])
        c1, c2 = st.columns(2)
        for col, ok, text in ((c1, True, "Yes, recommend it"), (c2, False, "No")):
            if col.button(text, key=f"d{ok}"):
                st.session_state["plan"] = requests.post(f"{API}/plans/{plan['plan_id']}/decision",
                                                         json={"approved": ok}, timeout=30).json()
                st.rerun()
    st.subheader(plan["destination"])
    st.write(plan["narrative"])
    st.caption(f"Narrative source: {plan['narrative_source']} · tokens used: {plan['tokens_used']}")
    if plan["best_days"]:
        st.success("Best days: " + ", ".join(plan["best_days"]) + (" (caution)" if plan["best_is_caution"] else ""))
    for c in plan["conflicts"]:
        st.info(c)
    for d in plan["days"]:
        with st.expander(f"{ICON[d['verdict']]} {d['day']} · {d['verdict'].upper()} · score {d['score']}"):
            for rsn in d["reasons"] or []:
                st.markdown(f"- **{rsn['label']}**: {rsn['message']} [raw data]({API}/evidence/{rsn['ref']})")
            if not d["reasons"]:
                st.write("No risk rules triggered.")
            st.json(d["metrics"], expanded=False)
    m = folium.Map(location=[next(x for x in dests if x["key"] == plan["destination_key"])["lat"],
                             next(x for x in dests if x["key"] == plan["destination_key"])["lon"]], zoom_start=9)
    folium.Marker([choice["lat"], choice["lon"]], tooltip=plan["destination"]).add_to(m)
    for h in plan["nearby_hospitals"]:
        folium.Marker([h["lat"], h["lon"]], tooltip=f"{h['name']} ({h['distance_km']} km)",
                      icon=folium.Icon(color="red", icon="plus")).add_to(m)
    st_folium(m, height=350, use_container_width=True)
    if plan["tips"]:
        with st.expander("Travel tips (Wikivoyage, CC BY-SA)"):
            for t in plan["tips"]:
                st.write(t["text"])
                st.caption(t["url"])
    if plan["data_gaps"]:
        st.caption("Data gaps: " + "; ".join(plan["data_gaps"]))
st.caption("Advisory only. For storm signals follow Bangladesh Meteorological Department and local authorities.")
