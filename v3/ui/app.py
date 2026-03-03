import json
import os
import sys
from pathlib import Path


import streamlit as st

# Ensure repo root is on sys.path so `from v3.ui.utils` works reliably.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v3.ui.utils import set_status, load_state

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

state = load_state()
for it in items:
    uid = it.get("job_uid")
    if uid and uid in state:
        it["status"] = state[uid]

st.sidebar.caption(f"Loaded: {len(items)}")
st.sidebar.caption(f"Generated: {vm.get('generated_at_utc','')}")

decision = st.sidebar.multiselect("Decision", ["apply", "maybe", "skip"], ["apply", "maybe", "skip"])
status_filter = st.sidebar.multiselect("Status", ["new", "applied", "ignored"], ["new", "applied", "ignored"])
min_score = st.sidebar.slider("Min score", 0.0, 1.0, 0.0, 0.01)
query = st.sidebar.text_input("Search (title/company/location)")


def match(it):
    if it.get("decision") not in decision:
        return False
    if it.get("status", "new") not in status_filter:
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
c1.metric("Apply", sum(1 for i in shown if i.get("decision") == "apply"))
c2.metric("Maybe", sum(1 for i in shown if i.get("decision") == "maybe"))
c3.metric("Skip", sum(1 for i in shown if i.get("decision") == "skip"))
c4.metric("Shown", len(shown))

st.divider()

for it in shown:
    uid = it.get("job_uid", "")
    left, right = st.columns([3, 1])

    with left:
        st.subheader(f"{it.get('title','')} — {it.get('company','')}")
        st.caption(
            f"{it.get('location','')} • "
            f"score={float(it.get('score',0.0)):.2f} • "
            f"decision={it.get('decision')} • "
            f"status={it.get('status','new')}"
        )

        url = it.get("apply_url", "")
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
        # Status controls (fast, no LLM rerun).
        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button("Applied", key=f"applied_{uid}"):
                set_status(uid, "applied")
                # Update in-memory view so UI reflects change immediately.
                it["status"] = "applied"
                st.rerun()
        with b2:
            if st.button("Ignore", key=f"ignored_{uid}"):
                set_status(uid, "ignored")
                it["status"] = "ignored"
                st.rerun()
        with b3:
            if st.button("Reset", key=f"new_{uid}"):
                set_status(uid, "new")
                it["status"] = "new"
                st.rerun()

        st.write("")  # spacer

        mk = it.get("matched_keywords", [])
        mi = it.get("missing_keywords", [])
        if mk:
            st.write("Matched:", ", ".join(mk[:10]))
        if mi:
            st.write("Missing:", ", ".join(mi[:10]))

    st.divider()