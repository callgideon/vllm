#!/usr/bin/env python3
"""Self-check of check-stack.py on a synthetic git repo: python3 .bitlane/test_check_stack.py (no network)."""
import importlib.util, os, pathlib, subprocess, tempfile

spec = importlib.util.spec_from_file_location("cs", pathlib.Path(__file__).with_name("check-stack.py"))
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)


def sh(*a):
    return subprocess.run(a, check=True, capture_output=True, text=True).stdout.strip()


def commit(path, msg):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(p.read_text() + "x\n" if p.exists() else "x\n")
    sh("git", "add", "-A")
    sh("git", "commit", "-q", "-m", msg)
    return sh("git", "rev-parse", "HEAD")


def errors(base):
    report, ok = cs.check(base, sh("git", "rev-parse", "HEAD"), prs=False)
    return ok, report


with tempfile.TemporaryDirectory() as d:
    os.chdir(d)
    sh("git", "init", "-q", "-b", "main")
    sh("git", "config", "user.email", "t@t"), sh("git", "config", "user.name", "t")
    base = commit("vllm/a.py", "upstream")
    commit("vllm/b.py", "[bitlane] fix b\n\nUpstream: https://github.com/vllm-project/vllm/pull/1")
    commit(".bitlane/x.py", "[bitlane] ci\n\nBitlane-only: our CI")
    commit("tests/test_b.py", "[bitlane] test\n\nWhy: x\nUpstream: https://github.com/vllm-project/vllm/pull/2")
    ok, report = errors(base)
    assert ok and "Stack: 3 commits" in report and "Hygiene: PASS" in report, report

    for path, msg, expect in [
        ("vllm/c.py", "fix c\n\nBitlane-only: x", "subject must start"),
        ("vllm/c.py", "[bitlane] fix c", "needs a trailer"),
        ("vllm/c.py", "[bitlane] fix c\n\nUpstream: https://github.com/other/repo/pull/3", "must be a vllm-project"),
        ("csrc/k.cu", "[bitlane] kernel\n\nBitlane-only: x", "not an overlay file"),
        ("vllm/data.json", "[bitlane] data\n\nBitlane-only: x", "not an overlay file"),
        ("csrc/k.cu", "[bitlane] kernel\n\nBitlane-only: x\nBinary-change: yes", "needs a full vLLM build"),
        (".github/workflows/upstream.yml", "[bitlane] ci\n\nBitlane-only: x", "not an overlay file"),
    ]:
        top = sh("git", "rev-parse", "HEAD")
        commit(path, msg)
        ok, report = errors(base)
        assert not ok and expect in report, (msg, report)
        sh("git", "reset", "-q", "--hard", top)

    top = sh("git", "rev-parse", "HEAD")  # a merge commit in the stack
    sh("git", "checkout", "-q", "-b", "side", base)
    commit("vllm/s.py", "[bitlane] side\n\nBitlane-only: x")
    sh("git", "checkout", "-q", "main")
    sh("git", "merge", "-q", "--no-ff", "-m", "[bitlane] merge\n\nBitlane-only: x", "side")
    ok, report = errors(base)
    assert not ok and "merge commit" in report, report
    sh("git", "reset", "-q", "--hard", top)

    # GitHub's PR merge commit: allowed, but the PR's own commits still pass or fail on their own (PR #3, 2026-10-20)
    for side_msg, ok_want in [("[bitlane] side\n\nBitlane-only: x", True), ("side without trailer", False)]:
        sh("git", "checkout", "-q", "-B", "side", base)
        commit("vllm/s.py", side_msg)
        sh("git", "checkout", "-q", "main")
        sh("git", "merge", "-q", "--no-ff", "-m", "Merge pull request #3 from callgideon/side", "side")
        ok, report = errors(base)
        assert ok == ok_want, (side_msg, report)
        sh("git", "reset", "-q", "--hard", top)

    # merged upstream and already in the base: the patch should have dropped
    cs.pr_state = lambda n: ("merged", base)
    report, ok = cs.check(base, top, prs=True)
    assert not ok and "is merged in the base" in report, report
    cs.pr_state = lambda n: ("closed", None)
    report, ok = cs.check(base, top, prs=True)
    assert ok and "closed without merge" in report, report
print("check-stack self-check: OK")
