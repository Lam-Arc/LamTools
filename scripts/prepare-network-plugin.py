"""user:“建议还是集成一下吧，尽量不把这些安装操作留给用户”+(打包前自动构建控制器、下载并校验内核，缺失时构建失败而非交给用户安装)。"""
import importlib.util
import asyncio
from pathlib import Path
import shutil
import subprocess
import os
import hashlib
import tempfile

root = Path(__file__).resolve().parents[1]
plugin = root / 'core/src/lamtools_core/plugins/bundled/network-exploration'


def publish_ui_assets(source: Path, destination: Path) -> None:
    # user:“测试，提交打包发布”+(先完整生成，再替换资源，避免原地截断正在被映射读取的模块)。
    assets = {'page.mjs': (source / 'page.mjs').read_bytes()}
    # The current entry inlines CSS; retain support for a separate sheet if a
    # future build emits one, without requiring it for an inline-style bundle.
    if (source / 'style.css').is_file():
        assets['style.css'] = (source / 'style.css').read_bytes()
    for name, content in assets.items():
        target = destination / name
        if target.is_file() and target.read_bytes() == content:
            continue
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination, prefix=name, suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
            temporary.replace(target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def main():
    # user:“界面太狗屎 打回重做”+(Vue 源界面在分发前构建成浏览器可直接加载的模块和独立样式)。
    with tempfile.TemporaryDirectory(prefix='sunday-network-ui-') as build_dir:
        subprocess.run(['npm.cmd' if os.name == 'nt' else 'npm', 'exec', '--', 'vite', 'build', '--config', 'vite.config.network-plugin.ts'], cwd=root / 'core/ui', env={**os.environ, 'SUNDAY_NETWORK_UI_OUTDIR': build_dir}, check=True)
        publish_ui_assets(Path(build_dir), plugin / 'ui')
    module_spec = importlib.util.spec_from_file_location('sunday_engine_build', plugin / 'engine_install.py')
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    asyncio.run(module.prepare_bundle())
    subprocess.run(['cargo', 'build', '--locked', '--release', '--manifest-path', str(plugin / 'controller/Cargo.toml'), '--target-dir', str(root / '.build/network-controller')], check=True)
    (plugin / 'bin').mkdir(exist_ok=True)
    # user:“修完打包发布新版本”+(相同产物复用，避免正在运行的开发版控制器使重复打包失败)。
    compiled = root / '.build/network-controller/release/sunday-network-controller.exe'
    destination = plugin / 'bin/sunday-network-controller.exe'
    if not destination.is_file() or hashlib.sha256(compiled.read_bytes()).digest() != hashlib.sha256(destination.read_bytes()).digest():
        shutil.copyfile(compiled, destination)


if __name__ == "__main__":
    main()
