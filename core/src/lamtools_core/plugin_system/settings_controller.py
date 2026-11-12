"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(设置写入复用原CAS并只返回脱敏投影)。"""
import copy
from .config_store import ConfigError
from .storage_access import _encode


class SettingsControllerError(RuntimeError):
    def __init__(self, code, message, *, may_have_changed=False):
        self.code, self.may_have_changed = code, may_have_changed
        super().__init__(message)


class PluginSettingsController:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._manifest, self._data_dir = context._plugin_manifest, context.data_dir
        self._settings = context.settings

    def _check(self):
        self._scope.check_open()
        if (self._context._registration_scope is not self._scope or self._context._plugin_manifest is not self._manifest
                or self._context.data_dir != self._data_dir):
            raise SettingsControllerError("settings/host-changed", "Settings binding changed")

    def describe(self):
        self._check()
        result = self._settings.public()
        self._check()
        return result

    def update(self, patch, *, expected_revision):
        if type(patch) is not dict:
            raise ConfigError("settings/invalid-values", "Patch must be an object")
        _encode(patch)
        self._check()
        snapshot = self._settings.read()
        self._check()

        def merge(current, changes, depth=0):
            if depth > 64:
                raise ConfigError("settings/invalid-values", "Patch nesting exceeds 64 levels")
            if type(current) is not dict or type(changes) is not dict:
                return copy.deepcopy(changes)
            result = copy.deepcopy(current)
            for key, value in changes.items():
                result[key] = merge(result[key], value, depth + 1) if key in result else copy.deepcopy(value)
            return result

        # user:“第二阶段结束后 就继续开展第三阶段”+(在原完整配置上合并补丁，原修订检查防止覆盖并发写入)。
        return self.replace(merge(snapshot.values, patch), expected_revision=expected_revision)

    def mutate(self, ops, *, expected_revision):
        if type(ops) is not list or not 1 <= len(ops) <= 64:
            raise ConfigError("settings/invalid-values", "Use 1–64 path edits")
        _encode(ops)
        for op in ops:
            if type(op) is not dict or type(op.get("op")) is not str or op["op"] not in {"set", "unset"}:
                raise ConfigError("settings/invalid-values", "Unknown path edit")
            required = {"op", "path", "value"} if op["op"] == "set" else {"op", "path"}
            path = op.get("path")
            if (set(op) != required or type(path) is not list or not 1 <= len(path) <= 32
                    or any(type(key) is not str or not key or len(key) > 256 or "\x00" in key for key in path)):
                raise ConfigError("settings/invalid-values", "Invalid path edit")
        self._check()
        snapshot = self._settings.read()
        self._check()
        values = copy.deepcopy(snapshot.values)
        # user:“第二阶段结束后 就继续开展第三阶段”+(按顺序编辑脱离存储的副本，全部校验后再经原CAS一次提交)。
        for op in ops:
            node = values
            for position, key in enumerate(op["path"]):
                last = position == len(op["path"]) - 1
                if type(node) is list:
                    if not key.isascii() or not key.isdigit() or (len(key) > 1 and key[0] == "0"):
                        raise ConfigError("settings/invalid-values", "Invalid array index")
                    index = int(key)
                    if index > len(node) or (index == len(node) and (not last or op["op"] == "unset")):
                        raise ConfigError("settings/invalid-values", "Array index is out of range")
                    if last:
                        if op["op"] == "unset": node.pop(index)
                        elif index == len(node): node.append(copy.deepcopy(op["value"]))
                        else: node[index] = copy.deepcopy(op["value"])
                    else:
                        node = node[index]
                elif type(node) is dict:
                    if last:
                        if op["op"] == "unset": node.pop(key, None)
                        else: node[key] = copy.deepcopy(op["value"])
                    elif key in node:
                        node = node[key]
                    else:
                        raise ConfigError("settings/invalid-values", "Path parent is missing")
                else:
                    raise ConfigError("settings/invalid-values", "Path parent is not a container")
        return self.replace(values, expected_revision=expected_revision)

    def replace(self, values, *, expected_revision):
        self._check()
        # user:“复用原宿主权威”+(先使用原schema及JSON校验，明确的参数错误不应误报可能已写入)。
        validation = self._settings.validate(values)
        if not validation.valid:
            raise ConfigError("settings/invalid-values", "; ".join(validation.problems))
        self._check()
        def check_after_write():
            try:
                self._check()
            except RuntimeError:
                raise SettingsControllerError("settings/host-changed", "Settings committed but binding changed", may_have_changed=True) from None
        try:
            # user:“复用原宿主权威”+(保留原schema校验与CAS提交，不把包含明文配置的原保存对象返回给Remote)。
            saved = self._settings.replace(values, expected_revision=expected_revision)
        except ConfigError as error:
            if error.code in {"settings/invalid-values", "config/invalid-values", "config/invalid-revision", "config/conflict", "config/busy"}:
                raise
            check_after_write()
            # user:“完成真实接口、参数/错误、作用域、取消/清理”+(写入异常可能发生在替换之后，不能假定原配置未变更)。
            raise SettingsControllerError("settings/write-uncertain", "Settings write failed; inspect current state", may_have_changed=True) from None
        except Exception:
            check_after_write()
            raise SettingsControllerError("settings/write-uncertain", "Settings write failed; inspect current state", may_have_changed=True) from None
        check_after_write()
        try:
            result = self._settings.public()
        except Exception:
            # user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(提交后投影失败与宿主变化分开报告，均明确可能已变更)。
            raise SettingsControllerError("settings/post-commit-unavailable", "Settings committed but public projection is unavailable", may_have_changed=True) from None
        check_after_write()
        # user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(并发配置或schema变化时不能把后来的投影当作本次写入结果)。
        if result.get("revision") != saved.snapshot.revision:
            raise SettingsControllerError("settings/post-commit-changed", "Settings changed after commit", may_have_changed=True)
        return result
