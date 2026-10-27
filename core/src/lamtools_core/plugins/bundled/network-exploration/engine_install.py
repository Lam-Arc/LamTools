"""user:“有任何需要下载的资源你都可以直接下到e盘”+(外部内核按需下载、固定版本、校验来源和哈希；不会随应用强制分发)。"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import zipfile

import httpx

ENGINES = {
    'aria2': {'binary': 'aria2c', 'repo': 'aria2/aria2', 'version': 'release-1.37.0', 'asset': 'aria2-1.37.0-win-64bit-build1.zip', 'sha256': '67d015301eef0b612191212d564c5bb0a14b5b9c4796b76454276a4d28d9b288', 'license': 'GPL-2.0-or-later', 'checksum_source': 'https://github.com/microsoft/winget-pkgs/blob/master/manifests/a/aria2/aria2/1.37.0/aria2.aria2.installer.yaml'},
    'mihomo': {'binary': 'mihomo', 'repo': 'MetaCubeX/mihomo', 'version': 'v1.19.33', 'asset': 'mihomo-windows-amd64-compatible-v1.19.33.zip', 'sha256': '7aaf636a4f2172dcd8ec34ac4f52797b059195e5afd6409508c963e545f8864d', 'license': 'GPL-3.0', 'checksum_source': 'https://api.github.com/repos/MetaCubeX/mihomo/releases/tags/v1.19.33'},
}


async def install_engine(data_dir: Path, params: dict):
    key = params.get('engine')
    if key not in ENGINES:
        raise ValueError('请选择 aria2 或 mihomo')
    spec = ENGINES[key]
    binary = spec['binary']
    destination = data_dir / 'engines'
    destination.mkdir(parents=True, exist_ok=True)
    source = params.get('path')
    url = f"https://github.com/{spec['repo']}/releases/download/{spec['version']}/{spec['asset']}"
    if source:
        # Local import accepts the original pinned archive, not an unverified executable.
        path = Path(source)
        if not path.is_absolute() or path.stat().st_size > 60 * 1024 * 1024:
            raise ValueError('请选择小于 60 MB 的官方 ZIP 绝对路径')
        archive = await asyncio.to_thread(path.read_bytes)
    else:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30, trust_env=False) as client:
            async with client.stream('GET', url) as response:
                response.raise_for_status()
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(chunks) + len(chunk) > 60 * 1024 * 1024:
                        raise ValueError('内核下载超过大小限制')
                    chunks.extend(chunk)
                archive = bytes(chunks)
    if hashlib.sha256(archive).hexdigest() != spec['sha256']:
        raise ValueError('官方内核 ZIP 校验失败，未安装或执行')
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        candidates = [entry for entry in bundle.infolist() if Path(entry.filename).name.lower().endswith('.exe')]
        if len(candidates) != 1 or candidates[0].file_size > 80 * 1024 * 1024:
            raise ValueError('内核压缩包结构不符合预期')
        executable = bundle.read(candidates[0])
    if not executable.startswith(b'MZ'):
        raise ValueError('内核不是有效的 Windows 程序')
    temporary = destination / f'{binary}.next'
    await asyncio.to_thread(temporary.write_bytes, executable)
    os.replace(temporary, destination / f'{binary}.exe')
    receipt = {**spec, 'source': url, 'binary_sha256': hashlib.sha256(executable).hexdigest()}
    await asyncio.to_thread((destination / f'{binary}.receipt.json').write_text, json.dumps(receipt, indent=2), encoding='utf-8')
    return {'installed': key, 'version': spec['version'], 'license': spec['license']}


async def ensure_bundled_engine(root: Path, data_dir: Path, key: str):
    # user:“建议还是集成一下吧，尽量不把这些安装操作留给用户”+(从随插件提供的已验证文件自动准备运行副本)。
    import shutil
    spec = ENGINES[key]
    binary = spec['binary']
    source = root / 'resources' / 'engines'
    receipt_path = source / f'{binary}.receipt.json'
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    if receipt.get('sha256') != spec['sha256'] or receipt.get('version') != spec['version']:
        raise ValueError('随插件提供的内核版本不匹配，请重新构建插件')
    expected = receipt['binary_sha256']
    destination = data_dir / 'engines'
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f'{binary}.exe'
    if target.is_file() and await asyncio.to_thread(lambda: hashlib.sha256(target.read_bytes()).hexdigest()) == expected:
        await asyncio.to_thread(shutil.copyfile, receipt_path, destination / receipt_path.name)
        return
    bundled = source / f'{binary}.exe'
    if await asyncio.to_thread(lambda: hashlib.sha256(bundled.read_bytes()).hexdigest()) != expected:
        raise ValueError('随插件提供的内核校验失败')
    temporary = destination / f'{binary}.next'
    await asyncio.to_thread(shutil.copyfile, bundled, temporary)
    os.replace(temporary, target)
    await asyncio.to_thread(shutil.copyfile, receipt_path, destination / receipt_path.name)


async def prepare_bundle():
    data_dir = Path(__file__).resolve().parent / 'resources'
    for key in ENGINES:
        spec = ENGINES[key]
        existing = data_dir / 'engines' / f"{spec['binary']}.receipt.json"
        if existing.is_file():
            receipt = json.loads(existing.read_text(encoding='utf-8'))
            executable = data_dir / 'engines' / f"{spec['binary']}.exe"
            if executable.is_file() and receipt.get('sha256') == spec['sha256'] and hashlib.sha256(executable.read_bytes()).hexdigest() == receipt.get('binary_sha256') and (data_dir / 'engines' / f'{key}.LICENSE.txt').is_file():
                print(f'Verified bundled {key}')
                continue
        await install_engine(data_dir, {'engine': key})
        spec = ENGINES[key]
        async with httpx.AsyncClient(follow_redirects=True, timeout=30, trust_env=False) as client:
            response = await client.get(f"https://api.github.com/repos/{spec['repo']}/contents/COPYING?ref={spec['version']}" if key == 'aria2' else f"https://api.github.com/repos/{spec['repo']}/contents/LICENSE?ref={spec['version']}", headers={'User-Agent': 'Sunday-Network-Build'})
            response.raise_for_status()
            import base64
            license_text = base64.b64decode(response.json()['content'])
        (data_dir / 'engines' / f'{key}.LICENSE.txt').write_bytes(license_text)
        print(f"Prepared {key} {spec['version']} ({spec['license']})")


if __name__ == '__main__':
    asyncio.run(prepare_bundle())
