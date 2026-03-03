import json
import os
import sys
import jsonschema

ROOT = os.path.dirname(os.path.dirname(__file__))  # v3/
SCHEMA = os.path.join(ROOT, "schemas", "agent_results.schema.json")

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "output", "agent_results.json")
    with open(SCHEMA, "r", encoding="utf-8") as f:
        schema = json.load(f)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    jsonschema.validate(instance=data, schema=schema)
    print(f"OK: {path} matches schema.")

if __name__ == "__main__":
    main()