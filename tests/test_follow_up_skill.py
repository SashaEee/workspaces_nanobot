"""Навык ``follow_up`` — отдельный MCP-процесс (см. openspec/changes/add-follow-up-skill).

Что здесь закреплено:

* SKILL.md разбирается фронтматтером и виден агенту всегда (``always: true``);
* в ``config.json`` статичный блок ``tools.mcpServers.follow_up`` — без путей
  конкретной машины, команда — лаунчер внутри папки навыка;
* навык объявлен в единственном реестре ``project.json::skills``;
* код сервера лежит в папке навыка, и лаунчер находит его без настройки;
* лаунчер — только стандартная библиотека; если кода нет, выходит с кодом 3
  и **ничего не пишет в stdout** (это канал JSON-RPC gateway'я);
* код навыка изолирован: не импортирует проект и не импортируется им,
  его ``requirements.txt`` не спорит с корневым, линтер проекта его не
  проверяет (сопровождается в репозитории Follow Up).

Поведение самого навыка здесь не тестируется — у него свой набор тестов.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.conftest import REPO_ROOT

SKILL_DIR = REPO_ROOT / "workspace" / "skills" / "follow_up"
LAUNCHER_REL = "workspace/skills/follow_up/scripts/follow_up_mcp"
LAUNCHER = REPO_ROOT / LAUNCHER_REL


def _strip_jsonc(text: str) -> str:
    no_line = re.sub(r"(?<!:)//.*$", "", text, flags=re.MULTILINE)
    return re.sub(r"/\*.*?\*/", "", no_line, flags=re.DOTALL)


def _frontmatter() -> dict:
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    assert m, "SKILL.md без фронтматтера"
    return yaml.safe_load(m.group(1))


# ── SKILL.md ───────────────────────────────────────────────────────

def test_skill_md_frontmatter_matches_the_directory_name():
    meta = _frontmatter()
    assert meta["name"] == "follow_up"
    assert meta["description"]
    nanobot_meta = meta["metadata"]
    if isinstance(nanobot_meta, str):
        nanobot_meta = json.loads(nanobot_meta)
    assert nanobot_meta["nanobot"]["always"] is True


def test_skill_md_names_only_tools_the_server_exposes():
    """Имена в SKILL.md — ``mcp_<сервер>_<инструмент>``; набор фиксирован
    контрактом навыка. Лишнее имя — обещание агенту, которое не сдержим."""
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    named = set(re.findall(r"mcp_follow_up_([a-z_]+)", text))
    assert named == {"ask", "hypotheses", "deviations", "status",
                     "card_start", "card_status", "forget"}


def test_skill_md_draws_the_line_with_audit_analyzer():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "audit_analyzer" in text


# ── реестры ────────────────────────────────────────────────────────

def test_config_json_block_is_static():
    cfg = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
    block = cfg["tools"]["mcpServers"]["follow_up"]
    assert block == {"type": "stdio", "command": LAUNCHER_REL,
                     "args": [], "tool_timeout": 120}
    # Ни абсолютных путей, ни ${VAR}: неизвестная переменная валит
    # resolve_config_env_vars у nanobot-ai на старте.
    assert "${" not in json.dumps(block) and not Path(block["command"]).is_absolute()


def test_project_json_declares_the_skill_once():
    data = json.loads(_strip_jsonc((REPO_ROOT / "project.json").read_text(encoding="utf-8")))
    assert data["skills"]["follow_up"] == {"enabled": True}


# ── лаунчер ────────────────────────────────────────────────────────

def test_launcher_uses_only_the_standard_library():
    tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= set(sys.stdlib_module_names), imported - set(sys.stdlib_module_names)


def test_launcher_has_a_windows_wrapper():
    assert (LAUNCHER.parent / "follow_up_mcp.cmd").read_bytes().startswith(b"@echo off")


@pytest.fixture
def launcher_copy(tmp_path: Path) -> Path:
    """Копия лаунчера в чистом дереве: на машине разработчика рядом с
    настоящим может лежать follow_up.env.local."""
    skill = tmp_path / "nb" / "workspace" / "skills" / "follow_up" / "scripts"
    skill.mkdir(parents=True)
    dst = skill / "follow_up_mcp"
    dst.write_bytes(LAUNCHER.read_bytes())
    return dst


def _clean_env() -> dict:
    return {k: v for k, v in os.environ.items()
            if not k.startswith("FOLLOW_UP_") and k != "MODELS_DEVICE"}


def test_unconfigured_launcher_exits_3_and_keeps_stdout_clean(launcher_copy):
    r = subprocess.run([sys.executable, str(launcher_copy)], capture_output=True,
                       text=True, env=_clean_env())
    assert r.returncode == 3
    assert r.stdout == ""
    assert "follow_up.env.local" in r.stderr


def test_where_explains_what_is_missing(launcher_copy):
    r = subprocess.run([sys.executable, str(launcher_copy), "--where"],
                       capture_output=True, text=True, env=_clean_env())
    info = json.loads(r.stdout)
    assert r.returncode == 3 and info["ok"] is False and info["problems"]
    # NANOBOT_HOME — корень нанобота, вычислен от расположения лаунчера.
    assert info["nanobot_home"] == str(launcher_copy.parents[4])


def test_local_file_configures_the_launcher(launcher_copy, tmp_path):
    root = tmp_path / "follow_up"
    (root / "backend" / "skill").mkdir(parents=True)
    (root / "backend" / "skill" / "mcp_server.py").write_text("", encoding="utf-8")
    (launcher_copy.parent.parent / "follow_up.env.local").write_text(
        f"FOLLOW_UP_ROOT={root}\nFOLLOW_UP_PYTHON={sys.executable}\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(launcher_copy), "--where"],
                       capture_output=True, text=True, env=_clean_env())
    info = json.loads(r.stdout)
    assert r.returncode == 0, info
    assert info["mode"] == "отдельный клон"
    assert info["root"] == str(root) and info["python"] == sys.executable
    assert info["models_device"] == "cpu"


# ── код навыка в папке навыка ──────────────────────────────────────

def test_bundled_server_is_found_without_configuration():
    """Ни follow_up.env.local, ни переменных: код рядом — лаунчер готов."""
    assert (SKILL_DIR / "backend" / "skill" / "mcp_server.py").is_file()
    r = subprocess.run([sys.executable, str(LAUNCHER), "--where"],
                       capture_output=True, text=True, env=_clean_env())
    info = json.loads(r.stdout)
    if info["local_file_exists"]:
        pytest.skip("на этой машине есть follow_up.env.local — он важнее")
    assert r.returncode == 0, info
    assert info["mode"] == "встроенный код"
    assert Path(info["root"]) == SKILL_DIR.resolve()
    assert info["python"]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module)
    return out


def test_skill_code_does_not_import_the_project():
    project = ("lib", "workspace", "gateway", "config", "cli_agent", "streamlit_app")
    offenders = {
        str(p.relative_to(REPO_ROOT)): sorted(m for m in _imports(p)
                                              if m.split(".")[0] in project)
        for p in (SKILL_DIR / "backend").rglob("*.py")
    }
    assert not {k: v for k, v in offenders.items() if v}


def test_project_does_not_import_the_skill_code():
    offenders = []
    for d in ("lib", "workspace/tools", "workspace/utils"):
        for p in (REPO_ROOT / d).rglob("*.py"):
            if any(m.split(".")[0] == "backend" or "skills.follow_up" in m
                   for m in _imports(p)):
                offenders.append(str(p.relative_to(REPO_ROOT)))
    assert not offenders


def _requirement_names(path: Path) -> set[str]:
    names = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            names.add(re.split(r"[\[<>=!~ ;]", line, maxsplit=1)[0].lower().replace("_", "-"))
    return names


def test_skill_requirements_do_not_repin_root_packages():
    """Версии общих пакетов задаёт корневой requirements.txt, а не навык."""
    shared = (_requirement_names(SKILL_DIR / "requirements.txt")
              & _requirement_names(REPO_ROOT / "requirements.txt"))
    assert not shared


def test_project_linter_leaves_the_skill_code_to_its_repository():
    text = (SKILL_DIR / "ruff.toml").read_text(encoding="utf-8")
    assert 'extend = "../../../pyproject.toml"' in text
    assert re.search(r'extend-exclude\s*=\s*\["backend"\]', text)


def test_skill_runtime_data_is_ignored():
    ignored = (SKILL_DIR / ".gitignore").read_text(encoding="utf-8").split()
    assert {"data/", "logs/", "models/", "follow_up.env.local"} <= set(ignored)
