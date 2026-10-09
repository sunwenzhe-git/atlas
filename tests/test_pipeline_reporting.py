from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PKG_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import atlas_report  # noqa: E402
import sync_cloud_issues_to_vault  # noqa: E402


def test_format_markdown_contains_all_sections() -> None:
    body = atlas_report.format_markdown(
        title="嵌套路由解析盲区",
        kind="design-conflict",
        conflict="子路由未继承前缀",
        context="FastAPI 全栈项目",
        proposal="增加递归前缀传递",
        evidence="404 Not Found",
    )
    assert "### 📌 流水线自感知上报 (Pipeline RFC)" in body
    assert "design-conflict" in body
    assert "子路由未继承前缀" in body
    assert "FastAPI 全栈项目" in body
    assert "增加递归前缀传递" in body
    assert "404 Not Found" in body


def test_save_offline_creates_valid_file(tmp_path: Path) -> None:
    title = "测试离线保存"
    body = "这是一份测试内容"
    saved = atlas_report.save_offline(tmp_path, title, body)
    assert saved.exists()
    assert saved.parent == tmp_path / "product" / "atlas-reports"
    assert saved.read_text(encoding="utf-8") == body
    assert saved.name.startswith("RFC-")
    assert saved.name.endswith(".md")


def test_generate_note_id_format() -> None:
    nid = sync_cloud_issues_to_vault.generate_note_id(1)
    assert len(nid) == 16
    assert nid.isdigit()


def test_sync_issue_to_note_creates_card(tmp_path: Path) -> None:
    atlas_dir = tmp_path / "atlas"
    atlas_dir.mkdir(parents=True)
    issue = {
        "number": 42,
        "title": "累加链测试与播种结构性冲突",
        "body": "长流程中每用例运行期重置导致前序草稿丢失",
        "html_url": "https://github.com/sunwenzhe-git/atlas/issues/42",
        "user": {"login": "test-collaborator"},
    }
    created = sync_cloud_issues_to_vault.sync_issue_to_note(issue, atlas_dir, 1)
    assert created is not None
    assert created.exists()
    content = created.read_text(encoding="utf-8")
    assert 'kind: proposal' in content
    assert 'issue_number: 42' in content
    assert 'reporter: test-collaborator' in content
    assert "累加链测试与播种结构性冲突" in content

    # 第二次同步相同 issue 应该幂等返回 None（防止重复建卡片）
    again = sync_cloud_issues_to_vault.sync_issue_to_note(issue, atlas_dir, 1)
    assert again is None


def test_cli_report_help() -> None:
    res = subprocess.run([sys.executable, str(SCRIPTS_DIR / "atlas_report.py"), "--help"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "atlas 流水线缺陷与设计冲突自感知上报工具" in res.stdout
