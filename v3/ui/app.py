import json
import os
import streamlit as st

V3_ROOT = os.path.dirname(os.path.dirname(__file__))  # v3/
DEFAULT_VIEW = os.path.join(V3_ROOT, "data", "view_model.json")

def load(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

st.set_page_config(page_title="AutoJob-Agent V3", layout="wide")
st.title("AutoJob-Agent V3 — Dashboard")

path = st.sidebar.text_input("view_model.json path", DEFAULT_VIEW)

try:
    vm = load(path)
except Exception as e:
    st.error(f"Failed to load view_model.json: {e}")
    st.stop()

items = vm.get("items", [])
st.sidebar.caption(f"Loaded: {len(items)}")
st.sidebar.caption(f"Generated: {vm.get('generated_at_utc','')}")

decision = st.sidebar.multiselect("Decision", ["apply", "maybe", "skip"], ["apply", "maybe", "skip"])
min_score = st.sidebar.slider("Min score", 0.0, 1.0, 0.0, 0.01)
query = st.sidebar.text_input("Search (title/company/location)")

def match(it):
    if it.get("decision") not in decision:
        return False
    if float(it.get("score", 0.0)) < min_score:
        return False
    if query.strip():
        q = query.strip().lower()
        return (
            q in it.get("title", "").lower()
            or q in it.get("company", "").lower()
            or q in it.get("location", "").lower()
        )
    return True

shown = [it for it in items if match(it)]
shown.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Apply", sum(1 for i in shown if i["decision"] == "apply"))
c2.metric("Maybe", sum(1 for i in shown if i["decision"] == "maybe"))
c3.metric("Skip", sum(1 for i in shown if i["decision"] == "skip"))
c4.metric("Shown", len(shown))

st.divider()

for it in shown:
    left, right = st.columns([3, 1])
    with left:
        st.subheader(f"{it.get('title','')} — {it.get('company','')}")
        st.caption(f"{it.get('location','')} • score={it.get('score',0):.2f} • decision={it.get('decision')} • status={it.get('status','new')}")
        url = it.get("apply_url","")
        if url:
            st.link_button("Open application page", url)

        reasons = it.get("reasons", [])
        if reasons:
            st.write("Reasons:", ", ".join(reasons))

        evidence = it.get("evidence", [])
        if evidence:
            with st.expander("Evidence"):
                for e in evidence:
                    st.write(f"- {e.get('field')}: {e.get('snippet')}")

    with right:
        mk = it.get("matched_keywords", [])
        mi = it.get("missing_keywords", [])
        if mk:
            st.write("Matched:", ", ".join(mk[:10]))
        if mi:
            st.write("Missing:", ", ".join(mi[:10]))