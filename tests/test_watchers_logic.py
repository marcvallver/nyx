"""Lógica pura de los 5 watchers (sin gi — testeable en CI)."""

from nyx.watchers.eod import eod_summary, seconds_until
from nyx.watchers.repos import diff_prs, snapshot_pr
from nyx.watchers.sessions import detect_collisions, find_root
from nyx.watchers.system import count_failures, kernel_pending
from nyx.watchers.usb import match_usb, offsite_age_days


# --- W1 sessions ---
def test_find_root_walks_up_to_git():
    dirs = {"/home/m/proj/.git"}
    assert find_root("/home/m/proj/src/deep", isdir=lambda p: p in dirs) == "/home/m/proj"


def test_find_root_no_git_returns_path():
    assert find_root("/tmp/x", isdir=lambda p: False) == "/tmp/x"


def test_collision_two_sessions_same_root():
    entries = [("sid-a", "/repo", 100.0), ("sid-b", "/repo", 110.0)]
    assert detect_collisions(entries, window_s=120, now=120.0) == ["/repo"]


def test_no_collision_different_roots_or_same_sid():
    # worktrees = roots distintos → NO colisión
    assert detect_collisions(
        [("a", "/repo", 100.0), ("b", "/repo-wt1", 110.0)], 120, 120.0) == []
    # la misma sesión escribiendo dos veces tampoco
    assert detect_collisions(
        [("a", "/repo", 100.0), ("a", "/repo", 110.0)], 120, 120.0) == []


def test_collision_window_expires():
    entries = [("a", "/repo", 0.0), ("b", "/repo", 500.0)]
    assert detect_collisions(entries, window_s=120, now=500.0) == []


# --- W2 repos ---
def _pr(num=1, author="marcvallver", title="t", checks=()):
    return {
        "number": num, "title": title, "author": {"login": author},
        "statusCheckRollup": [
            {"name": n, "status": "COMPLETED", "conclusion": c} for n, c in checks
        ],
        "reviewDecision": "",
    }


def test_snapshot_green_ignoring_known_broken_check():
    pr = _pr(checks=[("build", "SUCCESS"), ("gitleaks", "FAILURE")])
    snap = snapshot_pr(pr, ignore_checks=["gitleaks"])
    assert snap["green"] is True and snap["failing"] == []
    snap2 = snapshot_pr(pr, ignore_checks=[])
    assert snap2["green"] is False and snap2["failing"] == ["gitleaks"]


def test_snapshot_pending_not_green():
    pr = _pr(checks=[("build", "SUCCESS")])
    pr["statusCheckRollup"].append({"name": "e2e", "status": "IN_PROGRESS"})
    assert snapshot_pr(pr, [])["green"] is False


def test_diff_new_pr_from_partner_nudges():
    curr = {"42": snapshot_pr(_pr(42, author="marcsola", title="Hero"), [])}
    nudges = diff_prs({}, curr, "marcvallver", "/repo", "--admin")
    assert len(nudges) == 1 and "marcsola" in nudges[0].text and "#42" in nudges[0].text


def test_diff_own_green_transition_proposes_merge():
    prev = {"7": snapshot_pr(_pr(7, checks=[("build", "FAILURE")]), [])}
    curr = {"7": snapshot_pr(_pr(7, checks=[("build", "SUCCESS")]), [])}
    nudges = diff_prs(prev, curr, "marcvallver", "/repo", "--admin --squash")
    assert len(nudges) == 1
    assert nudges[0].action.command == "gh pr merge 7 --admin --squash"
    assert nudges[0].action.cwd == "/repo"
    assert nudges[0].mood == "glad"


def test_diff_stable_green_no_renudge():
    snap = {"7": snapshot_pr(_pr(7, checks=[("build", "SUCCESS")]), [])}
    assert diff_prs(snap, snap, "marcvallver", "/repo", "") == []


def test_diff_new_red_alerts_once_per_check():
    prev = {"7": snapshot_pr(_pr(7, checks=[("build", "SUCCESS")]), [])}
    curr = {"7": snapshot_pr(_pr(7, checks=[("build", "FAILURE")]), [])}
    nudges = diff_prs(prev, curr, "marcvallver", "/repo", "")
    assert len(nudges) == 1 and nudges[0].mood == "alert" and "build" in nudges[0].text


def test_diff_first_sight_own_green_nudges():
    curr = {"9": snapshot_pr(_pr(9, checks=[("build", "SUCCESS")]), [])}
    nudges = diff_prs({}, curr, "marcvallver", "/repo", "--admin")
    assert len(nudges) == 1 and nudges[0].key == "pr:green:9"


def test_status_context_shape_supported():
    pr = _pr()
    pr["statusCheckRollup"] = [{"context": "ci/legacy", "state": "failure"}]
    snap = snapshot_pr(pr, [])
    assert snap["failing"] == ["ci/legacy"]


# --- W3 usb ---
def test_match_usb_model_or_label_case_insensitive():
    assert match_usb("Seagate One Touch HDD", "", "one touch") is True
    assert match_usb("", "ONETOUCH-BK", "onetouch") is True
    assert match_usb("Kingston DataTraveler", "PENDRIVE", "one touch") is False
    assert match_usb("Seagate", "x", "") is False  # patrón vacío nunca matchea


def test_offsite_age_days():
    assert offsite_age_days(None, now=1000.0) is None
    assert offsite_age_days(0.0, now=86400.0 * 3) == 3.0
    assert offsite_age_days(1000.0, now=500.0) == 0.0  # reloj raro → 0, no negativo


# --- W4 system ---
def test_kernel_pending_when_running_dir_gone():
    assert kernel_pending("6.18.35-1-lts", ["6.19.1-1-lts"]) is True
    assert kernel_pending("6.18.35-1-lts", ["6.18.35-1-lts", "6.19.1-1"]) is False
    assert kernel_pending("", ["6.19"]) is False  # sin release → nunca


def test_count_failures_parses_valid_lines():
    out = (
        "marc:\n"
        "When                Type  Source                                           Valid\n"
        "2026-06-11 10:02:11 RHOST 100.73.98.37                                         V\n"
        "2026-06-11 10:02:19 RHOST 100.73.98.37                                         V\n"
        "2026-06-11 10:03:01 RHOST 100.73.98.37                                         I\n"
    )
    assert count_failures(out) == 2
    assert count_failures("") == 0
    assert count_failures("marc:\nWhen Type Source Valid\n") == 0


# --- W5 eod ---
def test_seconds_until_today_and_tomorrow():
    assert seconds_until("19:30", 19, 0, 0) == 1800
    assert seconds_until("19:30", 20, 0, 0) == 86400 - 1800
    assert seconds_until("basura", 19, 0, 0) == 1800  # fallback 19:30


def test_eod_summary_variants():
    assert eod_summary([], any_activity=True) is None
    assert eod_summary(["fulgor"], any_activity=False) is None
    assert eod_summary(["fulgor"], any_activity=True) == (
        "`fulgor` con trabajo sin commitear. /cierre-sesion pendiente.")
    two = eod_summary(["fulgor", "dotfiles"], any_activity=True)
    assert "`fulgor` y `dotfiles`" in two