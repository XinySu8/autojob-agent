import json
import os
import re
from typing import Any, Dict

ROOT = os.path.dirname(os.path.dirname(__file__))  # v3/

def norm_field(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", "_", s)
    return s

def main():
    in_path = os.path.join(ROOT, "output", "agent_results.json")
    out_path = os.path.join(ROOT, "output", "agent_results.normalized.json")

    with open(in_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for it in data.get("items", []):
        # normalize evidence field names
        ev = it.get("evidence", [])
        if isinstance(ev, list):
            for e in ev:
                if isinstance(e, dict) and "field" in e:
                    e["field"] = norm_field(e["field"])

        # normalize risk_flags: remove "None"
        rf = it.get("risk_flags", [])
        if rf == ["None"] or rf == ["none"] or rf == ["NONE"]:
            it["risk_flags"] = []
        elif isinstance(rf, list):
            it["risk_flags"] = [str(x).strip() for x in rf if str(x).strip().lower() not in {"none", "n/a", "na"}]

        # reasons: trim
        rs = it.get("reasons", [])
        if isinstance(rs, list):
            it["reasons"] = [str(x).strip() for x in rs if str(x).strip()]

        # missing_info: trim
        mi = it.get("missing_info", [])
        if isinstance(mi, list):
            it["missing_info"] = [str(x).strip() for x in mi if str(x).strip()]

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Wrote normalized -> {out_path}")

if __name__ == "__main__":
    main()