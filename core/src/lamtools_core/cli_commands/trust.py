"""user:“一次性处理干净 不要留尾巴”+(CLI 与设置页共用全局信任账)。"""
import json
from lamtools_core.tool.operation_trust import OperationTrustStore

async def cmd_trust_list(args):
    print(json.dumps({"entries": OperationTrustStore().list()}, ensure_ascii=False), flush=True)
    return 0

async def cmd_trust_revoke(args):
    OperationTrustStore().revoke(args.key)
    print(json.dumps({"revoked": True}), flush=True)
    return 0
