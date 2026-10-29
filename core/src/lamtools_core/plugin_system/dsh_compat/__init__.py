"""user:“脚本不必能处理所有问题，剩下问题交给 agent 来移植”+(静态迁移工具保留未适配源码并输出明确的人工交接)。"""

from .catalog import load_surface, render_matrix
from .migration import analyze, export_port

__all__ = ["load_surface", "render_matrix", "analyze", "export_port"]
