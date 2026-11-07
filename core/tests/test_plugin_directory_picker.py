"""user:“给我把 2 阶段做完，前端除外”+(目录选择的browse后端实际列举/创建，不需要前端或系统对话框)。"""
import pytest

from .test_plugin_working_directory import env


@pytest.mark.asyncio
async def test_browse_actual_list_create_errors_and_project_bounds(env):
    ctx, _, _, root = env
    api = ctx.directory_picker.capability()
    assert api.kind == "browse"
    initial = api.list()
    assert initial["path"] == str(root)
    assert {entry["name"] for entry in initial["entries"]} == {"one", "two"}
    assert initial["ancestors"] == [{"name": root.name, "path": str(root)}]
    child = api.create_directory(str(root), "new-child")
    assert (root / "new-child").is_dir() and child == str(root / "new-child")
    assert api.list(child)["entries"] == []
    from lamtools_core.plugin_system.directory_picker import DirectoryPickerError
    for path, name, code in [(str(root), "new-child", "directory-exists"),
                              (str(root), "../escape", "directory-create-failed"),
                              (str(root), "NUL", "directory-create-failed")]:
        with pytest.raises(DirectoryPickerError) as error:
            api.create_directory(path, name)
        assert error.value.code == code
    for path in ["one", "C:relative", str(root.parent)]:
        with pytest.raises(DirectoryPickerError) as error:
            api.list(path)
        assert error.value.code == "directory-unreadable"
    with pytest.raises(DirectoryPickerError):
        api.create_directory(None, "implicit-parent")
    with pytest.raises(DirectoryPickerError):
        api.list(r"\\server\share")
    assert not (root / "implicit-parent").exists()


@pytest.mark.asyncio
async def test_browse_cut_level_and_revocation(env):
    from lamtools_core.plugin_system.services import ServiceError
    ctx, _, _, root = env
    for number in range(4):
        (root / str(number)).mkdir()
    api = ctx.directory_picker.capability()
    listing = api.list(limit=2)
    assert listing["truncated"] and len(listing["entries"]) == 2
    await ctx._registration_scope.dispose()
    with pytest.raises(ServiceError):
        api.list()
    with pytest.raises(ServiceError):
        api.create_directory(str(root), "later")
    assert not (root / "later").exists()
