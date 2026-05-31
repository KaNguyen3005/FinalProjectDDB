from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_phase_0_scaffold_paths_exist():
    expected_paths = [
        "src/log",
        "src/node",
        "src/checkpoint",
        "src/crash",
        "src/recovery",
        "src/integrity",
        "api/routers",
        "api/websocket",
        "benchmark",
        "data_gen",
        "ui/css",
        "ui/js",
        "ui/demo.html",
        "ui/benchmark.html",
        "ui/logs.html",
        "docs/design_document.md",
        "docs/analysis_report.md",
        "docs/demo_script.md",
        "docs/presentation_outline.md",
        "results/raw",
        "results/charts",
        "docs/diagrams",
    ]

    missing = [path for path in expected_paths if not (ROOT / path).exists()]

    assert missing == []


def test_project_entry_files_exist():
    expected_files = [
        "README.md",
        "requirements.txt",
        "pytest.ini",
        "run.py",
        "roadmap.md",
    ]

    missing = [path for path in expected_files if not (ROOT / path).is_file()]

    assert missing == []
