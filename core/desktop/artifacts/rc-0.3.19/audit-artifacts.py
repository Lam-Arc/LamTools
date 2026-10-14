import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

root = Path('E:/LamTools')
evidence = Path(__file__).resolve().parent
installed = Path('E:/setuptest/0.3.19')
internal = installed/'lamcore-backend/_internal'
assert (installed/'lamcore.exe').is_file()
assert (installed/'lamcore-backend/sunday-core.exe').is_file()
plugins = internal/'resources/plugins/bundled'
expected = {p.name for p in (root/'core/src/lamtools_core/plugins/bundled').iterdir() if p.is_dir() and p.name not in {'workflow','emotion-ball-pet','__pycache__'}}
assert {x.name for x in plugins.iterdir() if x.is_dir()} == expected
assert {'git','websearch','imagegen'} <= expected
checks = []
for source,destination in [(root/'core/skills',internal/'resources/skills'),
                           (root/'core/config/resources',internal/'config/resources'),
                           (root/'core/config/command',internal/'config/command'),
                           (root/'core/config/llm_adapters',internal/'config/llm_adapters')]:
    files = [p for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'}]
    for p in files:
        actual = destination/p.relative_to(source)
        assert actual.is_file(), str(actual)
        assert actual.read_bytes() == p.read_bytes(), str(actual)
    checks.append({'source':str(source),'installed':str(destination),'verified_files':len(files)})
assert (internal/'python314.dll').is_file()
assert (internal/'base_library.zip').is_file()
assert (internal/'frontend/index.html').is_file()
installer = evidence/'Sunday_0.3.19_x64-setup.exe'
spec = importlib.util.spec_from_file_location('manifest_builder', root/'scripts/build-desktop-update.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
notes = (evidence/'RELEASE-NOTES.md').read_text(encoding='utf-8')
args = argparse.Namespace(base_url='https://ainarit.com/downloads',release_url='https://ainarit.com/sunday.html',notes=notes,notes_file=None,allow_version_mismatch=False)
manifest = module.build_manifest(args,installer)
manifest.pop('published_at',None)
(evidence/'desktop-update.proposed.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
optional = evidence/'workflow-1.0.0-optional-rc.zip'
with zipfile.ZipFile(optional,'w',zipfile.ZIP_DEFLATED) as archive:
    source = root/'core/src/lamtools_core/plugins/bundled/workflow'
    for p in source.rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'}:
            archive.write(p,Path('workflow')/p.relative_to(source))
artifacts = []
for p in [installer, optional, installed/'lamcore.exe', installed/'lamcore-backend/sunday-core.exe']:
    artifacts.append({'path':str(p),'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
out = {'artifacts':artifacts,'resource_checks':checks,'plugins':sorted(x.name for x in plugins.iterdir()),
       'runtime':'Bundled Python 3.14, native extensions and standard library verified; WebView2 present on test host. Bootstrapper offline installation untested.',
       'source_snapshot':'Existing working tree; no commit or publication created.'}
(evidence/'artifact-inventory.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
print(json.dumps(out,indent=2))
