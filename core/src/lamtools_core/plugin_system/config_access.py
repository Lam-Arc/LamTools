"""user:“宿主能力补齐和接口完善与文档更新”+(配置门面固定 manifest/owner/启动代，保存结果明确不代表应用或热重载)。"""

from .config_store import (ConfigError, ConfigSnapshot, ConfigValidation, ConfigSaveResult,
                           read_config_snapshot, validate_config_values, save_config_values)


class PluginConfigAPI:
    def __init__(self, manifest, scope, data_dir):
        self._manifest, self._scope, self._data_dir = manifest, scope, data_dir

    def read(self) -> ConfigSnapshot:
        self._scope.check_open()
        return read_config_snapshot(self._manifest, data_dir=self._data_dir)

    def validate(self, values) -> ConfigValidation:
        self._scope.check_open()
        return validate_config_values(self._manifest, values)

    def replace(self, values, *, expected_revision: str) -> ConfigSaveResult:
        self._scope.check_open()
        if expected_revision is None:
            raise ConfigError("config/invalid-revision", "Read the current configuration revision before replacing it")
        return save_config_values(self._manifest, values, data_dir=self._data_dir, expected_revision=expected_revision)


__all__ = ["ConfigError", "ConfigSnapshot", "ConfigValidation", "ConfigSaveResult", "PluginConfigAPI"]
