"""user:“QQ…哔哩哔哩…单开一个插件项目”+(构建独立发布包与带摘要的 GitHub 市场目录，排除运行数据)。"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

PLUGINS = ("qq-bot", "bili-scroll")
EXCLUDED_DIRS = {"data", ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "target", "dist"}
EXCLUDED_FILES = {"values.json", "values.jsonc", "settings.json", "settings.jsonc", ".env", "cookies.json", "credentials.json", "secrets.json"}


def distributable(path, root):
    parts = path.relative_to(root).parts
    return not any(part in EXCLUDED_DIRS or part.startswith(".env") for part in parts) and path.name not in EXCLUDED_FILES and path.suffix not in {".pyc", ".log", ".db", ".sqlite", ".lock"}


def build(root, output, tag):
    output.mkdir(parents=True, exist_ok=True)
    catalog = {"format": 1, "repository": "Lam-Arc/Sunday-Plugins", "plugins": []}
    for name in PLUGINS:
        folder = root / "plugins" / name
        manifest = json.loads((folder / "plugin.json").read_text(encoding="utf-8-sig"))
        if manifest["name"] != name:
            raise ValueError("unexpected plugin identity")
        if not (folder / "LICENSE").is_file() or not (folder / "NOTICE.md").is_file():
            raise ValueError(f"missing license/attribution for {name}")
        archive = output / f"{name}-{manifest['version']}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(folder.rglob("*")):
                if path.is_file() and distributable(path, folder):
                    if path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):
                        raise ValueError("plugin package cannot follow external links")
                    bundle.write(path, f"{name}/{path.relative_to(folder).as_posix()}")
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        catalog["plugins"].append({"id": name, "version": manifest["version"], "url": f"https://github.com/Lam-Arc/Sunday-Plugins/releases/download/{tag}/{archive.name}", "sha256": digest, "size": archive.stat().st_size})
    (output / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "SHA256SUMS").write_text("\n".join(f"{row['sha256']}  {row['url'].rsplit('/', 1)[-1]}" for row in catalog["plugins"]) + "\n", encoding="utf-8")
    return catalog


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    if not args.tag.startswith("plugins-") or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for c in args.tag):
        parser.error("tag must be a plugins-* release tag")
    print(json.dumps(build(args.root, args.output, args.tag), ensure_ascii=False))
