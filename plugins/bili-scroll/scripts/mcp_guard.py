"""user:“对比原版，能力应当只增不减”+(保持原服务器，补回 DSH 宿主原有的配置硬闸)。"""
import functools
import inspect
import json


def write_denial(name, arguments, config):
    if arguments.get("force") is True:
        return ""
    if name == "bili_reply":
        if arguments.get("rpid"):
            if not config.get("replyToComments") or int(config.get("replyPerRound", 1)) <= 0:
                return "回复评论未开启或本轮回复额度为零"
        elif not (config.get("autoComment") and config.get("mentionName") and config.get("dmMode", "only") != "only"):
            return "公开评论需要开启自动评论、填写要 @ 的人，且投递方式允许评论"
        elif int(config.get("commentPerRound", 1)) <= 0:
            return "本轮评论额度为零"
    if name == "bili_send_message":
        recipient = int(arguments.get("receiver_uid") or 0)
        owners = {int(config.get("dmUid") or 0), int(config.get("dmOwnerUid") or 0)} - {0}
        if not owners or recipient not in owners:
            return "私信只能发送给设置中指定的主人"
        if config.get("dmMode", "only") == "off" and not config.get("dmWatch"):
            return "私信投递和双向回复均未开启"
    return ""


def wrap_write(function, read_config):
    signature = inspect.signature(function)
    @functools.wraps(function)
    async def guarded(*args, **kwargs):
        force = kwargs.pop("force", False)
        arguments = dict(signature.bind(*args, **kwargs).arguments)
        denial = write_denial(function.__name__, {**arguments, "force": force}, read_config())
        if denial:
            return json.dumps({"ok": False, "blocked": True, "error": denial}, ensure_ascii=False)
        result = function(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result
    guarded.__signature__ = signature.replace(parameters=[*signature.parameters.values(),
        inspect.Parameter("force", inspect.Parameter.KEYWORD_ONLY, default=False, annotation=bool)])
    return guarded


def install_guard(config_path):
    from mcp.server.fastmcp import FastMCP
    original = FastMCP.tool
    def read_config():
        try:
            values = json.loads(config_path.read_text(encoding="utf-8"))
            cache = config_path.parent / "duty" / "recipient.json"
            if not values.get("dmUid") and cache.is_file():
                recipient = json.loads(cache.read_text(encoding="utf-8"))
                if recipient.get("name") == values.get("mentionName"):
                    values["dmUid"] = recipient.get("uid", 0)
            return values
        except (OSError, ValueError):
            return {}
    def tool(self, *args, **kwargs):
        register = original(self, *args, **kwargs)
        def decorator(function):
            if function.__name__ in {"bili_reply", "bili_send_message"}:
                function = wrap_write(function, read_config)
            elif function.__name__ in {"bili_transcribe", "bili_transcribe_start"}:
                original_function = function
                @functools.wraps(original_function)
                async def transcribe(*arguments, **parameters):
                    import os
                    os.environ["BILI_DUTY_ASR_MODEL"] = str(read_config().get("asrModel") or "small")
                    return await original_function(*arguments, **parameters)
                function = transcribe
            return register(function)
        return decorator
    FastMCP.tool = tool
