"""user:“建议还是集成一下吧，尽量不把这些安装操作留给用户”+(打包前自动构建控制器、下载并校验内核，缺失时构建失败而非交给用户安装)。"""
import importlib.util
import asyncio
from pathlib import Path
import shutil
import subprocess
import os
import hashlib

root = Path(__file__).resolve().parents[1]
plugin = root / 'core/src/lamtools_core/plugins/bundled/network-exploration'
# user:“界面太狗屎 打回重做”+(Vue 源界面在分发前构建成浏览器可直接加载的模块和独立样式)。
subprocess.run(['npm.cmd' if os.name == 'nt' else 'npm', 'exec', '--', 'vite', 'build', '--config', 'vite.config.network-plugin.ts'], cwd=root / 'core/ui', check=True)
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
