import json
import os
from pathlib import Path
os.environ['LAMTOOLS_CORE_CONFIG_ROOT'] = 'E:/setuptest/rc-0.3.19-update-config'
from lamtools_core.update import checker as c
out = {}
for name,url in [('site',c.DEFAULT_SITE_UPDATE_URL),('github',c.RELEASES_LATEST_URL)]:
    try: out[name] = c._http_get_json(url)
    except Exception as e: out[name] = {'error':str(e)}
out['check'] = c.check_update()
Path(__file__).with_name('update-readonly.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
print(json.dumps(out['check'],indent=2))
