"""user:“对比原版，能力应当只增不减”+(同一原版服务器，在插件数据目录运行并保留宿主写入闸)。"""
import os
from pathlib import Path
from mcp_guard import install_guard

home = Path(os.environ["BILI_DUTY_HOME"])
root = Path(os.environ["BILI_PLUGIN_ROOT"])
install_guard(home.parent / "config.jsonc")
source = root / "vendor" / "bilibili-mcp" / "mcp_server.py"
# The upstream server stores credentials relative to __file__. Execute its
# unchanged source with the private data-directory identity, just as DSH does.
exec(compile(source.read_text(encoding="utf-8"), str(source), "exec"),
     {"__name__": "__main__", "__file__": str(home / "mcp_server.py")})
