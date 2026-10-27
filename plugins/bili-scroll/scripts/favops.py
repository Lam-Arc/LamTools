"""user:“都试一试”+(收藏边车使用当前 bilibili-api-python 的公开 API，返回可核对回执)。"""
import asyncio
import json
import sys
from pathlib import Path


def load():
    from bilibili_api import Credential
    path = Path.cwd() / "bili_credential.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    return Credential(sessdata=value["sessdata"], bili_jct=value["bili_jct"],
                      buvid3=value.get("buvid3", ""), dedeuserid=str(value["dedeuserid"])), int(value["dedeuserid"])


async def folders():
    from bilibili_api import favorite_list
    credential, uid = load()
    response = await favorite_list.get_video_favorite_list(uid=uid, credential=credential)
    return {"ok": True, "folders": [{"id": row["id"], "title": row.get("title", ""),
                                    "count": row.get("media_count", 0)} for row in response.get("list") or []]}


async def add(bvid, fid):
    from bilibili_api import video
    if int(fid) <= 0:
        raise ValueError("收藏夹 ID 必须大于零")
    credential, _ = load()
    response = await video.Video(bvid=bvid, credential=credential).set_favorite(add_media_ids=[int(fid)])
    return {"ok": True, "bvid": bvid, "folder": int(fid), "receipt": response}


def main():
    try:
        args = sys.argv[1:]
        if args == ["folders"]:
            result = asyncio.run(folders())
        elif len(args) == 3 and args[0] == "add":
            result = asyncio.run(add(args[1], int(args[2])))
        else:
            raise ValueError("用法：folders 或 add <bvid> <fid>")
    except Exception as exc:
        result = {"ok": False, "error": str(exc)[:400]}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
