#!/usr/bin/env python3
"""Loop 1: GATHER.

Pulls Karthik's public GitHub activity and writes a timestamped raw-material file
for the drafting loop to read.

Reads the GitHub REST API rather than local `git log`, because the repos live on a
different machine than the agents. See PLANS/X_GROWTH_AUTOMATION_PLAN.md §11.1.

Usage:
    python3 gather.py [--user karthikjpio] [--days 14] [--out-dir raw]

Set GITHUB_TOKEN to raise the rate limit from 60/hr to 5000/hr and to include
private repos. Unauthenticated is fine for a nightly run: one pass is ~8 requests.

Exit codes: 0 ok (material found), 3 ok but no material in window, 1 hard failure.
"""

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
NO_MATERIAL = 3


class GitHubError(Exception):
    pass


def fetch(path, token=None):
    """GET a GitHub API path, returning parsed JSON."""
    req = urllib.request.Request(API + path)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "x-agent-gather")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        # 403 with a zero remaining-quota header is the rate limit, not a permission
        # problem. Worth distinguishing: one is "wait", the other is "fix your token".
        if e.code == 403 and e.headers.get("X-RateLimit-Remaining") == "0":
            reset = e.headers.get("X-RateLimit-Reset", "")
            when = ""
            if reset.isdigit():
                when = dt.datetime.fromtimestamp(int(reset)).strftime(" (resets %H:%M)")
            raise GitHubError("rate limit exhausted%s; set GITHUB_TOKEN" % when)
        if e.code == 404:
            raise GitHubError("not found: %s" % path)
        raise GitHubError("HTTP %d on %s" % (e.code, path))
    except urllib.error.URLError as e:
        raise GitHubError("network error on %s: %s" % (path, e.reason))


def iso_to_date(s):
    return dt.datetime.strptime(s[:10], "%Y-%m-%d").date()


def collect(user, days, token=None):
    """Return (repos_with_commits, skipped, cutoff)."""
    cutoff = dt.date.today() - dt.timedelta(days=days)
    repos = fetch("/users/%s/repos?sort=pushed&per_page=100" % user, token)

    active, skipped = [], []
    for r in repos:
        if r.get("fork"):
            continue
        # pushed_at bounds the commit dates, so skip the commits call entirely when
        # the repo hasn't been touched in the window. Saves requests against the cap.
        if r.get("pushed_at") and iso_to_date(r["pushed_at"]) < cutoff:
            skipped.append((r["name"], r.get("pushed_at", "")[:10]))
            continue

        commits = fetch("/repos/%s/%s/commits?per_page=100&since=%sT00:00:00Z"
                        % (user, r["name"], cutoff.isoformat()), token)
        picked = []
        for c in commits:
            msg = c["commit"]["message"]
            picked.append({
                "sha": c["sha"][:7],
                "date": c["commit"]["author"]["date"][:10],
                "subject": msg.splitlines()[0],
                "body": "\n".join(msg.splitlines()[1:]).strip(),
                "url": c.get("html_url", ""),
            })
        if picked:
            active.append({
                "name": r["name"],
                "description": r.get("description") or "",
                "language": r.get("language") or "",
                "url": r.get("html_url", ""),
                "commits": picked,
            })

    return active, skipped, cutoff


def render(user, active, skipped, cutoff, days):
    now = dt.datetime.now()
    total = sum(len(r["commits"]) for r in active)

    out = []
    out.append("---")
    out.append('title: "GATHER raw material %s"' % now.strftime("%Y-%m-%d"))
    out.append("tags: [x-growth, gather, raw-material]")
    out.append("status: active")
    out.append("created: %s" % now.strftime("%Y-%m-%d"))
    out.append("---")
    out.append("")
    out.append("# Raw material for %s" % now.strftime("%Y-%m-%d"))
    out.append("")
    out.append("Source: public GitHub activity for `%s`, window %s to %s (%d days)."
               % (user, cutoff.isoformat(), dt.date.today().isoformat(), days))
    out.append("Generated %s by `gather.py`." % now.strftime("%Y-%m-%d %H:%M"))
    out.append("")
    out.append("**Scope:** public repos only. Private repos and unpushed local work are "
               "not visible here. Absence of material below is not evidence that nothing "
               "was built.")
    out.append("")

    if not active:
        out.append("## No public commits in this window")
        out.append("")
        out.append("%d commits found between %s and today." % (total, cutoff.isoformat()))
        out.append("")
        out.append("The drafting loop must **not** invent a build receipt from this file. "
                   "Fall back to the pillars that do not require commits (decision, "
                   "failure, method, positioning), or skip the day and say so.")
        if skipped:
            out.append("")
            out.append("Most recent pushes outside the window:")
            out.append("")
            for name, when in sorted(skipped, key=lambda x: x[1], reverse=True)[:5]:
                out.append("- `%s` — last pushed %s" % (name, when))
        return "\n".join(out) + "\n", total

    out.append("## Summary")
    out.append("")
    out.append("%d commits across %d repo(s)." % (total, len(active)))
    out.append("")

    for r in active:
        out.append("## `%s`" % r["name"])
        out.append("")
        meta = [x for x in (r["language"], r["description"]) if x]
        if meta:
            out.append(" — ".join(meta))
            out.append("")
        for c in r["commits"]:
            out.append("- **%s** `%s` %s" % (c["date"], c["sha"], c["subject"]))
            if c["body"]:
                for line in c["body"].splitlines():
                    if line.strip():
                        out.append("  > %s" % line.strip())
        out.append("")

    out.append("## Notes for drafting")
    out.append("")
    out.append("- Every claim in a post must trace to a commit above. No numbers that "
               "are not in this file.")
    out.append("- Prefer the *problem solved* over the change made. A commit body that "
               "explains why is worth more than the subject line.")
    return "\n".join(out) + "\n", total


def main():
    p = argparse.ArgumentParser(description="Gather GitHub activity into raw material.")
    p.add_argument("--user", default="karthikjpio")
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--out-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw"))
    p.add_argument("--stdout", action="store_true", help="print instead of writing a file")
    args = p.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    try:
        active, skipped, cutoff = collect(args.user, args.days, token)
    except GitHubError as e:
        print("gather: %s" % e, file=sys.stderr)
        return 1

    text, total = render(args.user, active, skipped, cutoff, args.days)

    if args.stdout:
        sys.stdout.write(text)
    else:
        os.makedirs(args.out_dir, exist_ok=True)
        path = os.path.join(args.out_dir, "GATHER_%s.md" % dt.date.today().isoformat())
        with open(path, "w") as f:
            f.write(text)
        print(path)

    if total == 0:
        print("gather: no public commits in the last %d days" % args.days, file=sys.stderr)
        return NO_MATERIAL
    return 0


if __name__ == "__main__":
    sys.exit(main())
