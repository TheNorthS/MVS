import ast
from pathlib import Path


def test_sdk_imports_stay_in_infrastructure():
    for path in Path("src/mvs").rglob("*.py"):
        if "infrastructure/mcp" in path.as_posix():
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("mcp"), path
            if isinstance(node, ast.Import):
                assert not any(alias.name.startswith("mcp") for alias in node.names), path


def test_no_dynamic_execution_or_os_shell():
    for path in Path("src/mvs").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                assert node.func.id not in {"eval", "exec"}, path
            if isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"create_subprocess_shell", "subprocess_shell"}, path
            assert not any(
                arg.arg == "shell" and isinstance(arg.value, ast.Constant) and arg.value.value
                for arg in node.keywords
            ), path
