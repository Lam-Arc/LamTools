"""user:“实际的地址是在 /artifacts 内”+(缺失引用只恢复到当前项目内唯一的真实成果)。"""
from pathlib import Path

import pytest

from lamtools_core.app.file_references import resolve_file_reference, AmbiguousFileReference


def test_missing_project_root_image_resolves_to_actual_artifact(tmp_path):
    source = tmp_path / '.lam/artifacts/images/krea_ref01_00001_.png'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'actual image')
    assert resolve_file_reference(str(tmp_path / source.name), tmp_path) == source.resolve()
    assert resolve_file_reference('/artifacts/images/' + source.name, tmp_path) == source.resolve()
    assert resolve_file_reference(source.name, tmp_path) == source.resolve()


def test_exact_file_wins_and_duplicate_artifacts_never_get_guessed(tmp_path):
    for folder in ['.lam/artifacts/a', '.lam/artifacts/b']:
        path = tmp_path / folder / 'same.png'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'image')
    with pytest.raises(AmbiguousFileReference):
        resolve_file_reference(str(tmp_path / 'same.png'), tmp_path)
    exact = tmp_path / 'same.png'
    exact.write_bytes(b'original')
    assert resolve_file_reference(str(exact), tmp_path) == exact.resolve()


def test_no_fallback_outside_project_or_for_traversal(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    artifact = root / '.lam/artifacts/image.png'
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b'image')
    for path in [str(tmp_path / 'other/image.png'), '../image.png']:
        with pytest.raises(FileNotFoundError):
            resolve_file_reference(path, root)


def test_read_resolve_and_open_share_the_same_actual_path(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from lamtools_core.app.http_agent_app import create_core_agent_http_app
    root = tmp_path / 'project'
    source = root / '.lam/artifacts/images/image.png'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'png test bytes')
    opened = []
    monkeypatch.setattr('lamtools_core.attachment.files.open_with_default_app', opened.append)
    app = create_core_agent_http_app(core_db=tmp_path / 'core.db', data_dir=tmp_path / 'data', work_root=root)
    wrong = str(root / 'image.png')
    with TestClient(app) as client:
        params = {'path': wrong, 'work_root': str(root)}
        resolved = client.get('/api/core/files/resolve-reference', params=params)
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()['path'] == source.resolve().as_posix()
        assert client.get('/api/core/files/read-reference', params=params).content == source.read_bytes()
        assert client.post('/api/core/files/open-reference', json=params).status_code == 200
        assert opened == [source.resolve()]
        other = root / '.lam/artifacts/other/image.png'
        other.parent.mkdir()
        other.write_bytes(b'other')
        assert client.get('/api/core/files/resolve-reference', params=params).status_code == 409
        assert client.post('/api/core/files/open-reference', json=params).status_code == 409
        assert len(opened) == 1
