"""user:“放手去做吧”+(原版画图文件在 Sunday 工作区可安全读写并保留外部修改)。"""
import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[2] / 'plugins/excalidraw/vault.py'
spec = importlib.util.spec_from_file_location('excalidraw_vault_acceptance', PATH)
vault = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vault)


def test_original_markdown_round_trip_and_conflict(tmp_path):
    path = tmp_path / '子目录' / 'drawing.excalidraw.md'
    path.parent.mkdir()
    original = '---\nexcalidraw-plugin: parsed\n---\n用户文字\n\n# Drawing\n```json\n{"elements":[]}\n```\n'
    vault.write_text(tmp_path, '子目录/drawing.excalidraw.md', original, None)
    assert vault.read_text(tmp_path, '子目录/drawing.excalidraw.md') == original
    changed = original.replace('用户文字', '保留原始文字')
    vault.write_text(tmp_path, '子目录/drawing.excalidraw.md', changed, original)
    path.write_text('外部修改', encoding='utf-8')
    with pytest.raises(vault.ConflictError):
        vault.write_text(tmp_path, '子目录/drawing.excalidraw.md', original, changed)
    assert path.read_text(encoding='utf-8') == '外部修改'


def test_paths_cannot_escape_workspace(tmp_path):
    outside = tmp_path.parent / 'outside.excalidraw.md'
    for path in ('../outside.excalidraw.md', str(outside)):
        with pytest.raises(ValueError):
            vault.write_text(tmp_path, path, 'content', None)
    assert not outside.exists()


def test_create_and_deleted_file_conflicts(tmp_path):
    path = tmp_path / 'x.md'
    path.write_text('keep', encoding='utf-8')
    with pytest.raises(vault.ConflictError):
        vault.write_text(tmp_path, 'x.md', 'replace', None)
    path.unlink()
    with pytest.raises(vault.ConflictError):
        vault.write_text(tmp_path, 'x.md', 'replace', 'keep')
    assert not path.exists()

@pytest.mark.asyncio
async def test_file_operations_run_through_the_plugin_host(tmp_path):
    from lamtools_core.app import OperationCatalog
    from lamtools_core.plugin_system import PluginHost
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations

    plugin_root = PATH.parent.parent
    host = PluginHost(roots=[plugin_root], state_path=tmp_path / 'host-state.json')
    catalog = OperationCatalog()
    assembly = register_plugin_operations(catalog, host)
    assert not assembly.errors
    root = tmp_path / 'workspace'
    root.mkdir()
    # user:“FileNotFoundError: [Errno 2] No such file or directory”+(缺失画图返回明确状态，不暴露底层异常)。
    missing = await catalog.execute('excalidraw.file.read', {'work_root': str(root), 'path': 'drawing.excalidraw'})
    assert missing.status == 'ok' and missing.payload == {'missing': True}
    initial = '---\nexcalidraw-plugin: parsed\n---\n\n# Drawing\n'
    created = await catalog.execute('excalidraw.file.write', {
        'work_root': str(root), 'path': 'example.excalidraw.md', 'content': initial, 'original': None,
    })
    assert created.status == 'ok', created.payload
    read = await catalog.execute('excalidraw.file.read', {'work_root': str(root), 'path': 'example.excalidraw.md'})
    assert read.status == 'ok' and read.payload['content'] == initial
    (root / 'example.excalidraw.md').write_text('outside edit', encoding='utf-8')
    conflict = await catalog.execute('excalidraw.file.write', {
        'work_root': str(root), 'path': 'example.excalidraw.md', 'content': 'draft', 'original': initial,
    })
    assert conflict.status == 'error'
    assert (root / 'example.excalidraw.md').read_text(encoding='utf-8') == 'outside edit'

@pytest.mark.asyncio
async def test_canvas_page_is_declared_and_served_by_host(tmp_path):
    from lamtools_core.app import OperationCatalog
    from lamtools_core.plugin_system import PluginHost
    from lamtools_core.plugin_system.operations import register_plugin_system_operations
    from lamtools_core.plugin_system.assets import resolve_plugin_asset

    host = PluginHost(roots=[PATH.parent.parent], state_path=tmp_path / 'state.json')
    catalog = OperationCatalog()
    register_plugin_system_operations(catalog, host)
    result = await catalog.execute('plugin.system.ui', {})
    page = next(p for p in result.payload['pages'] if p['plugin'] == 'excalidraw')
    assert page['entry_url'].endswith('/excalidraw/assets/ui/page.mjs')
    assert resolve_plugin_asset(host, 'excalidraw', 'ui/page.mjs').is_file()

@pytest.mark.asyncio
async def test_markdown_image_assets_round_trip_through_host(tmp_path):
    import base64
    from lamtools_core.app import OperationCatalog
    from lamtools_core.plugin_system import PluginHost
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    host = PluginHost(roots=[PATH.parent.parent], state_path=tmp_path / 'host-state.json')
    catalog = OperationCatalog(); register_plugin_operations(catalog, host)
    root = tmp_path / 'workspace'; root.mkdir()
    raw = b'\x89PNG\r\n\x1a\nfixture bytes'
    encoded = 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii')
    saved = await catalog.execute('excalidraw.asset.put', {'work_root':str(root),'dataURL':encoded})
    assert saved.status == 'ok', saved.payload
    path = saved.payload['path']
    assert path.startswith('.excalidraw-assets/') and path.endswith('.png')
    assert (root / path).read_bytes() == raw
    read = await catalog.execute('excalidraw.asset.read', {'work_root':str(root),'path':path})
    assert read.status == 'ok' and read.payload['dataURL'] == encoded
    bad = await catalog.execute('excalidraw.asset.read', {'work_root':str(root),'path':'../elsewhere.png'})
    assert bad.status == 'error'
    bad_type = await catalog.execute('excalidraw.asset.put', {'work_root':str(root),'dataURL':'data:text/html;base64,PGh0bWw+'})
    assert bad_type.status == 'error'

@pytest.mark.asyncio
async def test_original_markdown_can_read_existing_workspace_image(tmp_path):
    import base64
    from lamtools_core.app import OperationCatalog
    from lamtools_core.plugin_system import PluginHost
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    host=PluginHost(roots=[PATH.parent.parent],state_path=tmp_path/'state.json')
    catalog=OperationCatalog();register_plugin_operations(catalog,host)
    root=tmp_path/'workspace';(root/'notes').mkdir(parents=True)
    raw=b'\x89PNG\r\n\x1a\nexisting';(root/'notes'/'图片.png').write_bytes(raw)
    result=await catalog.execute('excalidraw.asset.read',{'work_root':str(root),'path':'图片.png','drawingPath':'notes/test.excalidraw.md'})
    assert result.status=='ok',result.payload
    assert result.payload['dataURL']=='data:image/png;base64,'+base64.b64encode(raw).decode('ascii')
    assert result.payload['path']=='notes/图片.png'

@pytest.mark.asyncio
async def test_plugin_file_association_is_advertised_and_validated(tmp_path):
    from lamtools_core.app import OperationCatalog
    from lamtools_core.plugin_system import PluginHost
    from lamtools_core.plugin_system.operations import register_plugin_system_operations
    host=PluginHost(roots=[PATH.parent.parent],state_path=tmp_path/'state.json')
    catalog=OperationCatalog();register_plugin_system_operations(catalog,host)
    result=await catalog.execute('plugin.system.ui',{})
    page=next(x for x in result.payload['pages'] if x['plugin']=='excalidraw')
    assert page['file_extensions']==['.excalidraw.md','.excalidraw']

def test_plugin_file_extensions_reject_paths_and_empty_values(tmp_path):
    import json
    from lamtools_core.plugin_system.manifest import load_manifest
    from lamtools_core.plugin_system.ui import read_ui
    root=tmp_path/'unsafe';root.mkdir();(root/'page.mjs').write_text('export function mount(){}')
    for value in (['../secret'],['.md/abc'],[''],['.md','.MD']):
        (root/'plugin.json').write_text(json.dumps({'name':'unsafe','version':'1','ui':{'pages':[{'id':'x','entry':'./page.mjs','fileExtensions':value}]}}))
        with pytest.raises(Exception,match='fileExtensions'):
            read_ui(load_manifest(root/'plugin.json'))

@pytest.mark.asyncio
async def test_internal_link_resolution_is_scoped_to_workspace(tmp_path):
    from lamtools_core.app import OperationCatalog
    from lamtools_core.plugin_system import PluginHost
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    root=tmp_path/'workspace';(root/'notes').mkdir(parents=True);(root/'notes'/'文档.md').write_text('content',encoding='utf8')
    host=PluginHost(roots=[PATH.parent.parent],state_path=tmp_path/'state.json');catalog=OperationCatalog();register_plugin_operations(catalog,host)
    result=await catalog.execute('excalidraw.link.resolve',{'work_root':str(root),'path':'文档.md','drawingPath':'notes/画图.excalidraw.md'})
    assert result.status=='ok' and Path(result.payload['path']) == (root/'notes'/'文档.md').resolve()
    denied=await catalog.execute('excalidraw.link.resolve',{'work_root':str(root),'path':'../../outside.md','drawingPath':'notes/画图.excalidraw.md'})
    assert denied.status=='error'

@pytest.mark.asyncio
async def test_vault_style_basename_links_resolve_unique_and_report_ambiguity(tmp_path):
    from lamtools_core.app import OperationCatalog
    from lamtools_core.plugin_system import PluginHost
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    root=tmp_path/'workspace';(root/'drawings').mkdir(parents=True);(root/'notes').mkdir()
    (root/'notes'/'文档.md').write_text('one',encoding='utf8')
    host=PluginHost(roots=[PATH.parent.parent],state_path=tmp_path/'state.json');catalog=OperationCatalog();register_plugin_operations(catalog,host)
    args={'work_root':str(root),'path':'文档','drawingPath':'drawings/test.excalidraw.md'}
    result=await catalog.execute('excalidraw.link.resolve',args)
    assert result.status=='ok' and Path(result.payload['path'])==(root/'notes'/'文档.md').resolve()
    (root/'other').mkdir();(root/'other'/'文档.md').write_text('two',encoding='utf8')
    ambiguous=await catalog.execute('excalidraw.link.resolve',args)
    assert ambiguous.status=='error' and '多个' in ambiguous.payload['error']
