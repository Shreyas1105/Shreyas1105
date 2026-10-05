#!/usr/bin/env python3
"""Refresh the live threat-feed block in README.md from CISA's KEV catalog.

The feed is untrusted input: every field is validated and sanitised before it
is written into the README, and on any error the README is left untouched.
"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

FEED_URL = os.environ.get(
    "FEED_URL",
    "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
)
README = Path(__file__).resolve().parent.parent / "README.md"
START, END = "<!--THREAT_FEED_START-->", "<!--THREAT_FEED_END-->"
LIMIT = 5
MAX_BYTES = 20_000_000
CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,7}$")


def clean(value, limit):
    """Strip control chars and backticks, collapse whitespace, truncate."""
    text = re.sub(r"[\x00-\x1f\x7f`]", " ", str(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def fetch():
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": "profile-readme-threat-feed"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read(MAX_BYTES))


def parse(data):
    entries = []
    for v in data.get("vulnerabilities", []):
        cve = str(v.get("cveID", ""))
        try:
            added = datetime.strptime(str(v.get("dateAdded", "")), "%Y-%m-%d").date()
        except ValueError:
            continue
        if not CVE_RE.match(cve):
            continue
        entries.append(
            {
                "cve": cve,
                "added": added,
                "vendor": clean(v.get("vendorProject", "?"), 24),
                "product": clean(v.get("product", "?"), 28),
                "name": clean(v.get("vulnerabilityName", ""), 64),
                "ransomware": str(v.get("knownRansomwareCampaignUse", "")).lower() == "known",
            }
        )
    entries.sort(key=lambda e: (e["added"], e["cve"]), reverse=True)
    return entries


def threat_level(recent):
    # My own simple heuristic, not an official rating.
    if recent >= 10:
        return "HIGH"
    if recent >= 4:
        return "ELEVATED"
    return "GUARDED"


def build_block(entries):
    now = datetime.now(timezone.utc)
    week_ago = (now - timedelta(days=7)).date()
    recent = sum(1 for e in entries if e["added"] >= week_ago)
    lines = [
        "$ ./threat-feed --source cisa-kev --limit %d" % LIMIT,
        "SYSTEM: ONLINE | THREAT LEVEL: %s | LAST SYNC: %s UTC"
        % (threat_level(recent), now.strftime("%Y-%m-%d %H:%M")),
        "KEV catalog: %d entries | added in last 7 days: %d" % (len(entries), recent),
        "",
    ]
    for e in entries[:LIMIT]:
        flag = "  [RANSOMWARE]" if e["ransomware"] else ""
        lines.append("[%s] %s  %s %s%s" % (e["added"], e["cve"], e["vendor"], e["product"], flag))
        lines.append("             %s" % e["name"])
    body = "\n".join(lines)
    return (
        "%s\n```text\n%s\n```\n"
        "<sub>Source: [CISA Known Exploited Vulnerabilities]"
        "(https://www.cisa.gov/known-exploited-vulnerabilities-catalog). "
        "Threat level is my own heuristic based on entries added in the last 7 days.</sub>\n%s"
        % (START, body, END)
    )


def main():
    try:
        entries = parse(fetch())
    except Exception as exc:  # network, JSON, schema: keep the last good README
        print("feed update failed: %s" % exc, file=sys.stderr)
        return 1
    if not entries:
        print("feed returned no valid entries; leaving README unchanged", file=sys.stderr)
        return 1
    text = README.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    if not pattern.search(text):
        print("markers not found in README.md", file=sys.stderr)
        return 1
    new = pattern.sub(lambda _m: build_block(entries), text, count=1)
    if new != text:
        README.write_text(new, encoding="utf-8")
    print("updated with %d entries" % len(entries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
