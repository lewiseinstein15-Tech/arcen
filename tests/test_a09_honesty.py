"""A-09: docs do not advertise unsupported catalog sizes or lazy file reads."""

from pathlib import Path


def test_documentation_does_not_claim_unverified_catalog_sizes():
    root = Path(__file__).resolve().parents[1]
    for name in ("README.md", "docs/ARCHITECTURE.md", "docs/BACKEND-SPEC.md"):
        text = (root / name).read_text()
        for claim in ("500+ sub-agents", "10,000+ skills", "300+ MCPs", "100+ plugins"):
            assert claim not in text
    assert "reads each whole file" in (root / "README.md").read_text()
