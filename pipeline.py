#!/usr/bin/env python3
"""Durable human-in-the-loop orchestration for x-agent.

Stops before publishing to X. Approval and publication are separate states:
only ``published`` spends a source note and updates cadence history.
"""

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.parse

import check
import draft
import generate
import privacy


HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_STATE = os.path.join(HERE, "state")
DEFAULT_DENYLIST = os.path.join(HERE, "config", "private-denylist.txt")
MAX_ATTEMPTS = 3


class PipelineError(Exception):
    pass


def atomic_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(path), text=True)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def atomic_json(path, value):
    atomic_write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def read_text(path):
    with open(path) as f:
        return f.read()


@contextlib.contextmanager
def pipeline_lock(state_dir):
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, "pipeline.lock"), "a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def run_dir(state_dir, run_id):
    return os.path.join(state_dir, "runs", run_id)


def record_path(state_dir, run_id):
    return os.path.join(run_dir(state_dir, run_id), "record.json")


def load_record(state_dir, run_id):
    try:
        with open(record_path(state_dir, run_id)) as f:
            return json.load(f)
    except OSError as e:
        raise PipelineError("cannot load run %s: %s" % (run_id, e))


def save_record(state_dir, row):
    row["updated_at"] = now_iso()
    atomic_json(record_path(state_dir, row["id"]), row)


def all_records(state_dir):
    root = os.path.join(state_dir, "runs")
    if not os.path.isdir(root):
        return []
    rows = []
    for name in sorted(os.listdir(root)):
        path = record_path(state_dir, name)
        if os.path.isfile(path):
            with open(path) as f:
                rows.append(json.load(f))
    return rows


def active_today(state_dir, today):
    terminal = {"rejected", "published", "failed", "skipped", "interview_answered"}
    for row in reversed(all_records(state_dir)):
        if row.get("date") == today.isoformat() and row.get("status") not in terminal:
            return row
    return None


def stable_id(today, pillar, source_text):
    digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()[:10]
    return "%s-%s-%s" % (today.isoformat(), pillar, digest)


def exact_source(note, material):
    # A note is the claim boundary. Background commits may help with context,
    # but they cannot widen a note-backed claim.
    return note["body"] if note is not None else (material or "")


def gate_result(draft_text, source_text):
    found = check.check(draft_text, material=source_text)
    return {
        "pass": not any(x["severity"] == "fail" for x in found),
        "findings": found,
        "human_checks": check.HUMAN_CHECKS,
    }


def repair_prompt(prompt, previous, gate, feedback=None):
    blocking = [x["detail"] for x in gate["findings"] if x["severity"] == "fail"]
    out = [prompt.rstrip(), "", "## Revision required", ""]
    if feedback:
        out.extend(["Human feedback: %s" % feedback, ""])
    if blocking:
        out.append("The previous draft failed these checks:")
        out.extend("- %s" % item for item in blocking)
        out.append("")
    out.extend([
        "Previous draft:",
        previous,
        "",
        "Return one corrected post and nothing else. Preserve only claims supported",
        "by the source. Do not add a new number, example, or outcome.",
    ])
    return "\n".join(out) + "\n"


def generate_checked(prompt, source_text, runner=generate.shell_runner,
                     max_attempts=MAX_ATTEMPTS, feedback=None):
    attempts = []
    current_prompt = prompt
    for number in range(1, max_attempts + 1):
        text = generate.generate(current_prompt, runner=runner)
        gate = gate_result(text, source_text)
        attempts.append({"number": number, "draft": text, "gate": gate})
        if gate["pass"]:
            return text, gate, attempts
        current_prompt = repair_prompt(prompt, text, gate, feedback)
    return attempts[-1]["draft"], attempts[-1]["gate"], attempts


def interview_card(run_id, pillar):
    return {
        "run_id": run_id,
        "status": "needs_interview",
        "pillar": pillar,
        "questions": [
            "What exactly did you build or change?",
            "What constraint or tradeoff shaped the decision?",
            "How did you verify it before relying on it?",
            "What broke or surprised you, if anything?",
            "Which details and numbers are safe to publish?",
        ],
        "instruction": (
            "Reply with the answers and explicitly say whether they are safe to publish. "
            "The answers become the source; commits remain background only."
        ),
    }


def gather_today(today, raw_dir):
    cmd = [sys.executable, os.path.join(HERE, "gather.py"), "--out-dir", raw_dir]
    done = subprocess.run(cmd, text=True, capture_output=True)
    if done.returncode not in (0, 3):
        raise PipelineError("gather failed: %s" % ((done.stderr or done.stdout).strip()))
    path = os.path.join(raw_dir, "GATHER_%s.md" % today.isoformat())
    if not os.path.exists(path):
        raise PipelineError("gather returned %d but did not write today's file" % done.returncode)
    with open(path) as f:
        return path, f.read()


def start(state_dir=DEFAULT_STATE, notes_dir=None, raw_dir=None,
          denylist_path=DEFAULT_DENYLIST, today=None, runner=generate.shell_runner,
          gatherer=gather_today):
    today = today or dt.date.today()
    notes_dir = notes_dir or os.path.join(HERE, "notes")
    raw_dir = raw_dir or os.path.join(HERE, "raw")
    history_path = os.path.join(state_dir, "history.json")
    denylist = privacy.load_denylist(denylist_path)

    with pipeline_lock(state_dir):
        existing = active_today(state_dir, today)
        if existing:
            return existing

        material_path, material = gatherer(today, raw_dir)
        history = draft.load_history(history_path)
        fresh = draft.unused_notes(draft.load_notes(notes_dir), history)
        pillar, reason = draft.select(history, today, draft.available(material, fresh))
        if pillar is None:
            row = {
                "id": "%s-skipped" % today.isoformat(),
                "date": today.isoformat(),
                "created_at": now_iso(),
                "status": "skipped",
                "reason": reason,
                "material_path": material_path,
            }
            save_record(state_dir, row)
            return row

        note = draft.pick_note(fresh, pillar["key"])
        source_text = exact_source(note, material)
        run_id = stable_id(today, pillar["key"], source_text)
        base = {
            "id": run_id,
            "date": today.isoformat(),
            "created_at": now_iso(),
            "pillar": pillar["key"],
            "reason": reason,
            "material_path": material_path,
            "note": note["path"] if note else None,
            "source_kind": note["source_kind"] if note else "artifact",
            "attempts": 0,
        }

        # Standing rule: interview Karthik before drafting about a build.
        if note is None:
            base["status"] = "needs_interview"
            base["review"] = interview_card(run_id, pillar["key"])
            save_record(state_dir, base)
            return base

        privacy.require_safe(source_text, denylist, "source")
        prompt = draft.build_prompt(pillar, reason, material, note)
        privacy.require_safe(prompt, denylist, "prompt")
        text, gate, attempts = generate_checked(prompt, source_text, runner=runner)
        privacy.require_safe(text, denylist, "draft")

        folder = run_dir(state_dir, run_id)
        atomic_write(os.path.join(folder, "prompt.txt"), prompt)
        atomic_write(os.path.join(folder, "source.txt"), source_text)
        atomic_write(os.path.join(folder, "draft.md"), text + "\n")
        atomic_json(os.path.join(folder, "gate.json"), gate)
        base["attempts"] = len(attempts)
        base["status"] = "awaiting_review" if gate["pass"] else "gate_failed"
        base["draft_path"] = os.path.join(folder, "draft.md")
        base["gate_path"] = os.path.join(folder, "gate.json")
        save_record(state_dir, base)
        return base


def transition(state_dir, run_id, action, feedback=None, post_url=None,
               runner=generate.shell_runner, denylist_path=DEFAULT_DENYLIST,
               answer=None, source=None, publishable=False, notes_dir=None,
               delivery_event=None):
    with pipeline_lock(state_dir):
        row = load_record(state_dir, run_id)
        status = row["status"]

        if action == "delivered":
            if not delivery_event:
                raise PipelineError("delivered needs the Buzz event ID")
            if row.get("delivery_event_id"):
                if row["delivery_event_id"] != delivery_event:
                    raise PipelineError("run already delivered in a different Buzz event")
                return row
            row["delivery_event_id"] = delivery_event
            save_record(state_dir, row)
            return row

        if action == "answer":
            if status == "interview_answered":
                return row
            if status != "needs_interview":
                raise PipelineError("answer requires needs_interview, found %s" % status)
            if not source:
                raise PipelineError("answer needs the Buzz event ID as --source")
            if not publishable:
                raise PipelineError(
                    "answer needs --publishable after Karthik explicitly approves public use")
            notes_dir = notes_dir or os.path.join(HERE, "notes")
            denylist = privacy.load_denylist(denylist_path)
            privacy.require_safe(answer or "", denylist, "interview answer")
            path = draft.capture_note(
                notes_dir, row["pillar"], source, "private", answer,
                dt.date.fromisoformat(row["date"]), publishable=True)
            row["status"] = "interview_answered"
            row["captured_note"] = path
            save_record(state_dir, row)
            return row

        if action == "approve":
            if status == "approved":
                return row
            if status != "awaiting_review":
                raise PipelineError("approve requires awaiting_review, found %s" % status)
            row["status"] = "approved"
            save_record(state_dir, row)
            return row

        if action == "reject":
            if status == "rejected":
                return row
            if status not in ("awaiting_review", "approved"):
                raise PipelineError("reject requires awaiting_review or approved, found %s" % status)
            if not feedback:
                raise PipelineError("reject needs feedback")
            row["status"] = "rejected"
            row["feedback"] = feedback
            save_record(state_dir, row)
            return row

        if action == "revise":
            if status not in ("awaiting_review", "rejected", "gate_failed"):
                raise PipelineError("revise requires a reviewable or rejected run, found %s" % status)
            feedback = feedback or row.get("feedback")
            if not feedback:
                raise PipelineError("revise needs feedback")
            folder = run_dir(state_dir, run_id)
            prompt = read_text(os.path.join(folder, "prompt.txt"))
            source = read_text(os.path.join(folder, "source.txt"))
            previous = read_text(os.path.join(folder, "draft.md"))
            denylist = privacy.load_denylist(denylist_path)
            privacy.require_safe(feedback, denylist, "feedback")
            revision_prompt = repair_prompt(
                prompt, previous, gate_result(previous, source), feedback)
            text, gate, attempts = generate_checked(
                revision_prompt, source, runner=runner, feedback=feedback)
            privacy.require_safe(text, denylist, "draft")
            atomic_write(os.path.join(folder, "draft.md"), text + "\n")
            atomic_json(os.path.join(folder, "gate.json"), gate)
            row["version"] = int(row.get("version", 1)) + 1
            row["attempts"] = int(row.get("attempts", 0)) + len(attempts)
            row["feedback"] = feedback
            row["status"] = "awaiting_review" if gate["pass"] else "gate_failed"
            save_record(state_dir, row)
            return row

        if action == "published":
            if status == "published":
                return row
            if status != "approved":
                raise PipelineError("published requires approved, found %s" % status)
            if not post_url:
                raise PipelineError("published needs the X post URL")
            parsed = urllib.parse.urlparse(post_url)
            if (parsed.scheme != "https" or parsed.netloc.lower() not in
                    ("x.com", "www.x.com", "twitter.com", "www.twitter.com")
                    or "/status/" not in parsed.path):
                raise PipelineError("published needs a valid X status URL")
            history = os.path.join(state_dir, "history.json")
            rows = draft.load_history(history)
            history_row = {"date": row["date"], "pillar": row["pillar"]}
            if row.get("note"):
                history_row["note"] = row["note"]
            rows.append(history_row)
            atomic_json(history, rows)
            row["status"] = "published"
            row["post_url"] = post_url
            save_record(state_dir, row)
            return row

        raise PipelineError("unknown action %r" % action)


def delivery_card(row):
    if row["status"] == "needs_interview":
        return row["review"]
    card = {
        "run_id": row["id"],
        "status": row["status"],
        "pillar": row.get("pillar"),
        "attempts": row.get("attempts", 0),
    }
    if row.get("reason"):
        card["reason"] = row["reason"]
    if row.get("delivery_event_id"):
        card["delivery_event_id"] = row["delivery_event_id"]
    if row.get("draft_path") and os.path.exists(row["draft_path"]):
        card["draft"] = read_text(row["draft_path"]).strip()
    if row.get("gate_path") and os.path.exists(row["gate_path"]):
        with open(row["gate_path"]) as f:
            card["gate"] = json.load(f)
    if row["status"] == "awaiting_review":
        card["instructions"] = {
            "approve": "approve %s" % row["id"],
            "reject": "reject %s: <what to change>" % row["id"],
        }
    if row["status"] == "approved":
        card["instruction"] = (
            "Paste it into X. Then reply: published %s <X post URL>" % row["id"])
    if row["status"] == "interview_answered":
        card["instruction"] = "Interview captured. Run the pipeline again to generate the draft."
    return card


def main():
    p = argparse.ArgumentParser(description="Run and manage the X drafting pipeline.")
    p.add_argument("--state-dir", default=DEFAULT_STATE)
    p.add_argument("--denylist", default=DEFAULT_DENYLIST)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    status = sub.add_parser("status")
    status.add_argument("run_id", nargs="?")
    for name in ("answer", "approve", "reject", "revise", "delivered", "published"):
        cmd = sub.add_parser(name)
        cmd.add_argument("run_id")
        if name == "answer":
            cmd.add_argument("--source", required=True)
            cmd.add_argument("--publishable", action="store_true")
        if name in ("reject", "revise"):
            cmd.add_argument("--feedback")
        if name == "published":
            cmd.add_argument("--url")
        if name == "delivered":
            cmd.add_argument("--event", required=True)
    args = p.parse_args()

    try:
        if args.command == "run":
            row = start(state_dir=args.state_dir, denylist_path=args.denylist)
        elif args.command == "status":
            if args.run_id:
                row = load_record(args.state_dir, args.run_id)
            else:
                rows = all_records(args.state_dir)
                row = rows[-1] if rows else {"status": "never_run"}
        else:
            answer = sys.stdin.read() if args.command == "answer" else None
            row = transition(
                args.state_dir, args.run_id, args.command,
                feedback=getattr(args, "feedback", None),
                post_url=getattr(args, "url", None),
                denylist_path=args.denylist,
                answer=answer,
                source=getattr(args, "source", None),
                publishable=getattr(args, "publishable", False),
                delivery_event=getattr(args, "event", None),
            )
        print(json.dumps(delivery_card(row), indent=2))
        return 0
    except (PipelineError, draft.DraftError, generate.GenerateError,
            privacy.PrivacyError, OSError) as e:
        print(json.dumps({"status": "failed", "error": str(e)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
