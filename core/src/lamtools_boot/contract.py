"""user:“该重建就重建”+(启动层和运行层共用恢复内核边界，不维护两套规则)。"""
KERNEL_BACKEND = frozenset({
    "lamtools_core.plugin_system.host", "lamtools_core.plugin_system.manifest",
    "lamtools_core.plugin_system.state", "lamtools_core.plugin_system.import_map",
    "lamtools_core.plugin_system.loading", "lamtools_core.plugin_system.safety",
    "lamtools_core.plugin_system.behavior_table", "lamtools_core.logging_setup",
})
KERNEL_FRONTEND_PREFIXES = ("@/plugins/contributions", "@/plugins/pages")


def protected_target(target):
    if target.startswith("@/"):
        return any(target.startswith(prefix) for prefix in KERNEL_FRONTEND_PREFIXES)
    return any(name == target or name.startswith(target + ".") for name in KERNEL_BACKEND)
