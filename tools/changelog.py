"""Append an entry to CHANGELOG.json: python scripts_changelog.py entry.json"""
import json
import sys

c = json.load(open("CHANGELOG.json"))
e = json.load(open(sys.argv[1]))
e["id"] = c["entries"][-1]["id"] + 1
e.setdefault("date", "2026-10-08")
c["entries"].append(e)
json.dump(c, open("CHANGELOG.json", "w"), indent=2)
open("CHANGELOG.json", "a").write("\n")
print("entry", e["id"])
