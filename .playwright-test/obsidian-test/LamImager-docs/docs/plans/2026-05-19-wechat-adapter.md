# WeChat Work (企业微信) Adapter Implementation Plan

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 企业微信自建应用 adapter that lets users interact with Artist via 企业微信, without modifying the core Artist runtime.

**Architecture:** 企业微信回调 → `routers/wechat.py` → `services/wechat_work_adapter.py` → `artist_orchestrate` → collect result → call 企业微信应用消息 API to send text + image replies. User mapping via `userid → session_id` stored in SQLite.

**Tech Stack:** FastAPI router + `aiohttp` for 企业微信 API calls (no SDK needed, 企业微信 API 是纯 REST + JSON, 比 公众号 XML 简单得多)

**企业微信 vs 公众号 key differences:**
- 无需 XML 解析, 回调是 JSON
- 验签用 `msg_signature` (SHA1(sort(token, timestamp, nonce, encrypt)))
- 消息加密用 AES, 但 SDK 不需要, 自己写几十行即可
- 发消息用应用消息 API (`POST /cgi-bin/message/send`), 不是客服消息
- 图片先上传素材 (`POST /cgi-bin/media/uploadimg`), 再用 `msgtype=image` 发送
- 无 48 小时限制, 企业内部应用可随时主动推送

---

## Task 1: Add 企业微信 config fields

**Files:** `backend/app/config.py`

**Steps:**
- [ ] Add to `Settings` class:
  ```python
  WECHAT_WORK_ENABLED: bool = False
  WECHAT_WORK_CORP_ID: str = ""
  WECHAT_WORK_AGENT_ID: str = ""
  WECHAT_WORK_SECRET: str = ""
  WECHAT_WORK_TOKEN: str = ""
  WECHAT_WORK_ENCODING_AES_KEY: str = ""
  ```

**Verification:**
- [ ] `py -3.14 -c "from app.config import settings; print(settings.WECHAT_WORK_CORP_ID)"` runs without error

**Commit:** `feat(wechat-work): add config fields`

---

## Task 2: Create WechatWorkBinding model

**Files:** `backend/app/models/wechat_work_binding.py` (new), `backend/app/models/__init__.py`

**Steps:**
- [ ] Create `wechat_work_binding.py`:
  ```python
  class WechatWorkBinding(Base):
      __tablename__ = "wechat_work_bindings"
      id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
      userid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
      session_id: Mapped[str] = mapped_column(String(36), index=True)
      created_at: Mapped[datetime] = mapped_column(default=func.now())
      last_active_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())
  ```
- [ ] Import in `models/__init__.py`

**Verification:**
- [ ] `py -3.14 -c "from app.models.wechat_work_binding import WechatWorkBinding; print(WechatWorkBinding.__tablename__)"` succeeds

**Commit:** `feat(wechat-work): add WechatWorkBinding model`

---

## Task 3: Create 企业微信 crypto utilities

**Files:** `backend/app/utils/wechat_work_crypto.py` (new)

**Steps:**
- [ ] Implement `WechatWorkCrypto` class:
  - `__init__(self, token, encoding_aes_key, corp_id)`
  - `verify_signature(signature, timestamp, nonce, encrypt) -> bool`: SHA1(sort(token, timestamp, nonce, encrypt))
  - `decrypt(encrypt) -> str`: AES-256-CBC decrypt with base64-decoded AES key, PKCS7 unpad, extract XML/JSON content
  - `encrypt(reply, nonce) -> dict`: AES encrypt reply, return `{encrypt, signature, timestamp, nonce}`
- [ ] AES key derivation: `base64.b64decode(encoding_aes_key + "=")`, IV = first 16 bytes
- [ ] PKCS7 padding/unpadding

**Verification:**
- [ ] Round-trip test: encrypt → decrypt returns original content

**Commit:** `feat(wechat-work): add crypto utilities`

---

## Task 4: Create WechatWorkAdapter service

**Files:** `backend/app/services/wechat_work_adapter.py` (new)

**Steps:**
- [ ] Create `WechatWorkAdapter` class:
  - `get_or_create_session(db, userid) -> str`: lookup binding, create session if not exists
  - `get_access_token() -> str`: call `POST /cgi-bin/gettoken?corpid={corp_id}&corpsecret={secret}`, cache with TTL + asyncio.Lock
  - `send_text_message(userid, content)`: call `POST /cgi-bin/message/send` with `msgtype=text`, `touser={userid}`, `agentid={agent_id}`
  - `send_image_message(userid, image_url)`: download image → upload via `POST /cgi-bin/media/uploadimg` → send with `msgtype=image`
  - `send_markdown_message(userid, content)`: `msgtype=markdown` (企业微信支持 markdown 卡片)
  - `handle_artist_result(userid, result: dict)`: extract message + image URLs, send text then images sequentially
  - `download_media(media_id) -> bytes`: `GET /cgi-bin/media/get`
- [ ] Use `aiohttp.ClientSession` for all HTTP calls
- [ ] All methods are async

**Verification:**
- [ ] `py -3.14 -c "from app.services.wechat_work_adapter import WechatWorkAdapter; print('ok')"` succeeds

**Commit:** `feat(wechat-work): add WechatWorkAdapter service`

---

## Task 5: Create 企业微信 router

**Files:** `backend/app/routers/wechat_work.py` (new), `backend/app/main.py`

**Steps:**
- [ ] Create `wechat_work.py` with `router = APIRouter(tags=["wechat-work"])`:
  - `GET /api/wechat-work/callback`: verify URL callback (企业微信验证)
  - `POST /api/wechat-work/callback`: handle incoming messages:
    1. Parse JSON body, extract `msg_signature`, `timestamp`, `nonce`, `Encrypt`
    2. Verify signature via `WechatWorkCrypto.verify_signature()`
    3. Decrypt to get message content (JSON with `Content`, `MsgType`, `FromUserName`)
    4. Extract `userid` (FromUserName), message type, content
    5. Get or create session
    6. Return `"success"` immediately
    7. Spawn `asyncio.create_task()` for artist turn
  - `POST /api/wechat-work/test`: dev test endpoint (bypasses signature check)
- [ ] Register router in `main.py`: `if settings.WECHAT_WORK_ENABLED: app.include_router(wechat_work.router)`

**Verification:**
- [ ] Server starts with `WECHAT_WORK_ENABLED=false` (no router)
- [ ] Server starts with `WECHAT_WORK_ENABLED=true`, `/api/wechat-work/callback` accessible

**Commit:** `feat(wechat-work): add callback router`

---

## Task 6: Wire adapter into artist flow

**Files:** `backend/app/routers/wechat_work.py`

**Steps:**
- [ ] Implement `_run_artist_for_wechat(userid, session_id, prompt, reference_images)`:
  1. Create `AsyncSession` from `async_session_factory`
  2. Build `GenerateRequest(agent_mode=True, agent_persona="artist", prompt=prompt, reference_images=reference_images)`
  3. Call `handle_agent_generate(db, data)`
  4. On success: `adapter.handle_artist_result(userid, result)`
  5. On error: `adapter.send_text_message(userid, "创作遇到问题，请稍后再试")`
- [ ] For image messages: download media via `adapter.download_media()`, save to uploads, pass URL as `reference_images`
- [ ] Send "正在创作中..." text message immediately after receiving request

**Verification:**
- [ ] POST to `/api/wechat-work/test` with `{"userid": "test", "content": "画一只猫"}` triggers artist flow

**Commit:** `feat(wechat-work): wire artist flow`

---

## Task 7: Add Alembic migration

**Files:** auto-generated in `backend/alembic/versions/`

**Steps:**
- [ ] Run `cd backend && py -3.14 -m alembic revision --autogenerate -m "add wechat_work_bindings table"`
- [ ] Review and run `py -3.14 -m alembic upgrade head`

**Verification:**
- [ ] `wechat_work_bindings` table exists in database

**Commit:** `feat(wechat-work): add migration`

---

## Task 8: Add .env.example and setup guide

**Files:** `backend/.env.example`

**Steps:**
- [ ] Add:
  ```
  # 企业微信自建应用 Integration
  # WECHAT_WORK_ENABLED=false
  # WECHAT_WORK_CORP_ID=
  # WECHAT_WORK_AGENT_ID=
  # WECHAT_WORK_SECRET=
  # WECHAT_WORK_TOKEN=
  # WECHAT_WORK_ENCODING_AES_KEY=
  ```

**Verification:**
- [ ] File exists with all entries

**Commit:** `docs(wechat-work): add .env.example`

---

## 企业微信设置步骤 (用户指南)

1. 注册企业微信: https://work.weixin.qq.com/ (个人即可注册)
2. 创建自建应用: 「应用管理」→「自建」→「创建应用」
3. 获取 Corp ID: 「我的企业」→「企业信息」→「企业ID」
4. 获取 Agent ID 和 Secret: 应用详情页
5. 设置接收消息: 应用详情 → 「接收消息」→「设置API接收」
   - URL: `https://你的域名/api/wechat-work/callback`
   - Token 和 EncodingAESKey: 自定义/随机生成
6. 配置 .env 并启动服务
7. 在企业微信中打开应用, 发消息即可与 Artist 对话
