"""user:“自动化兼容脚本”+(从仓库直接运行迁移分析器，不执行插件源码)。"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core" / "src"))
from lamtools_core.plugin_system.dsh_compat.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
