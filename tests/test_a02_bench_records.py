"""A-02 partial plumbing: fake scoring only, not a benchmark result."""

from bench.records import aggregate, score_patch, swebench_prediction

PATCH = b"diff --git a/file b/file\nnew file mode 100644\nindex 0000000..1234567\n--- /dev/null\n+++ b/file\n@@ -0,0 +1 @@\n+hello\n"


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def score(self, task_id, patch):
        self.calls.append((task_id, patch))
        return True


def test_fake_scores_exact_patch_bytes(tmp_path):
    path = tmp_path / "patch.diff"
    path.write_bytes(PATCH)
    runtime = FakeRuntime()
    row = score_patch("fixture-1", path, runtime)
    assert row["resolved"] is True
    assert runtime.calls == [("fixture-1", PATCH)]
    assert len(row["patch_sha256"]) == 64


def test_swebench_wire_format(tmp_path):
    path = tmp_path / "patch.diff"
    path.write_bytes(PATCH)
    assert swebench_prediction("repo__issue-1", "fixed-model", path) == {
        "instance_id": "repo__issue-1",
        "model_name_or_path": "fixed-model",
        "model_patch": PATCH.decode(),
    }


def test_unknown_values_are_not_measured_zero():
    result = aggregate(
        [{"resolved": None}, {"resolved": True, "cost_measured": False, "cost_usd": 0}]
    )
    assert result["scored"] == 1 and result["unscored"] == 1
    assert result["cost_usd"] is None and result["cost_skipped_runs"] == 2
    assert aggregate([])["resolved_percent"] is None
