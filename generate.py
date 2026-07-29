#!/usr/bin/env python3
"""Loop 2, final step: turn the prompt into a draft.

This is deliberately the thinnest module in the repo. Everything that decides
whether a post is honest happens before it, in `draft.py`, and everything that
decides whether a draft is publishable happens after it, in `check.py`. This
part only moves text through a model.

It shells out to the `claude` CLI rather than calling an HTTP API, so it needs
no API key and no SDK: it reuses whatever credentials the CLI already has. The
model command is injectable, so the tests exercise every path in here without
ever calling a model.

Usage:
    python3 draft.py | python3 generate.py > draft.md
    python3 generate.py --prompt-file prompt.txt --out draft.md
    python3 generate.py --dry-run < prompt.txt

Exit codes: 0 ok, 1 hard failure, 4 the model produced nothing usable.
"""

import argparse
import os
import shutil
import subprocess
import sys

EMPTY_OUTPUT = 4
DEFAULT_CMD = ("claude", "-p")
DEFAULT_TIMEOUT = 300


class GenerateError(Exception):
    pass


def shell_runner(prompt, cmd=DEFAULT_CMD, timeout=DEFAULT_TIMEOUT):
    """Send the prompt to the model command on stdin and return its stdout."""
    if shutil.which(cmd[0]) is None:
        raise GenerateError(
            "%r is not on PATH. Install it, or pass --cmd with something that "
            "reads a prompt on stdin and writes the post to stdout." % cmd[0])
    try:
        done = subprocess.run(list(cmd), input=prompt, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise GenerateError("%s produced nothing after %ds" % (cmd[0], timeout))
    if done.returncode != 0:
        detail = (done.stderr or "").strip().splitlines()
        raise GenerateError("%s exited %d%s" % (
            cmd[0], done.returncode, ": " + detail[-1] if detail else ""))
    return done.stdout


def unwrap(text):
    """Strip a fence wrapping the whole reply.

    Only a fence, and only when it wraps everything. A model that ignored "return
    the post text and nothing else" and wrote a preamble is a real problem, and
    tidying that away here would hide it from the gate and from me. Fences are
    the one habit worth absorbing, because they change nothing about the words.
    """
    lines = text.strip().splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text.strip()


def generate(prompt, runner=shell_runner):
    if not prompt or not prompt.strip():
        raise GenerateError("empty prompt: nothing to send")
    draft = unwrap(runner(prompt))
    if not draft:
        # Distinct exit code: an empty reply is a model or credential problem,
        # not a draft that failed the gate, and the two need different fixes.
        raise GenerateError("the model returned nothing")
    return draft


def main():
    p = argparse.ArgumentParser(description="Turn a DRAFT prompt into a post.")
    p.add_argument("--prompt-file", help="prompt to send (default: stdin)")
    p.add_argument("--out", help="write the draft here (default: stdout)")
    p.add_argument("--cmd", help="model command, default 'claude -p'")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    p.add_argument("--dry-run", action="store_true",
                   help="report what would be run, without calling a model")
    args = p.parse_args()

    try:
        prompt = (open(args.prompt_file).read() if args.prompt_file
                  else sys.stdin.read())
        cmd = tuple(args.cmd.split()) if args.cmd else DEFAULT_CMD

        if args.dry_run:
            print("would run: %s" % " ".join(cmd), file=sys.stderr)
            print("prompt: %d chars, %d lines" % (len(prompt),
                                                  len(prompt.splitlines())),
                  file=sys.stderr)
            return 0

        draft = generate(prompt, lambda text: shell_runner(text, cmd, args.timeout))
    except GenerateError as e:
        print("generate: %s" % e, file=sys.stderr)
        return EMPTY_OUTPUT if "returned nothing" in str(e) else 1
    except OSError as e:
        print("generate: %s" % e, file=sys.stderr)
        return 1

    if args.out:
        with open(args.out, "w") as f:
            f.write(draft + "\n")
        print("wrote %s (%d chars)" % (args.out, len(draft)), file=sys.stderr)
    else:
        sys.stdout.write(draft + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
