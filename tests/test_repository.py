"""Repository-level checks: README structure, Markdown links and tracked-file hygiene."""

import re
import shutil
import subprocess
from urllib.parse import unquote

import pytest

import config
from conftest import PROJECT_ROOT

README = PROJECT_ROOT / "README.md"
README_SECTIONS = [
    "Dashboard preview", "Main features", "Technology stack", "Key results (seed 42)",
    "KPI definitions and classification rules", "Power BI dashboard", "Project workflow",
    "Getting started", "How to use and manually test the project", "Automated testing",
    "Repository structure", "Limitations", "Project status",
]
DASHBOARD_PAGES = ["Referral Overview", "Leakage & Service Performance", "Turnaround Time & Data Quality"]
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")
MACHINE_PATH = re.compile(r"(?i)\b[a-z]:\\(?!\.venv)|\b[a-z]:/|/Users/[^/\s]+|/home/[^/\s]+|\\Users\\[^\\\s]+")
STALE_WORDING = re.compile(r"(?i)not (?:been )?(?:built|created) yet|does not exist yet|\|\s*in progress\b|"
                           r"\|\s*planned\s*\||phases? \d\w?\)? (?:is |are )?(?:planned|in progress)")


def readme():
    return README.read_text(encoding="utf-8")


def tracked_files():
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    result = subprocess.run(["git", "ls-files"], cwd=PROJECT_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip("not a Git checkout")
    return [PROJECT_ROOT / name for name in result.stdout.splitlines()]


def markdown_files():
    return sorted(set(PROJECT_ROOT.glob("*.md")) | set((PROJECT_ROOT / "powerbi").glob("*.md"))
                  | set((PROJECT_ROOT / "sql").glob("*.md")))


def heading_anchor(heading):
    """GitHub's anchor for a Markdown heading."""
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return text.replace(" ", "-")


def anchors(path):
    text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
    return {heading_anchor(h) for h in re.findall(r"^#{1,6} (.+)$", text, re.MULTILINE)}


def test_readme_sections_appear_in_order():
    headings = re.findall(r"^## (.+)$", readme(), re.MULTILINE)
    assert [h for h in headings if h in README_SECTIONS] == README_SECTIONS
    assert readme().startswith("# Healthcare Referral Leakage Analytics\n")


def test_readme_has_one_subsection_and_screenshot_per_dashboard_page():
    text = readme()
    dashboard = text[text.index("## Power BI dashboard"):text.index("## Project workflow")]
    for page in DASHBOARD_PAGES:
        assert f"### {page}" in dashboard, page
    for screenshot in config.POWERBI_SCREENSHOTS:
        assert f"]({screenshot})" in dashboard, screenshot
    preview = text[text.index("## Dashboard preview"):text.index("## Main features")]
    assert f"]({config.POWERBI_SCREENSHOTS[0]})" in preview


def test_readme_states_the_synthetic_data_notice_before_any_section():
    intro = readme().split("\n## ", 1)[0].lower()
    for phrase in ["synthetic data notice", "fictional", "no real patient", "portfolio and educational use",
                   "clinical decision-making"]:
        assert phrase in intro, phrase


@pytest.mark.parametrize("path", markdown_files(), ids=lambda p: p.relative_to(PROJECT_ROOT).as_posix())
def test_markdown_links_and_images_resolve(path):
    text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
    for target in MARKDOWN_LINK.findall(text):
        if re.match(r"(?i)https?://|mailto:", target):
            continue
        file_part, _, anchor = unquote(target).partition("#")
        linked = (path.parent / file_part).resolve() if file_part else path
        assert linked.exists(), f"{target} in {path.name}"
        if anchor and linked.suffix == ".md":
            assert anchor in anchors(linked), f"{target} in {path.name}"


def test_readme_documents_the_tracked_powerbi_files_that_exist():
    for relative in re.findall(r"(?:powerbi|sql|tests|screenshots)/[\w.-]+\.\w+", readme()):
        assert (PROJECT_ROOT / relative).is_file(), relative


def test_readme_documents_the_windows_test_command():
    text = readme()
    assert ".\\.venv\\Scripts\\python.exe -m pytest -q" in text
    for script in ["generate_data.py", "prepare_data.py", "analyze_data.py", "prepare_powerbi_data.py"]:
        assert f".\\.venv\\Scripts\\python.exe {script}" in text, script
        assert (PROJECT_ROOT / script).is_file(), script
    assert (PROJECT_ROOT / "requirements.txt").is_file()


def test_every_phase_is_complete_and_no_stale_status_remains():
    phases = re.findall(r"^\| (\d) \| .+ \| (\w[\w ]*) \|$", readme(), re.MULTILINE)
    assert [number for number, _ in phases] == ["1", "2", "3", "4", "5"]
    assert all(status == "Complete" for _, status in phases), phases
    for path in markdown_files():
        assert not STALE_WORDING.search(path.read_text(encoding="utf-8")), path.name


def test_tracked_text_files_contain_no_machine_specific_paths():
    for path in tracked_files():
        if path.suffix.lower() in {".pbix", ".png"} or "powerbi/data" in path.as_posix():
            continue
        text = path.read_text(encoding="utf-8")
        match = MACHINE_PATH.search(text)
        assert match is None, f"{path.relative_to(PROJECT_ROOT).as_posix()}: {match.group(0) if match else ''}"
