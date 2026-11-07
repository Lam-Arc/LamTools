"""user:“给我把 2 阶段做完，前端除外”+(Web胶合只公开原HTTP宿主明确广告地址，不改前端、路由或认证)。"""
from dataclasses import dataclass
from urllib.parse import urlsplit,urlunsplit


class WebAppAccessError(RuntimeError):
    def __init__(self,code,message):
        self.code=code
        super().__init__(message)


@dataclass(frozen=True)
class WebAppValues:
    url: str

    @classmethod
    def from_url(cls,value):
        try:
            if type(value) is not str or not 1<=len(value)<=2048 or any(c.isspace() or ord(c)<32 for c in value):
                raise ValueError
            parsed=urlsplit(value)
            if (parsed.scheme not in {"http","https"} or not parsed.hostname
                    or parsed.hostname in {"0.0.0.0","::"} or parsed.port==0 or parsed.username is not None
                    or parsed.password is not None or parsed.query or parsed.fragment):
                raise ValueError
            return cls(urlunsplit((parsed.scheme,parsed.netloc,parsed.path.rstrip('/')+'/',"","")))
        except (ValueError,TypeError):
            raise WebAppAccessError("web-app/invalid-url","Use an explicit HTTP(S) browser root without credentials, query, fragment or wildcard address") from None


class PluginWebAppAPI:
    def __init__(self,context,scope):
        self._context,self._scope=context,scope
        self._value=context.service("web_app")

    def get_advertised_url(self):
        if self._scope is not None:
            self._scope.check_open()
        if self._context.service("web_app") is not self._value:
            raise WebAppAccessError("web-app/host-changed","Web host was withdrawn or replaced")
        if not isinstance(self._value,WebAppValues):
            raise WebAppAccessError("web-app/unavailable","No advertised HTTP frontend runtime is mounted")
        return self._value.url
