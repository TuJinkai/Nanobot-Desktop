"""nanobot Desktop 一键构建编排。

完整流程：
    1. 构建 WebUI            (bun run build → nanobot/web/dist)
    2. 构建 nanobot wheel     (避免在 bundle 里编译构建后端)
    3. 制作嵌入式 Python bundle(embeddable 发行版，自包含可分发)
    4. 构建 Pake 桌面窗口     (需 Rust + VS Build Tools，由 build_pake_env.ps1 执行)
    5. 生成 NSIS 安装包       (makensis)

用法::

    python desktop/scripts/build_all.py
    python desktop/scripts/build_all.py --skip-pake      # 无 Rust/VS 时跳过
    python desktop/scripts/build_all.py --skip-installer
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

# Force UTF-8 on stdout/stderr so the Chinese step labels and ✓/✗ markers
# survive a GBK Windows console (otherwise print() raises UnicodeEncodeError
# and masks the real build error).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

ROOT = Path(__file__).resolve().parent.parent.parent
DESKTOP = ROOT / "desktop"
WEBUI = ROOT / "webui"
OUTPUT = DESKTOP / "output"

PYTHON_EMBED_URL = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"


def step(name: str) -> None:
    print(f"\n{'=' * 60}\n  {name}\n{'=' * 60}\n")


def run(cmd: list[str], cwd: Path | None = None) -> int:
    # Resolve the executable via PATH so npm/.cmd shims (e.g. `bun` → bun.cmd on
    # Windows) are found — CreateProcess won't search PATHEXT or launch a .cmd
    # directly.  Script shims are wrapped in `cmd /c`; real .exe get their full
    # path.  Everything else is left untouched (so `python -c "…; …"` keeps its
    # semicolon instead of being split by a shell).
    exe = shutil.which(cmd[0])
    if exe:
        if exe.lower().endswith((".cmd", ".bat")):
            cmd = ["cmd", "/c", exe, *cmd[1:]]
        else:
            cmd = [exe, *cmd[1:]]
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=str(cwd or ROOT)).returncode


def _which(name: str) -> str | None:
    return shutil.which(name)


# ---------------------------------------------------------------------------
# 1. WebUI
# ---------------------------------------------------------------------------


def build_webui() -> bool:
    step("1/5 — 构建 nanobot WebUI")
    if not (WEBUI / "node_modules").exists():
        if run(["bun", "install"], cwd=WEBUI) != 0:
            return False
    if run(["bun", "run", "build"], cwd=WEBUI) != 0:
        return False
    dist = ROOT / "nanobot" / "web" / "dist"
    ok = (dist / "index.html").exists()
    print(f"  {'OK' if ok else 'FAIL'}: {dist}")
    return ok


# ---------------------------------------------------------------------------
# 2. nanobot wheel
# ---------------------------------------------------------------------------


def build_wheel() -> bool:
    step("2/5 — 构建 nanobot wheel（避免在 bundle 内编译构建后端）")
    wheels = OUTPUT / "wheels"
    wheels.mkdir(parents=True, exist_ok=True)
    if run([sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-cache-dir", "-w", str(wheels)]) != 0:
        return False
    found = list(wheels.glob("nanobot_ai-*.whl"))
    print(f"  OK: {found[0].name if found else '无 wheel!'}")
    return bool(found)


# ---------------------------------------------------------------------------
# 3. 嵌入式 Python bundle（自包含、可分发；不要用 venv）
# ---------------------------------------------------------------------------


def build_python_bundle() -> bool:
    step("3/5 — 制作嵌入式 Python bundle")
    import zipfile

    bundle = OUTPUT / "python-bundle"
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)

    zip_path = OUTPUT / "python-embed.zip"
    if not zip_path.exists():
        print(f"  下载 {PYTHON_EMBED_URL}")
        urllib.request.urlretrieve(PYTHON_EMBED_URL, zip_path)

    print("  解压 embeddable...")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(bundle)

    # 启用 site-packages：取消注释 import site，并加上 Lib\site-packages
    pth_files = list(bundle.glob("python*._pth"))
    if not pth_files:
        print("  FAIL: 找不到 *._pth")
        return False
    pth = pth_files[0]
    pth.write_text(
        "python312.zip\n.\nLib\\site-packages\n\nimport site\n",
        encoding="utf-8",
    )

    # bootstrap pip
    get_pip = bundle / "get-pip.py"
    urllib.request.urlretrieve(GET_PIP_URL, get_pip)
    py = str(bundle / "python.exe")
    if run([py, str(get_pip), "--no-warn-script-location"]) != 0:
        return False
    get_pip.unlink()

    # 安装 nanobot wheel + 全部依赖（用 bundle 自己的 pip，禁用用户站点防污染）
    env = {**__import__("os").environ, "PYTHONNOUSERSITE": "1"}
    wheel = next((OUTPUT / "wheels").glob("nanobot_ai-*.whl"))
    print(f"  安装 {wheel.name} 及依赖（可能需要几分钟）...")
    rc = subprocess.run(
        [py, "-m", "pip", "install", "--no-warn-script-location", str(wheel)],
        env=env,
    ).returncode
    if rc != 0:
        return False

    # 校验
    check = subprocess.run(
        [py, "-c", "import nanobot; print('nanobot', nanobot.__version__)"], env=env
    )
    ok = check.returncode == 0
    print(f"  {'OK' if ok else 'FAIL'}: nanobot 可在 bundle 内导入")
    return ok


# ---------------------------------------------------------------------------
# 4. Pake（需 Rust + VS Build Tools，委托给 PowerShell 脚本）
# ---------------------------------------------------------------------------


def build_pake() -> bool:
    step("4/5 — 构建 Pake 桌面窗口（需 Rust + VS Build Tools）")
    ps1 = DESKTOP / "scripts" / "build_pake_env.ps1"
    rc = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(ps1)]
    ).returncode
    print(f"  {'OK' if rc == 0 else 'FAIL（确认已装 VS Build Tools VCTools）'}")
    return rc == 0


# ---------------------------------------------------------------------------
# 5. NSIS 安装包
# ---------------------------------------------------------------------------


def build_installer() -> bool:
    step("5/5 — 生成 Windows 安装包 (NSIS)")
    makensis = _which("makensis")
    if not makensis:
        print("  FAIL: 找不到 makensis，装 NSIS 3.x")
        return False
    rc = subprocess.run(
        [
            makensis,
            f"/DOUTPUT_DIR={OUTPUT}",
            f"/DASSETS_DIR={DESKTOP / 'assets'}",
            f"/DBACKEND_DIR={DESKTOP / 'backend'}",
            f"/DLICENSE_PATH={ROOT / 'LICENSE'}",
            str(DESKTOP / "installer" / "nanobot-desktop.nsi"),
        ]
    ).returncode
    exes = sorted(OUTPUT.glob("nanobot-desktop-setup-*.exe"))
    exe = exes[-1] if exes else (OUTPUT / "nanobot-desktop-setup.exe")
    print(f"  {'OK' if rc == 0 and exe.exists() else 'FAIL'}: {exe}")
    return rc == 0 and exe.exists()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="构建 nanobot Desktop")
    ap.add_argument("--skip-webui", action="store_true")
    ap.add_argument("--skip-pake", action="store_true")
    ap.add_argument("--skip-python", action="store_true")
    ap.add_argument("--skip-installer", action="store_true")
    args = ap.parse_args()

    OUTPUT.mkdir(parents=True, exist_ok=True)

    stages = [
        ("webui", args.skip_webui, build_webui),
        ("wheel", False, build_wheel),
        ("python", args.skip_python, build_python_bundle),
        ("pake", args.skip_pake, build_pake),
        ("installer", args.skip_installer, build_installer),
    ]
    for name, skip, fn in stages:
        if skip:
            print(f"\n  跳过: {name}")
            continue
        if not fn():
            print(f"\n  ✗ 构建失败于: {name}")
            return 1

    print(f"\n{'=' * 60}\n  ✓ nanobot Desktop 构建完成！\n  产物: {OUTPUT}\n{'=' * 60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
