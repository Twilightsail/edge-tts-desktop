"""生成第三方许可声明 frontend/public/third-party-notices.txt。

覆盖随安装包分发的三类依赖：后端 Python（打进 EXE）、前端 npm（打进页面）、外壳 Rust crate（编进应用），
外加 ffmpeg（独立可执行文件）。每个依赖的名称/版本/许可证，以及它自带的许可证全文（相同文本合并）。

用法（在仓库根目录，使用后端虚拟环境的 Python）：
    backend\\.venv\\Scripts\\python.exe scripts\\gen_notices.py [--contact "邮箱或网址"]
"""

import argparse
import hashlib
import importlib.metadata as md
import json
import re
import subprocess
import sys
import tomllib
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "public" / "third-party-notices.txt"
LICENSE_FILE = re.compile(r"^(licen[sc]e|copying|notice|copyright|authors)([-_.].*)?$", re.I)
PLACEHOLDER = "[请发布者填写]"
# SPDX 许可证清单仓库里的标准文本（与 FSF 发布的全文一致）
SPDX = "https://raw.githubusercontent.com/spdx/license-list-data/main/text/"


def fetch(url: str) -> str:
    """用 curl 下载（比 urllib 更能适应系统代理/证书设置），失败重试两次。"""
    for attempt in range(3):
        result = subprocess.run(["curl", "-sSL", "--fail", "-m", "60", url], capture_output=True)
        if result.returncode == 0 and result.stdout:
            return result.stdout.decode("utf-8", errors="replace")
    raise RuntimeError(f"无法下载 {url}")


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def read_texts(directory: Path, depth: int = 1) -> list[tuple[str, str]]:
    """读取目录下（及 licenses 子目录）的许可证类文件。"""
    found = []
    candidates = [p for p in directory.iterdir() if p.is_file()] if directory.is_dir() else []
    for sub in ("licenses", "LICENSES", "license"):
        if (directory / sub).is_dir():
            candidates += [p for p in (directory / sub).rglob("*") if p.is_file()]
    for path in candidates:
        if LICENSE_FILE.match(path.name) or path.parent.name.lower() in ("licenses", "license"):
            try:
                found.append((path.name, path.read_text(encoding="utf-8", errors="replace").strip()))
            except OSError:
                pass
    return found


# ---------------- Python ----------------
def python_packages() -> list[dict]:
    project = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    roots = [re.split(r"[ ;<>=!~\[(]", r)[0] for r in project["project"]["dependencies"]]
    seen: dict[str, md.Distribution] = {}

    def walk(name: str):
        key = norm(name)
        if key in seen:
            return
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            return
        seen[key] = dist
        for requirement in dist.requires or []:
            if "extra ==" not in requirement:
                walk(re.split(r"[ ;<>=!~\[(]", requirement)[0])

    for root in roots:
        walk(root)
    result = []
    for dist in seen.values():
        meta = dist.metadata
        license_name = (meta.get("License-Expression") or meta.get("License") or "").strip().split("\n")[0]
        if not license_name or len(license_name) > 60:
            classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
            license_name = "; ".join(classifiers) or "见许可证全文"
        texts = []
        for file in dist.files or []:
            if LICENSE_FILE.match(file.name) or "licenses" in file.parts:
                try:
                    texts.append((file.name, dist.locate_file(file).read_text(encoding="utf-8", errors="replace").strip()))
                except OSError:
                    pass
        url = meta.get("Home-page") or next((u.split(",")[-1].strip() for u in meta.get_all("Project-URL") or []), "")
        result.append({"eco": "Python", "name": meta["Name"], "version": dist.version, "license": license_name, "url": url, "texts": texts})
    return result


# ---------------- npm ----------------
def npm_packages() -> list[dict]:
    modules = ROOT / "frontend" / "node_modules"
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    seen: dict[str, dict] = {}

    def locate(name: str) -> Path | None:
        path = modules / name
        return path if (path / "package.json").is_file() else None

    def walk(name: str):
        path = locate(name)
        if path is None or name in seen:
            return
        meta = json.loads((path / "package.json").read_text(encoding="utf-8"))
        license_field = meta.get("license") or meta.get("licenses") or "见许可证全文"
        if isinstance(license_field, list):
            license_field = " OR ".join(item.get("type", "?") for item in license_field)
        elif isinstance(license_field, dict):
            license_field = license_field.get("type", "?")
        repo = meta.get("repository")
        url = repo.get("url", "") if isinstance(repo, dict) else (repo or meta.get("homepage", ""))
        seen[name] = {"eco": "前端 (npm)", "name": name, "version": meta.get("version", ""), "license": str(license_field), "url": url, "texts": read_texts(path)}
        for dependency in meta.get("dependencies", {}):
            walk(dependency)

    for dependency in package.get("dependencies", {}):
        walk(dependency)
    return list(seen.values())


# ---------------- Rust ----------------
def rust_packages() -> list[dict]:
    manifest = ROOT / "desktop" / "src-tauri" / "Cargo.toml"
    raw = subprocess.run(
        ["cargo", "metadata", "--format-version", "1", "--manifest-path", str(manifest), "--filter-platform", "x86_64-pc-windows-msvc"],
        capture_output=True, text=True, check=True, encoding="utf-8",
    ).stdout
    data = json.loads(raw)
    resolved = {n["id"] for n in data["resolve"]["nodes"]}
    result = []
    for package in data["packages"]:
        if package["id"] not in resolved or package["name"] == "edge-tts-desktop":
            continue
        result.append({
            "eco": "外壳 (Rust)", "name": package["name"], "version": package["version"],
            "license": package.get("license") or "见许可证全文", "url": package.get("repository") or package.get("homepage") or "",
            "texts": read_texts(Path(package["manifest_path"]).parent),
        })
    return result


# ---------------- ffmpeg ----------------
def ffmpeg_info() -> tuple[str, str]:
    import imageio_ffmpeg

    out = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-version"], capture_output=True, text=True).stdout
    lines = out.splitlines()
    return lines[0], next((l for l in lines if l.startswith("configuration:")), "")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--contact", default=PLACEHOLDER, help="发布者联系方式（GPL/LGPL 要求的源码获取途径）")
    parser.add_argument("--license", dest="own_license", default=PLACEHOLDER, help="本软件自身的许可，如 \"MIT（见仓库根目录 LICENSE 文件）\"")
    parser.add_argument("--source", default=PLACEHOLDER, help="本软件源码与构建说明的公开地址（仓库网址）")
    args = parser.parse_args()
    print("收集 Python 依赖…", file=sys.stderr)
    packages = python_packages()
    print("收集 npm 依赖…", file=sys.stderr)
    packages += npm_packages()
    print("收集 Rust 依赖（cargo metadata）…", file=sys.stderr)
    packages += rust_packages()
    ffmpeg_version, ffmpeg_config = ffmpeg_info()

    # 发布包里没带许可证文件的依赖：用 SPDX 的标准文本兜底（版权人以其项目主页为准）
    generic: dict[str, str] = {}
    for p in packages:
        if p["texts"]:
            continue
        for spdx_id in re.findall(r"[A-Za-z0-9.+-]+", p["license"]):
            if spdx_id in ("MIT", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause", "MPL-2.0", "ISC", "Zlib"):
                if spdx_id not in generic:
                    generic[spdx_id] = fetch(SPDX + spdx_id + ".txt").strip()
                p["texts"] = [(f"{spdx_id}（通用文本，版权人见项目主页）", generic[spdx_id])]
                break

    print("下载许可证全文…", file=sys.stderr)
    gpl3 = fetch(SPDX + "GPL-3.0-only.txt").strip()
    lgpl3 = fetch(SPDX + "LGPL-3.0-only.txt").strip()

    out = []
    out.append("""第三方软件与许可声明（Edge TTS 桌面版）
======================================================================
本软件自身的许可：%(l)s
本软件源码与构建说明：%(src)s
发布者联系方式（索取源码、反馈问题）：%(c)s

本软件使用并随安装包分发了下列第三方软件。它们各自的版权归其作者所有，使用须遵守各自的许可证。
本文件由 scripts/gen_notices.py 自动生成。

----------------------------------------------------------------------
一、需要特别说明的组件
----------------------------------------------------------------------

[1] FFmpeg —— GNU GPL v3
    随安装包分发的 ffmpeg.exe（由 imageio-ffmpeg 提供，gyan.dev 的 essentials 构建）：
      %(fv)s
      %(fc)s
    该构建启用了 --enable-gpl 与 --enable-version3，整体适用 GNU 通用公共许可证第 3 版（GPL-3.0）。
    本软件以“独立进程”方式调用 ffmpeg.exe（仅用于解码和拼接音频），不与其链接，其余代码不因此受 GPL 约束。
    按 GPL 要求，您有权获得 ffmpeg 的对应源码：
      · FFmpeg 官方源码：https://ffmpeg.org/releases/
      · 该构建的说明与构建信息：https://www.gyan.dev/ffmpeg/builds/
      · 或向发布者索取（见上方联系方式），发布者将在合理期限内提供。
    GPL-3.0 许可证全文见本文件第四部分。

[2] edge-tts —— GNU LGPL v3
    本软件的后端使用 edge-tts 库（https://github.com/rany2/edge-tts），未做任何修改。
    按 LGPL-3.0 要求：您有权修改该库，并用修改后的版本替换本软件使用的版本；
    本软件后端为 Python 程序，源码与构建说明（含如何替换 edge-tts 并重新打包）公开在：%(src)s
    LGPL-3.0 许可证全文见本文件第四部分。

[3] certifi —— MPL-2.0
    certifi 使用 Mozilla 公共许可证 2.0。其源码未经修改，可从 https://github.com/certifi/python-certifi 获取。

[4] Microsoft Edge WebView2 运行时
    界面由系统的 WebView2 运行时渲染，它是 Microsoft 的软件，不随本软件分发；
    若系统缺少，安装程序会引导从 Microsoft 获取。

[5] 在线语音服务（非软件许可，但使用时需知晓）
    · “Edge 在线语音”引擎通过 edge-tts 访问微软 Edge 浏览器“朗读”功能所用的服务。这是非官方、未受微软支持的接口，
      可能随时变化或被限制，使用须自行遵守微软的服务条款。
    · “Azure”引擎使用 Azure AI Speech 官方接口，需要使用者自己的订阅密钥，计费与条款以 Azure 为准。
    · 两个引擎都会把您要合成的文本发送给微软的服务器。

""" % {"c": args.contact, "l": args.own_license, "src": args.source, "fv": ffmpeg_version, "fc": ffmpeg_config})

    out.append("----------------------------------------------------------------------\n二、依赖清单\n----------------------------------------------------------------------\n")
    by_eco = defaultdict(list)
    for package in packages:
        by_eco[package["eco"]].append(package)
    for eco, items in by_eco.items():
        out.append(f"\n【{eco}】共 {len(items)} 个\n")
        for p in sorted(items, key=lambda p: p["name"].lower()):
            out.append(f"  {p['name']} {p['version']} — {p['license']}" + (f"  <{p['url']}>" if p["url"] else ""))
    counts = defaultdict(int)
    for p in packages:
        counts[p["license"]] += 1

    out.append("\n----------------------------------------------------------------------\n三、各依赖自带的许可证全文（相同文本合并）\n----------------------------------------------------------------------\n")
    groups: dict[str, dict] = {}
    for p in packages:
        for filename, text in p["texts"]:
            if not text:
                continue
            key = hashlib.sha256(re.sub(r"\s+", " ", text).encode()).hexdigest()
            group = groups.setdefault(key, {"text": text, "users": []})
            tag = f"{p['name']} {p['version']}"
            if tag not in group["users"]:
                group["users"].append(tag)
    missing = [f"{p['name']} {p['version']}（{p['license']}）" for p in packages if not p["texts"]]
    for group in sorted(groups.values(), key=lambda g: g["users"][0].lower()):
        out.append("\n" + "=" * 70 + "\n适用于：" + "、".join(group["users"]) + "\n" + "=" * 70 + "\n" + group["text"] + "\n")
    if missing:
        out.append("\n以下依赖的发布包中未附带许可证文件，请按其许可证标识（见第二部分）和项目主页获取全文：\n  " + "\n  ".join(sorted(missing)) + "\n")

    out.append("\n----------------------------------------------------------------------\n四、GNU 许可证全文\n----------------------------------------------------------------------\n")
    out.append("\n" + "=" * 70 + "\nGNU GENERAL PUBLIC LICENSE Version 3（适用于 FFmpeg）\n" + "=" * 70 + "\n" + gpl3 + "\n")
    out.append("\n" + "=" * 70 + "\nGNU LESSER GENERAL PUBLIC LICENSE Version 3（适用于 edge-tts）\n" + "=" * 70 + "\n" + lgpl3 + "\n")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"已生成 {OUT}（{OUT.stat().st_size // 1024} KB，{len(packages)} 个依赖，{len(groups)} 份不同的许可证文本）", file=sys.stderr)
    print("许可证分布：", dict(sorted(counts.items(), key=lambda kv: -kv[1])[:12]), file=sys.stderr)
    if PLACEHOLDER in (args.contact, args.own_license, args.source):
        print("提示：--contact / --license / --source 有未提供的项，文件里仍是占位符，正式发布前必须填写。", file=sys.stderr)


if __name__ == "__main__":
    main()
