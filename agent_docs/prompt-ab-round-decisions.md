# 各次运行的逐轮决策依据

动作列是模型实际发出的调用目标，结果列是工具返回的首段内容或命中山数量。

| 编号 | 轮次 | 工具 | 字数 | 图表 | 核心 | 桌面 | 移交 | 管理 | 持久 | 阶段序列 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Ox-1 | 26 | 47 | 4142 | 1 | 8/29 | 3/24 | 4/4 | 0/5 | 0/2 | `MCTTPPPXXCKTTTTTMPCPXVVCM-` |
| Ox-2 | 29 | 56 | 6050 | 1 | 8/29 | 3/24 | 4/4 | 5/5 | 2/2 | `MPPCCTTTTTTTTTCPXMPPVTTTXCTT-` |
| Ox-3 | 31 | 56 | 5539 | 1 | 7/29 | 3/24 | 4/4 | 0/5 | 0/2 | `MKCCPPPTTTTTTTTTTVVVTVXKXPPXCX-` |
| Ox-4 | 45 | 74 | 4105 | 1 | 7/29 | 4/24 | 2/4 | 0/5 | 0/2 | `XCCCPXPXXCXXXKXCPTTTTTTTTTTTTPXXPMTTTKKPMXCT-` |
| Ra-1 | 32 | 60 | 6312 | 1 | 8/29 | 3/24 | 4/4 | 0/5 | 0/2 | `MPPPKXKPTTTTTTTTTXMTXKPPPXPXPCX-` |
| Ra-2 | 25 | 50 | 6047 | 1 | 29/29 | 24/24 | 4/4 | 0/5 | 0/2 | `MKPPCMTTTTCCCCXXXVTPKXXK-` |
| Ra-3 | 45 | 79 | 4506 | 1 | 28/29 | 24/24 | 4/4 | 5/5 | 2/2 | `MMCKKPXTTTTTTTVTTXPXTCCXVPMCXXMMCXTPXPCXXXPP-` |
| Ra-4 | 47 | 82 | 4105 | 1 | 9/29 | 4/24 | 4/4 | 5/5 | 2/2 | `MCPCCXKKXXXMTXTTTTTTPTTXPTTXTPPPPPCCCKXXXKKXPT-` |
| Rb-1 | 34 | 60 | 5171 | 1 | 8/29 | 3/24 | 4/4 | 5/5 | 2/2 | `MPKPCCKPPMTTTTTTPTXXXPKXTCXTXKXTX-` |
| Rb-2 | 28 | 46 | 4685 | 1 | 8/29 | 3/24 | 4/4 | 5/5 | 2/2 | `XCCCPPPTMTPTPXXXMMPXMMXXXPX-` |
| Rc-1 | 45 | 76 | 4650 | 1 | 8/29 | 3/24 | 4/4 | 0/5 | 2/2 | `XPPCCCCPXKKXCXPTTMTTMTTPTTTTTXXPPXPXCXXPVTXP-` |
| Rc-2 | 33 | 62 | 3179 | 0 | 3/29 | 0/24 | 2/4 | 0/5 | 2/2 | `MCCCPPKKKKMTTTTXTTTTTMMXMMXXCCTM-` |

## Ox-1（chain4/base，26 轮）

| 轮 | 动作 | 得到 |
| --- | --- | --- |
| 1 | ls && echo "---" && ls core/src/lamtools_core/app | head -50 | 0.1.0 0.1.1 0.3.0 0.3.1 0.3.2 AGENTS.md CITATION.cff LICENSE MAINTENAN… |
|  | search_content E:\LamTools\core\src\lamtools_core | 匹配34处；扫描775项：core/src/lamtools_core/app/base_agent.py:780: def _compose_system_prom… |
| 2 | ls prompt/ && echo "=== kernel ===" && ls kernel/ | head -40 && echo "=== plugins/bundled ===" & | __init__.py __pycache__ movable.py === kernel === __init__.py __pycach… |
|  | read_file core/src/lamtools_core/app/base_agent.py | " not in content and artifact_metadata.get("stdout"): lines.append(f"s… |
| 3 | grep -n "def _compose_system_prompt" -A 3 app/base_agent.py && echo "=== prompthub? ===" && grep | 780: def _compose_system_prompt( 781- self, 782- state: RuntimeState, … |
|  | echo "=== tools.jsonc 清单 ===" && find . -name "tools.jsonc" -not -path "*/node_modules/*" | sort | === tools.jsonc 清单 === ./.build/plugin-rebuild/live/plugins/bili-scrol… |
| 4 | sed -n '780,1010p' app/base_agent.py | def _compose_system_prompt( self, state: RuntimeState, *, study_mode: … |
|  | echo "=== main tree tools.jsonc ===" && find core plugins -name "tools.jsonc" -not -path "*/node | === main tree tools.jsonc === core/desktop/src-tauri/lamcore-backend/_… |
| 5 | cat plugins/bundled/plan/tools/tools.jsonc | head -40 && echo "=== TAIL marker defs ===" && grep | { // The plan plugin ships skills only (draft-plan / refine-plan / exe… |
|  | wc -l prompt/movable.py plugin_system/prompt_waterfall.py kernel/loop.py context_compaction/*.py | 215 prompt/movable.py 174 plugin_system/prompt_waterfall.py 5443 kerne… |
| 6 | read_file core/src/lamtools_core/prompt/movable.py | """Movable system-context blocks with an epoch-frozen leading prompt. … |
|  | read_file core/src/lamtools_core/plugin_system/prompt_waterfall.py | """System-prompt waterfall for plugins. The upstream DSH host exposes … |
| 7 | sed -n '1140,1300p' app/base_agent.py | } def emit_runtime_context_snapshot(self, state: RuntimeState) -> Chat… |
|  | wc -l plugin_system/prompt_extensions.py && cat plugin_system/prompt_extensions.py | 196 plugin_system/prompt_extensions.py """user:“每一个地方 sunday 都有等价或者近似接… |
| 8 | echo "=== loop.py system msgs ===" && grep -n 'role="system"\|role=.system.' kernel/loop.py | he | === loop.py system msgs === 2246: role="system", === compaction notice… |
|  | sed -n '1,120p' tool/loadtools.py && echo "=== mode_prompt_line ===" && grep -n "def mode_prompt | """Load-tools configuration: mode-based tool set management. Controls … |
| 9 | echo "=== mode_prompt_line usage ===" && grep -rn "mode_prompt_line" --include=*.py . && echo "= | === mode_prompt_line usage === ./app/base_agent.py:78:from lamtools_co… |
|  | echo "=== loop 2220-2280 ===" && sed -n '2220,2280p' kernel/loop.py && echo "=== loop 4550-4600  | === loop 2220-2280 === turn_input.user_content if turn_input.user_cont… |
| 10 | sed -n '1080,1145p' app/base_agent.py && echo "=== _study_mode_and_instructions ===" && grep -n  | include_processes: bool, ) -> dict[str, Any]: """Collect the session-s… |
|  | echo "=== agent.py resolve_agent_plan ===" && grep -n "def resolve_agent_plan" -A 60 plugin_syst | === agent.py resolve_agent_plan === 166:def resolve_agent_plan( 167- a… |
| 11 | ls tool/ && echo "=== toolbox build ===" && grep -n "def build_core_toolbox" -A 80 tool/default_ | __init__.py __pycache__ android_use.py approval.py approval_continuati… |
|  | echo "=== plugin_compaction ===" && head -60 app/plugin_compaction.py && echo "=== context.py 67 | === plugin_compaction === """user:“每一个地方 sunday 都有等价或者近似接口”+(插件手动压缩复用桌… |
| 12 | grep -n "def default_core_tool_specs" -A 40 tool/default_toolbox.py && echo "=== DEFAULT_TOOL_OR | 1104:def default_core_tool_specs() -> list[ToolSpec]: 1105- names = [ … |
| 13 | sed -n '284,380p' tool/default_toolbox.py && echo "=== bundled names ===" && grep -n "_BUNDLED_P | DEFAULT_TOOL_CATEGORIES: dict[str, str] = { "android_use": "computer",… |
|  | for f in plugins/bundled/workflow/tools.jsonc plugins/bundled/study/tools.jsonc plugins/bundled/ | ===== plugins/bundled/workflow/tools.jsonc 3: { "name": "workflow_grap… |
| 14 | ls core/src/lamtools_core/plugins/bundled/ && echo "=== grep plugin mgmt tools ===" && grep -rn  | imagegen network-exploration pipeline-checker plan study websearch wor… |
|  | echo "=== bili-scroll ===" && grep -n '"name"' plugins/bili-scroll/tools/tools.jsonc && echo "== | === bili-scroll === 4: "name": "bili_status", 11: "name": "bili_config… |
| 15 | grep -rn "enable_plugin_manager\|plugin_manager" --include=*.py . | head -20 && echo "=== search | ./app/default_agent.py:3907: enable_plugin_manager: bool = True, ./app… |
|  | grep -n "DEFAULT_TOOL_DEFINITIONS" -A 5 tool/default_toolbox.py | head -20 && echo "=== count pe | 460:DEFAULT_TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = ( 461- *CON… |
| 16 | python -c " import re lines=open('tool/default_toolbox.py',encoding='utf-8').read().splitlines() | 21 ['read_file', 'list_dir', 'search_files', 'search_content', 'load_s… |
|  | grep -n "name=\"\|\"name\":\|\"description\":" plugin_system/manager_tools.py | head -40 && echo | 54: "description": "Install source kind", 58: "description": "Local pl… |
| 17 | echo "=== agent_preset_prompt ===" && grep -rn "agent_preset_prompt" --include=*.py . | head -20 | === agent_preset_prompt === ./app/base_agent.py:558: agent_preset_prom… |
|  | echo "=== study plugin agent ===" && ls plugins/bundled/study/ && grep -rn "STUDY_SYSTEM_PROMPT" | === study plugin agent === __init__.py __pycache__ backend.py dictiona… |
| 18 | sed -n '20,50p' plugins/bundled/study/backend.py && echo "..." && sed -n '360,400p' plugins/bund | 'exam': 'study.exam', 'sign': 'study.sign', 'notes': 'study.notes', } … |
|  | echo "=== assemble_agents / read_agent ===" && sed -n '1,165p' plugin_system/agent.py | === assemble_agents / read_agent === """Agent takeover declarations: p… |
| 19 | echo "=== frozen_tool_block_message ===" && grep -rn "frozen_tool_block_message" --include=*.py  | === frozen_tool_block_message === ./app/base_agent.py:69: frozen_tool_… |
|  | sed -n '2030,2140p' app/base_agent.py | agent_presets = plugin_context.services.get("agent_presets") fresh_pre… |
| 20 | grep -rn "prompt_waterfall" --include=*.py . | grep -v "plugin_system/prompt" | head -20 && echo | ./app/base_agent.py:575: prompt_waterfall: Any | None = None, ./app/ba… |
|  | grep -n "_apply_user_prompt_submit_hook" -A 60 kernel/loop.py | head -80 | 2228: else await self._apply_user_prompt_submit_hook(state, turn_input… |
| 21 | echo "=== hook event names ===" && grep -rn 'event_name="[A-Za-z]*"' --include=*.py . | head -20 | === hook event names === ./kernel/loop.py:3912: event_name="PreToolUse… |
|  | echo "=== lifecycle-demo ===" && grep -n '"name"' core/examples/plugins/lifecycle-demo/tools.jso | === lifecycle-demo === 3: "name": "lifecycle_echo", === git plugin in … |
| 22 | python -c " import json,re,pathlib def strip(s): out=[];i=0;ins=False;esc=False while i<len(s):  | [command] cd /e/LamTools && python -c " import json,re,pathlib def str… |
| 23 | python -c " import json,pathlib BS=chr(92); NL=chr(10); Q=chr(34) def strip(s): out=[];i=0;ins=F | 5 core/src/lamtools_core/plugins/bundled/workflow/tools.jsonc ['workfl… |
| 24 | echo "=== git_status declarations in main tree ===" && grep -rn "git_status" --include=*.jsonc c | === git_status declarations in main tree === === plugin_context_files … |
|  | grep -n "def _runtime_context_delta" -A 40 app/base_agent.py | head -50 && echo "=== _runtime_co | 409:def _runtime_context_delta( 410- previous: Any, 411- current: Mapp… |
| 25 | ls dist-plugins 2>/dev/null | head && find . -maxdepth 3 -type d -name "git" -path "*plugins*" - | LamCore_0.2.5_x64-setup.exe lamtools-rag-v0.1.0.zip === emit_runtime_c… |
|  | sed -n '4610,4720p' kernel/loop.py | message = ( f"{message} The turn stopped without sending an oversized … |
| 26 | 输出正文 | — |

## Ox-2（chain6/base，29 轮）

| 轮 | 动作 | 得到 |
| --- | --- | --- |
| 1 | ls -la E:/LamTools && echo "---" && ls E:/LamTools/core | total 21237 drwxr-xr-x 1 Administrator 197121 0 Nov 20 17:59 . drwxr-x… |
|  | grep -rn "system_prompt" --include=*.py core/src | head -100 | core/src/lamtools_core/app/base_agent.py:780: def _compose_system_prom… |
| 2 | ls prompt/ && echo "=== waterfall ===" && grep -rn "waterfall" --include=*.py . | head -40 | __init__.py __pycache__ movable.py === waterfall === ./app/base_agent.… |
|  | grep -rn "compaction_messages\|epoch\[.system_prompt.\]\|system_prompt=" --include=*.py kernel/  | kernel/loop.py:4563: compaction_messages = compaction_input_messages(r… |
| 3 | read_file core/src/lamtools_core/plugin_system/prompt_waterfall.py | """System-prompt waterfall for plugins. The upstream DSH host exposes … |
|  | read_file core/src/lamtools_core/plugin_system/prompt_extensions.py | """user:“每一个地方 sunday 都有等价或者近似接口”+(提示词贡献绑定已有启动所有权，复用原提示词流水线)。""" from … |
|  | read_file core/src/lamtools_core/prompt/movable.py | """Movable system-context blocks with an epoch-frozen leading prompt. … |
| 4 | grep -rn "plan_movable_context\|movable_context_notice\|MOVABLE_CONTEXT_METADATA_KEY\|MovableBlo | ./app/base_agent.py:37: MOVABLE_CONTEXT_METADATA_KEY, ./app/base_agent… |
|  | sed -n '760,1010p' app/base_agent.py | argument, so it must lead with the real id the model resolver accepts;… |
| 5 | sed -n '1150,1350p' app/base_agent.py | ) if state.metadata is None: state.metadata = {} state.metadata[RUNTIM… |
|  | sed -n '4540,4660p' kernel/loop.py && echo "=== 990-1030 ===" && sed -n '985,1035p' kernel/loop. | "context_compaction_retained_steps": retained_steps, "context_compacte… |
| 6 | echo "=== STUDY PROTOCOL ===" && grep -rn "_STUDY_TOOL_PROTOCOL\|STUDY_SYSTEM_PROMPT\|study_prom | === STUDY PROTOCOL === app/base_agent.py:200:_STUDY_TOOL_PROTOCOL = ( … |
|  | echo "=== tools.jsonc ===" && find . -name "tools.jsonc" -not -path "*/node_modules/*" | head -6 | === tools.jsonc === ./.build/plugin-rebuild/live/plugins/bili-scroll/t… |
| 7 | echo "=== bundled tools.jsonc ===" && find core/src/lamtools_core/plugins -name "tools.jsonc" |  | === bundled tools.jsonc === core/src/lamtools_core/plugins/bundled/ima… |
|  | ls plugins/bundled/ && echo "=== study backend 320-400 ===" && sed -n '325,400p' plugins/bundled | imagegen network-exploration pipeline-checker plan study websearch wor… |
| 8 | head -40 core/src/lamtools_core/plugins/bundled/study/tools.jsonc && echo "=== workflow ===" &&  | { "tools": [ { "name": "get_knowledge_net", "description": "Read a sco… |
|  | grep -rn "ToolSpec\|name=\"" default_toolbox.py | head -60 && echo "=== toolbox size ===" && wc  | 25:from lamtools_core.tool import ToolCall, ToolContext, ToolResult, T… |
| 9 | sed -n '1040,1130p' default_toolbox.py | "description": "snapshot 最多返回多少个元素，默认 80。", }, "max_width": { "type": … |
|  | grep -rn "_CORE_TOOL\|CORE_TOOL_NAMES\|_TOOL_NAMES\s*=" --include=*.py tool/ kernel/ app/ | head | tool/default_toolbox.py:1081:_BUNDLED_PLUGIN_TOOL_NAMES = frozenset({"… |
| 10 | grep -rn "DEFAULT_TOOL_ORDER\|DEFAULT_TOOL_CATEGORIES" --include=*.py . | head -20 | ./app/http_agent_app.py:2192: DEFAULT_TOOL_CATEGORIES, ./app/http_agen… |
|  | grep -rn "plugin_manager\|control" --include=*.py tool/default_toolbox.py | head -40 | 36:from lamtools_core.tool.android_use import android_control_availabl… |
| 11 | sed -n '245,330p' tool/default_toolbox.py | "write_checklist": AUTO_ALLOW, "update_checklist": AUTO_ALLOW, "questi… |
|  | grep -c "\"name\":" plugin_system/manager_tools.py && grep -n "name\":\|def plugin_manager_tool_ | 6 37:def plugin_manager_tool_specs() -> list[ToolSpec]: 92: "name": {"… |
| 12 | python -c " import json,re,glob,os files=sorted(glob.glob('core/src/lamtools_core/plugins/bundle | 1 core/src/lamtools_core/plugins/bundled\imagegen\tools\tools.jsonc ge… |
|  | sed -n '1,140p' plugin_system/manager_tools.py | """模型可调插件管理工具（F2 共识：skill 引导插件安装的调用通道）。 照抄 durable_tools 骨架（operation … |
| 13 | echo "=== git_status refs ===" && grep -rn "git_status" --include=*.py --include=*.jsonc --inclu | === git_status refs === ./app/auxiliary_chat.py:14:READ_ONLY_TOOLS = f… |
|  | python -c " import re s=open('tool/default_toolbox.py',encoding='utf-8').read() m=re.search(r'DE | 29 ['read_file', 'list_dir', 'search_files', 'search_content', 'load_s… |
| 14 | cat plugins/bundled/imagegen/tools/tools.jsonc && echo "=== websearch ===" && cat plugins/bundle | { "tools": [ { "name": "generate_image", "permission": "ask_user", "ha… |
|  | grep -rn "core_tool\|core_spec_by_name\|CORE_TOOL_REF" --include=*.py plugin_system/ | head -20 | plugin_system/runtime.py:75: base = _core_tool_base(tool.name) plugin_… |
| 15 | ls core/src/lamtools_core/resources 2>/dev/null; find core/src -type d -name git -not -path "*/n | === runtime 60-130 === "visibility": tool.visibility, "skill": tool.sk… |
|  | sed -n '195,240p' app/base_agent.py && echo "=== 1990-2060 ===" && sed -n '1990,2060p' app/base_ | # user:“Minimize unnecessary model round-trips.”+(工具执行效率作为内置原则：输入与依赖已知… |
| 16 | ls plugins/ && echo "=== role=system sites ===" && cd core/src/lamtools_core && grep -rn 'role=" | bili-scroll excalidraw lamtools-rag qq-bot === role=system sites === .… |
|  | echo "=== agent_presets ===" && grep -n "prompt\|def " plugin_system/agent_presets.py | head -40 | === agent_presets === 4:tool allow-list, an optional model, and extra … |
| 17 | echo "=== http_client 40-100 ===" && sed -n '40,100p' llm/http_client.py && echo "=== llm/__init | === http_client 40-100 === _logger = logging.getLogger(__name__) @data… |
|  | echo "=== loop 2220-2270 ===" && sed -n '2220,2270p' kernel/loop.py && echo "=== state 95-130 == | === loop 2220-2270 === turn_input.user_content if turn_input.user_cont… |
| 18 | echo "=== loop 275-300 ===" && sed -n '275,300p' kernel/loop.py && echo "=== sub_agent late ctx  | === loop 275-300 === def compaction_input_messages(messages: list[Chat… |
|  | ls plugins/excalidraw && echo "=== manifests with inline tools ===" && grep -rln '"tools"' plugi | EXCALIDRAW-LICENSE NOTICE.md OBSIDIAN-PLUGIN-LICENSE __pycache__ build… |
| 19 | python -c " import json for p in ['plugins/excalidraw/plugin.json','plugins/qq-bot/plugin.json', | plugins/excalidraw/plugin.json | keys: ['name', 'version', 'descriptio… |
|  | echo "=== agent.py 160-200 ===" && sed -n '160,200p' plugin_system/agent.py && echo "=== auxilia | === agent.py 160-200 === continue global_owner = manifest.name assembl… |
| 20 | grep -rn "prompts\.\(section\|variable\|on_assemble\)\|context\.prompts\|prompt_waterfall.regist | plugins/qq-bot/qqbot/agent_bridge.py:125: waterfall = service("system_… |
|  | python -c " import json,glob for p in sorted(glob.glob('core/src/lamtools_core/plugins/bundled/* | core/src/lamtools_core/plugins/bundled\imagegen\plugin.json agent: nul… |
| 21 | python -c " import ast,glob,os found={} for root,dirs,files in os.walk('core/src/lamtools_core') | arrange -> core/src/lamtools_core\tool\durable_tools.py goal -> core/s… |
|  | sed -n '100,150p' plugins/qq-bot/qqbot/agent_bridge.py && echo "=== study load prompt ===" && se | self.data_dir = Path(data_dir) self.work_root = Path(work_root) self.l… |
| 22 | grep -rn "durable_tool_specs\|\"arrange\"\|\"goal\"\|read_main_chat" --include=*.py tool/ app/ k | tool/default_toolbox.py:33: durable_tool_specs, tool/default_toolbox.p… |
|  | sed -n '1791,1830p' tool/default_toolbox.py && echo "=== durable_tools def ===" && grep -n "def  | def tool_specs(self) -> list[ToolSpec]: specs = [ replace(spec, permis… |
| 23 | sed -n '1525,1600p' tool/default_toolbox.py | } # 模式独占工具的反向索引：tool -> 允许使用它的模式集合。 self._exclusive_tool_modes: dict[s… |
|  | grep -rn "raw_input\|prompt\b" plugins/bundled/study/prompts/study-system.md 2>/dev/null | head  | 6:1.1) Reuse the host Agent Loop and its common safety and permission … |
| 24 | grep -rl '"git_status"' --include=*.jsonc --include=*.json . 2>/dev/null | grep -v -E "\.worktre | [command] cd E:/LamTools && grep -rl '"git_status"' --include=*.jsonc … |
|  | grep -n "enable_goal_tool\|enable_arrange_tool\|enable_plugin_manager" tool/default_toolbox.py | | 1437: enable_goal_tool: bool = False, 1438: enable_arrange_tool: bool … |
| 25 | git ls-files | grep -iE "plugins/bundled/(git|desktop|browser)" | head -10; echo "--- exit:$? -- | --- exit:0 --- 14 |
|  | grep -rn "enable_goal_tool=\|enable_arrange_tool=\|enable_plugin_manager=" --include=*.py . | gr | ./app/default_agent.py:821: enable_goal_tool=goal_manager is not None,… |
| 26 | git ls-files | grep "tools.jsonc" | archive/members/writer/config/resources/loadtools.jsonc core/config/re… |
|  | grep -rn "plugin_context_files" --include=*.py . | head -10 && echo "=== emit_runtime_context_sn | ./app/base_agent.py:574: plugin_context_files: list[dict[str, Any]] | … |
| 27 | head -20 config/resources/loadtools.jsonc && echo "=== access_tools ===" && head -15 config/reso | { "version": 1, "modes": { "consider": { "description": "Consider mode… |
| 28 | cat config/resources/loadtools.jsonc | { "version": 1, "modes": { "consider": { "description": "Consider mode… |
|  | sed -n '1454,1480p' app/base_agent.py | def _frozen_tools(self, state: RuntimeState) -> list[dict[str, Any]]: … |
| 29 | 输出正文 | — |

## Ox-3（r1/base，31 轮）

| 轮 | 动作 | 得到 |
| --- | --- | --- |
| 1 | ls core/src/lamtools_core/app/ 2>/dev/null | head -50; echo "---"; ls core/src/lamtools_core/ | __init__.py __pycache__ agent_app.py api_access.py approval_resolution… |
|  | search_content core/src/lamtools_core | 匹配34处；扫描775项：core/src/lamtools_core/app/base_agent.py:780: def _compose_system_prom… |
| 2 | ls core/src/lamtools_core/prompt/ core/src/lamtools_core/context_compaction/ 2>/dev/null | core/src/lamtools_core/context_compaction/: __init__.py __pycache__ co… |
|  | sed -n '760,1060p' core/src/lamtools_core/app/base_agent.py | argument, so it must lead with the real id the model resolver accepts;… |
| 3 | read_file core/src/lamtools_core/prompt/movable.py | """Movable system-context blocks with an epoch-frozen leading prompt. … |
|  | grep -rn "MOVABLE_CONTEXT_METADATA_KEY\|movable_epoch\|rebuild_movable_system_context\|render_mo | core/src/lamtools_core/app/base_agent.py:37: MOVABLE_CONTEXT_METADATA_… |
| 4 | sed -n '1150,1300p' core/src/lamtools_core/app/base_agent.py | ) if state.metadata is None: state.metadata = {} state.metadata[RUNTIM… |
|  | sed -n '4520,4630p' core/src/lamtools_core/kernel/loop.py | metrics.pop("context_usage_prompt_tokens", None) # Keep raw request-on… |
| 5 | sed -n '4630,4720p' core/src/lamtools_core/kernel/loop.py; echo "=== grep rebuild_movable calls  | final_request = replace(request, messages=replacement) final_tokens = … |
|  | ls core/src/lamtools_core/plugin_system/ | head -60; echo "=== waterfall ==="; sed -n '1,80p' co | __init__.py __pycache__ account_access.py agent.py agent_access.py age… |
| 6 | sed -n '80,260p' core/src/lamtools_core/plugin_system/prompt_waterfall.py | def get_section(self, name: str) -> PromptSection | None: for section … |
|  | sed -n '640,760p' core/src/lamtools_core/plugin_system/context.py | from .credential_controller import PluginCredentialController return P… |
| 7 | ls core/src/lamtools_core/plugin_system/prompt_extensions.py && sed -n '1,120p' core/src/lamtool | core/src/lamtools_core/plugin_system/prompt_extensions.py """user:“每一个… |
|  | find . -name "tools.jsonc" -not -path "*/node_modules/*" -not -path "*/.git/*" | sort | ./.build/plugin-rebuild/live/plugins/bili-scroll/tools/tools.jsonc ./.… |
| 8 | find core/src/lamtools_core/plugins/bundled plugins -name "tools.jsonc" 2>/dev/null | sort; echo | core/src/lamtools_core/plugins/bundled/imagegen/tools/tools.jsonc core… |
|  | grep -rn "STUDY_SYSTEM_PROMPT\|request_local_late_context\|auxiliary_read_only" --include=*.py c | core/src/lamtools_core/app/auxiliary_chat.py:60: if (row.get("metadata… |
| 9 | grep -n "def _register\|_register_tool\|name=\"" core/src/lamtools_core/tool/default_toolbox.py  | === wc === 3094 core/src/lamtools_core/tool/default_toolbox.py |
|  | for f in core/src/lamtools_core/plugins/bundled/imagegen/tools/tools.jsonc core/src/lamtools_cor | --- core/src/lamtools_core/plugins/bundled/imagegen/tools/tools.jsonc … |
| 10 | head -40 core/src/lamtools_core/plugins/bundled/study/tools.jsonc; echo "=== plan ==="; head -30 | { "tools": [ { "name": "get_knowledge_net", "description": "Read a sco… |
|  | grep -n "def \|ToolSpec\|register" core/src/lamtools_core/tool/default_toolbox.py | head -80 | 25:from lamtools_core.tool import ToolCall, ToolContext, ToolResult, T… |
| 11 | sed -n '451,470p' core/src/lamtools_core/tool/default_toolbox.py; echo "..."; sed -n '1080,1160p | def _schema(properties: dict[str, Any], required: list[str] | None = N… |
|  | grep -n "CORE_TOOL\|_TOOLS\s*=\|_SPECS\s*=" core/src/lamtools_core/tool/default_toolbox.py | hea | [command] cd /e/LamTools && grep -n "CORE_TOOL\|_TOOLS\s*=\|_SPECS\s*=… |
| 12 | grep -rn "DEFAULT_TOOL_ORDER\s*[:=]\|DEFAULT_TOOL_CATEGORIES\s*[:=]\|CONTEXT_HISTORY_TOOLS\s*[:= | core/src/lamtools_core/tool/context_history.py:230:CONTEXT_HISTORY_TOO… |
|  | ls .venv/Scripts/python.exe 2>/dev/null; python -c "import sys; print(sys.version)" 2>&1 | head  | 3.14.4 (tags/v3.14.4:23116f9, Apr 7 2026, 14:10:54) [MSC v.1944 64 bit… |
| 13 | sed -n '240,450p' core/src/lamtools_core/tool/default_toolbox.py | # 由宿主拒绝未经审批的声明，与 computer_use 一样不逐条弹审批)。 BROWSER_TOOL_NAME: AUTO_ALLOW… |
|  | sed -n '225,260p' core/src/lamtools_core/tool/context_history.py | except HistoryError as exc: return ToolResult(call_id=call.id, name=ca… |
| 14 | ls core/src/lamtools_core/plugins/bundled/; echo "=== git plugin ==="; ls core/src/lamtools_core | imagegen network-exploration pipeline-checker plan study websearch wor… |
|  | grep -c "\"name\"" core/src/lamtools_core/plugin_system/manager_tools.py; echo "---"; grep -n "^ | 9 --- 37:def plugin_manager_tool_specs() -> list[ToolSpec]: 92: "name"… |
| 15 | sed -n '30,150p' core/src/lamtools_core/plugin_system/manager_tools.py | def _session_id(call: ToolCall) -> str: metadata = call.metadata if is… |
|  | grep -rn "git_status" --include=*.py --include=*.jsonc --include=*.json core/src/lamtools_core | | core/src/lamtools_core/app/auxiliary_chat.py:14:READ_ONLY_TOOLS = froz… |
| 16 | python - <<'PY' import re, json, pathlib def strip_jsonc(t): out=[];i=0;n=len(t);in_str=False;es | [command] cd /e/LamTools && python - <<'PY' import re, json, pathlib d… |
|  | grep -c "ToolSpec(" core/src/lamtools_core/plugin_system/manager_tools.py; grep -n "PLUGIN_.*_TO | 5 21:PLUGIN_INSTALL_TOOL = "plugin_install" 22:PLUGIN_DEPS_TOOL = "plu… |
| 17 | python -c " import re, json, pathlib def strip(t): t = re.sub(r'^[ \t]*//.*$', '', t, flags=re.M | core\src\lamtools_core\plugins\bundled\imagegen\tools\tools.jsonc -> 1… |
|  | cat core/src/lamtools_core/plugins/bundled/websearch/tools/tools.jsonc; echo "=== imagegen ==="; | { "tools": [ { "name": "web_search", "permission": "auto_allow", "hand… |
| 18 | python -c " import ast, pathlib, collections def names_in_tuple(node): out=[] for el in node.elt | [command] cd /e/LamTools && python -c " import ast, pathlib, collectio… |
| 19 | python -c " import ast, pathlib, collections p = pathlib.Path('core/src/lamtools_core/tool/defau | CONTEXT_HISTORY_TOOLS 2 ['search_context', 'recall_context'] DEFAULT_T… |
| 20 | python -c " import ast, pathlib tb = ast.parse(pathlib.Path('core/src/lamtools_core/tool/default | starred: Name(id='CONTEXT_HISTORY_TOOLS', ctx=Load()) defs count 21 ['… |
| 21 | grep -rn "DEFAULT_TOOL_DEFINITIONS\|DEFAULT_TOOL_ORDER" --include=*.py core/src/lamtools_core |  | core/src/lamtools_core/tool/default_toolbox.py:251:DEFAULT_TOOL_ORDER:… |
|  | grep -n "\"name\": \"memory\"\|\"name\": MEMORY\|\"name\": \"library\"\|\"name\": DESKTOP\|\"nam | core/src/lamtools_core/tool/default_toolbox.py:584: "name": MEMORY_TOO… |
| 22 | python -c " import ast, pathlib, collections tb = ast.parse(pathlib.Path('core/src/lamtools_core | defs 27 ['read_file', 'list_dir', 'search_files', 'search_content', 'l… |
| 23 | grep -rn 'role="system"' --include=*.py core/src/lamtools_core | grep -v test | head -40 | core/src/lamtools_core/app/base_agent.py:1158: role="system", core/src… |
|  | sed -n '1,80p' core/src/lamtools_core/app/auxiliary_chat.py | """Read-only main-chat assistance: fresh semantic context and suppleme… |
| 24 | echo "=== controller 620-680 ==="; sed -n '620,680p' core/src/lamtools_core/context_compaction/c | === controller 620-680 === model_retries=request.model_retries, model_… |
|  | echo "=== loop 2220-2270 ==="; sed -n '2220,2270p' core/src/lamtools_core/kernel/loop.py; echo " | === loop 2220-2270 === turn_input.user_content if turn_input.user_cont… |
| 25 | echo "=== http_client 55-100 ==="; sed -n '55,100p' core/src/lamtools_core/llm/http_client.py; e | === http_client 55-100 === temperature: float = 0.2 thinking_supported… |
|  | echo "=== study 20-50 ==="; sed -n '20,50p' core/src/lamtools_core/plugins/bundled/study/backend | === study 20-50 === 'exam': 'study.exam', 'sign': 'study.sign', 'notes… |
| 26 | echo "=== plugin prompts usage ==="; grep -rn "context.prompts\|system_prompt_waterfall\|on_asse | === plugin prompts usage === plugins/qq-bot/qqbot/agent_bridge.py:125:… |
|  | echo "=== hook engine system ==="; grep -rn "additional_context\|system" --include=*.py core/src | === hook engine system === 61: if result.additional_context: 63: item … |
| 27 | sed -n '100,170p' plugins/qq-bot/qqbot/agent_bridge.py | self.data_dir = Path(data_dir) self.work_root = Path(work_root) self.l… |
|  | sed -n '225,270p' core/src/lamtools_core/plugin_system/hook_engine.py; echo "=== study plugin.js | return HookDecision(), audit except Exception as exc: audit = {"hook_i… |
| 28 | grep -rn "RUNTIME_CONTEXT_DELTA_KEY\s*=\|RUNTIME_CONTEXT_METADATA_KEY\s*=\|TAIL_SYSTEM_MESSAGE_M | core/src/lamtools_core/app/base_agent.py:344:def _runtime_context_text… |
|  | echo "=== superagent prompt ==="; grep -rn "instructions\|system" --include=*.py core/src/lamtoo | === superagent prompt === core/src/lamtools_core/superagent/models.py:… |
| 29 | grep -n "def mode_prompt_line" -A 30 core/src/lamtools_core/tool/loadtools.py; echo "=== dispatc | 138:def mode_prompt_line( 139- load_tools: LoadTools, 140- active_mode… |
|  | sed -n '340,430p' core/src/lamtools_core/app/base_agent.py | rendered = rendered[:_MODEL_TOOL_EVIDENCE_LIMIT] + "\n[tool evidence t… |
| 30 | grep -rn "BROWSER_TOOL_NAME =\|DESKTOP_OVERLAY_TOOL_NAME =\|MEMORY_TOOL_NAME =\|LIBRARY_TOOL_NAM | core/src/lamtools_core/agent.py:15:SUB_AGENT_TOOL_NAME = "sub_agent" c… |
|  | grep -rn "dispatch_brief_for" --include=*.py core/src/lamtools_core | head -5 | core/src/lamtools_core/app/base_agent.py:79:from lamtools_core.app.sup… |
| 31 | 输出正文 | — |

## Ox-4（r2/base，45 轮）

| 轮 | 动作 | 得到 |
| --- | --- | --- |
| 1 | search_content E:/LamTools/core/src/lamtools_core | 匹配34处；扫描775项：core/src/lamtools_core/app/base_agent.py:780: def _compose_system_prom… |
|  | search_content E:/LamTools | 匹配0处；扫描2602项：No matches found within the scan budget after visiting 2602 entries; t… |
| 2 | list_dir E:/LamTools/core/src/lamtools_core/prompt | __init__.py 7.0KB 2026-07-29 02:37 __pycache__/ movable.py 7.4KB 2026-… |
|  | read_file E:/LamTools/core/src/lamtools_core/app/base_agent.py | " not in content and artifact_metadata.get("stdout"): lines.append(f"s… |
| 3 | sed -n '760,1070p' core/src/lamtools_core/app/base_agent.py | argument, so it must lead with the real id the model resolver accepts;… |
|  | sed -n '1070,1360p' core/src/lamtools_core/app/base_agent.py | refresh = getattr(self.toolbox, "refresh_runtime_permissions", None) i… |
| 4 | read_file E:/LamTools/core/src/lamtools_core/prompt/movable.py | """Movable system-context blocks with an epoch-frozen leading prompt. … |
|  | search_files E:/LamTools/core/src/lamtools_core | 匹配1处；扫描892项：core/src/lamtools_core/plugin_system/prompt_waterfall.py |
| 5 | read_file E:/LamTools/core/src/lamtools_core/plugin_system/prompt_waterfall.py | """System-prompt waterfall for plugins. The upstream DSH host exposes … |
|  | sed -n '4540,4620p' core/src/lamtools_core/kernel/loop.py | "context_compaction_retained_steps": retained_steps, "context_compacte… |
| 6 | search_content E:/LamTools/core/src/lamtools_core | 匹配3处；扫描775项：core/src/lamtools_core/plugin_system/dsh_compat/migration.py:665: "- 已… |
|  | sed -n '4620,4760p' core/src/lamtools_core/kernel/loop.py | } await self._persist_runtime_context_metrics(state, history=history) … |
| 7 | search_content E:/LamTools/core/src/lamtools_core | 匹配23处；扫描775项：core/src/lamtools_core/app/base_agent.py:25: HISTORICAL_TAIL_SYSTEM_ME… |
|  | read_file E:/LamTools/core/src/lamtools_core/plugin_system/prompt_extensions.py | """user:“每一个地方 sunday 都有等价或者近似接口”+(提示词贡献绑定已有启动所有权，复用原提示词流水线)。""" from … |
| 8 | sed -n '2200,2290p' core/src/lamtools_core/kernel/loop.py; echo ===; sed -n '320,360p' core/src/ | previous_status, previous_owner.get("pid"), ) await self.state_store.s… |
|  | read_file E:/LamTools/core/src/lamtools_core/runtime/tool_freeze.py | """Freeze the model-visible tool array for one compaction cycle. user:… |
| 9 | search_content E:/LamTools/core/src/lamtools_core | 匹配4处；扫描775项：core/src/lamtools_core/app/base_agent.py:1124: retry = metadata.get("e… |
|  | search_content E:/LamTools/core/src/lamtools_core | 匹配14处；扫描775项：core/src/lamtools_core/app/base_agent.py:1119: verification_state.get(… |
| 10 | sed -n '1340,1460p' core/src/lamtools_core/app/base_agent.py | {"_runtime_context_delta": runtime_deltas} if runtime_deltas else {} )… |
|  | sed -n '1700,1760p' core/src/lamtools_core/app/base_agent.py | [record], run_id=state.run_id, turn_id=str(state.metadata.get("turn_id… |
| 11 | search_content E:/LamTools/core/src/lamtools_core | 匹配16处；扫描775项：core/src/lamtools_core/app/base_agent.py:1158: role="system", core/src… |
|  | search_content E:/LamTools/core/src/lamtools_core | 匹配16处；扫描775项：core/src/lamtools_core/app/base_agent.py:1610: # C2 共识：hook additional… |
| 12 | sed -n '40,100p' core/src/lamtools_core/llm/http_client.py; echo === SHALLOW; sed -n '30,110p' c | _logger = logging.getLogger(__name__) @dataclass(frozen=True) class LL… |
|  | read_file E:/LamTools/core/src/lamtools_core/runtime/context_delta.py | """Shared keys and predicate for append-only runtime context updates. … |
| 13 | sed -n '1,60p' core/src/lamtools_core/tool/loadtools.py; echo "=== mode_prompt_line"; grep -n "d | """Load-tools configuration: mode-based tool set management. Controls … |
|  | sed -n '1110,1160p' core/src/lamtools_core/llm/profiles.py; echo "=== 210-280 hook_engine"; sed  | fallback="off", ) if reasoning_effort and not reasoning_level and effe… |
| 14 | sed -n '80,140p' core/src/lamtools_core/context_compaction/state.py; echo "=== controller 600-68 | # the keyword; detect that shape without a second read. raw_history = … |
|  | sed -n '1,120p' core/src/lamtools_core/plugin_system/agent.py | """Agent takeover declarations: prompt, tools, approval, context and s… |
| 15 | sed -n '1,60p' core/src/lamtools_core/config/subagent_prompt.py; echo "=== grep defs"; grep -n " | """Sub-agent delegation guide prompt. Loads a natural-language markdow… |
|  | grep -n "_cached_subagent_guide\|_cached_subagent_roles\|_cached_subagent_strategy\|_build_proje | 575: prompt_waterfall: Any | None = None, 583: self.prompt_waterfall =… |
| 16 | sed -n '600,640p' core/src/lamtools_core/app/base_agent.py; echo ===; sed -n '740,760p' core/src | self.toolbox.disabled_tools.update(forbidden_subagent_tools) self.veri… |
|  | sed -n '240,260p' core/src/lamtools_core/config/subagent_prompt.py; echo ===; sed -n '420,450p'  | "sub-agents in parallel wherever possible. The main Agent remains resp… |
| 17 | for f in $(find . -name "plugin.json*" -o -name "plugin.jsonc" | sort); do echo "--- $f"; python | --- ./bundled/imagegen/plugin.json agent: none --- ./bundled/network-e… |
| 18 | ls tool/ && echo "=== tools.jsonc files" && find . -name "tools.jsonc" | sort | __init__.py __pycache__ android_use.py approval.py approval_continuati… |
|  | grep -n "class \|^def build_core_toolbox" tool/default_toolbox.py | head -60 | 191:class SubAgentRunner(Protocol): 1416:class CoreToolbox: 2056: # in… |
| 19 | sed -n '1416,1520p' tool/default_toolbox.py | class CoreToolbox: def __init__( self, *, work_root: str | Path, comma… |
|  | grep -n "def register\|self\._tools\[\|_add_tool\|add_tool(" tool/default_toolbox.py | head -40; | === tool modules register fns |
| 20 | grep -rc "ToolSpec(" tool/*.py tool/search/*.py 2>/dev/null | grep -v ":0" | sort -t: -k2 -rn; e | tool/durable_tools.py:2 tool/sub_agent_runner.py:1 tool/default_toolbo… |
|  | grep -n "def model_tools" -A 60 tool/default_toolbox.py | head -90 | 1851: def model_tools( 1852- self, 1853- *, 1854- include_tools: set[s… |
| 21 | grep -n "def tool_specs" -A 40 tool/default_toolbox.py | head -60; echo "=== imports of specs";  | 1791: def tool_specs(self) -> list[ToolSpec]: 1792- specs = [ 1793- re… |
| 22 | grep -n "self\._specs" tool/default_toolbox.py | head -20; echo "=== ToolSpec count in default_t | 1647: self._specs = [ 1654: tool_host.reserve(spec.name for spec in se… |
| 23 | sed -n '1060,1140p' tool/default_toolbox.py; echo "=== 1640,1665"; sed -n '1640,1670p' tool/defa | # user:“让 Agent Loop 能直接调用：打开/切换标签、快照、点击、输入、等待、截图”+ # (工具名用 browser，动作… |
| 24 | ls agent_docs/ 2>/dev/null | head -50; echo ===; ls agent_docs | grep -i "tool\|plugin" | 02_Sunday_桌宠_V1.0_功能清单_已填写.md a9_package_acceptance.md acceptance_1cf1… |
|  | grep -n "DEFAULT_TOOL_ORDER\s*=\|DEFAULT_TOOL_CATEGORIES\s*=" -A 40 tool/default_toolbox.py | he | [command] cd core/src/lamtools_core && grep -n "DEFAULT_TOOL_ORDER\s*=… |
| 25 | read_file E:/LamTools/agent_docs/system_prompt_and_tool_catalog.md | # Sunday 系统提示词与工具描述 · 代码地图与原文 > 生成方式：直接调用真实组装代码 `core/src/lamtools_cor… |
|  | grep -rn "DEFAULT_TOOL_ORDER" tool/*.py | head; echo ===; grep -rn "DEFAULT_TOOL_CATEGORIES" too | tool/default_toolbox.py:251:DEFAULT_TOOL_ORDER: tuple[str, ...] = ( to… |
| 26 | for f in $(find . -name tools.jsonc | sort); do echo "--- $f"; grep -c '"name"' $f; done; echo " | --- ./imagegen/tools/tools.jsonc 1 --- ./network-exploration/tools.jso… |
|  | sed -n '251,340p' tool/default_toolbox.py | DEFAULT_TOOL_ORDER: tuple[str, ...] = ( "read_file", "list_dir", "sear… |
| 27 | sed -n '1,60p' tool/durable_tools.py; echo "=== plugin_manager_specs"; grep -rn "plugin_manager_ | """Model-facing Goal and Arrange tools backed by the shared operation … |
|  | for f in $(find . -name tools.jsonc | sort); do echo "--- $f"; python -c " import sys,re,json t= | --- ./imagegen/tools/tools.jsonc 1 ['generate_image'] --- ./network-ex… |
| 28 | sed -n '1600,1620p' tool/default_toolbox.py; echo "=== def plugin_manager_tool_specs"; grep -rn  | # stays reserved for genuinely destructive operations. self._native_op… |
|  | grep -rn "PLUGIN_MANAGER_TOOL\|plugin-manager\|plugin_manager" tool/default_toolbox.py | head -2 | 1458: enable_plugin_manager: bool = False, 1604: from lamtools_core.pl… |
| 29 | grep -n "def plugin_manager_tool_specs" -A 40 plugin_system/manager_tools.py | head -60; echo "= | 37:def plugin_manager_tool_specs() -> list[ToolSpec]: 38- return [ 39-… |
| 30 | grep -n "PLUGIN_INSTALL_TOOL\s*=\|PLUGIN_[A-Z_]*_TOOL\s*=\|ToolSpec(" plugin_system/manager_tool | 21:PLUGIN_INSTALL_TOOL = "plugin_install" 22:PLUGIN_DEPS_TOOL = "plugi… |
| 31 | echo "=== git_status refs"; grep -rn "git_status" --include=*.py --include=*.json --include=*.js | === git_status refs ./app/auxiliary_chat.py:14:READ_ONLY_TOOLS = froze… |
|  | grep -rln "ToolSpec(" --include=*.py . | sort; echo "=== counts"; for f in $(grep -rln "ToolSpec | ./app/auxiliary_chat.py ./mcp/registry.py ./plugin_system/capabilities… |
| 32 | grep -rn "bundled_core_tool_specs" --include=*.py . | head; echo "=== resolve plugin specs"; gre | ./app/base_agent.py:2005: from lamtools_core.tool.default_toolbox impo… |
| 33 | sed -n '95,175p' plugin_system/runtime.py | metadata["overrides_core_tool"] = True return ToolSpec( name=tool.name… |
| 34 | ls | head; ls .venv/Scripts/python.exe 2>/dev/null; python -c "import sys; print(sys.version)" | Caddyfile Dockerfile LamTools README.md __pycache__ _swap_checkboxes.p… |
| 35 | python -c " import sys sys.path.insert(0,'src') from lamtools_core.tool.default_toolbox import d | default_core: 24 ['read_file', 'list_dir', 'search_files', 'search_con… |
| 36 | grep -rn "enable_plugin_manager" --include=*.py . | grep -v default_toolbox.py | head -10; echo  | ./app/default_agent.py:3907: enable_plugin_manager: bool = True, ./app… |
|  | sed -n '2000,2040p' app/base_agent.py; echo "=== auxiliary_chat spec"; sed -n '1,40p' app/auxili | from lamtools_core.plugin_system.agent_presets import build_agent_pres… |
| 37 | cat .lam/core/config/loadtools.jsonc 2>/dev/null | head -60 | // loadtools.jsonc — 模式工具集配置 // 每个模式是一个工具白名单：tools 为空数组表示该模式可使用全部工具（不限… |
|  | for d in study workflow; do echo "--- $d"; python -c " import json,re,sys p=sys.argv[1]+'/plugin | --- study {'name': 'study', 'scope': 'mode', 'mode': None, 'enabled': … |
| 38 | ls context_compaction/; echo "=== summary prompt"; grep -rn "SYSTEM\|system" context_compaction/ | __init__.py __pycache__ controller.py fallback.py fitter.py formatting… |
|  | grep -rn "ACTIVE_MODE\|active_mode" app/base_agent.py | grep -i "prompt\|mode" | head -10; echo  | 544: active_mode: str | None = None # loadtools.jsonc mode name (e.g. … |
| 39 | sed -n '60,130p' context_compaction/summarizer.py; echo "=== prompt text const"; grep -rn "SUMMA | summary_budget.max_input_tokens if summary_budget is not None else inp… |
| 40 | grep -rn "def goal_continuation_message" -A 20 kernel/*.py runtime/*.py 2>/dev/null | head -30 | runtime/goal_continuation.py:36:def goal_continuation_message(reminder… |
|  | grep -rn "register(" plugin_system/context.py | head -5; sed -n '680,700p' plugin_system/context | 96: return self._active_registration_scope().register(service_key(key)… |
| 41 | grep -rn "prompts\.\(section\|variable\|on_assemble\)" . 2>/dev/null | head -10; echo "=== any s | === any system_prompt_waterfall in plugins |
|  | ls 資料 2>/dev/null | head; ls core/.lam/plugins 2>/dev/null | head; ls .lam/plugins 2>/dev/null | | easynet imagegen.jsonc imagegen.lock network-exploration |
| 42 | grep -rn "prompts\.\(section\|variable\|on_assemble\)\|system_prompt" easynet 2>/dev/null | head | === easynet files data |
| 43 | grep -n "def _runtime_context_text" -A 60 app/base_agent.py | head -80 | 344:def _runtime_context_text(fields: Mapping[str, Any]) -> str: 345- … |
| 44 | ls; echo ===; grep -rn "browser\|plugin_install" access_tools.jsonc 2>/dev/null | head | AGENTS.md README.md access_tools.jsonc command hooks.json imagegen.jso… |
| 45 | 输出正文 | — |

## Ra-1（chain7/variant，32 轮）

| 轮 | 动作 | 得到 |
| --- | --- | --- |
| 1 | ls && echo "---" && ls core/src/lamtools_core/app/ | head -60 | 0.1.0 0.1.1 0.3.0 0.3.1 0.3.2 AGENTS.md CITATION.cff LICENSE MAINTENAN… |
|  | grep -rn "system_prompt" --include=*.py core/src | head -120 | core/src/lamtools_core/app/base_agent.py:780: def _compose_system_prom… |
| 2 | grep -rn "system_prompt_waterfall\|SystemPromptWaterfall\|waterfall" --include=*.py core/src | h | core/src/lamtools_core/app/base_agent.py:575: prompt_waterfall: Any | … |
|  | grep -rn "role=\"system\"\|role='system'\|role: \"system\"" --include=*.py core/src | head -80 | core/src/lamtools_core/app/base_agent.py:1158: role="system", core/src… |
| 3 | sed -n '760,1000p' core/src/lamtools_core/app/base_agent.py | argument, so it must lead with the real id the model resolver accepts;… |
|  | read_file core/src/lamtools_core/plugin_system/prompt_waterfall.py | """System-prompt waterfall for plugins. The upstream DSH host exposes … |
| 4 | read_file core/src/lamtools_core/plugin_system/prompt_extensions.py | """user:“每一个地方 sunday 都有等价或者近似接口”+(提示词贡献绑定已有启动所有权，复用原提示词流水线)。""" from … |
|  | read_file core/src/lamtools_core/prompt/movable.py | """Movable system-context blocks with an epoch-frozen leading prompt. … |
| 5 | sed -n '1140,1300p' core/src/lamtools_core/app/base_agent.py | } def emit_runtime_context_snapshot(self, state: RuntimeState) -> Chat… |
|  | sed -n '580,700p' core/src/lamtools_core/context_compaction/controller.py && echo "=== state.py  | "Context compaction failed to fit within limit: latest user " "message… |
| 6 | echo "=== loop.py 2200-2280" && sed -n '2200,2280p' core/src/lamtools_core/kernel/loop.py && ech | === loop.py 2200-2280 previous_status, previous_owner.get("pid"), ) aw… |
|  | grep -rn "TAIL_SYSTEM_MESSAGE_MARKER" --include=*.py core/src | head -40 && echo "=== agent pres | core/src/lamtools_core/app/base_agent.py:25: HISTORICAL_TAIL_SYSTEM_ME… |
| 7 | grep -rn "additional_context\|system_message\|systemMessage" --include=*.py core/src | grep -v " | core/src/lamtools_core/app/base_agent.py:1247: tail_system_messages: l… |
|  | sed -n '180,240p' core/src/lamtools_core/context_compaction/planner.py && echo "=== fitter 180-2 | def _protected_message_indexes( messages: list[ChatMessage], *, retain… |
| 8 | echo "=== context.py 660-720" && sed -n '660,720p' core/src/lamtools_core/plugin_system/context. | === context.py 660-720 cached = getattr(self, "_telemetry_api_cache", … |
|  | grep -rn "prompts.section\|prompts.variable\|prompts.on_assemble\|\.prompts\b" --include=*.py co | core/src/lamtools_core/member/kit.py:65: return sorted(self.prompts, k… |
| 9 | ls core/src/lamtools_core/tool/ && echo "=== tools.jsonc files" && find core/src/lamtools_core/p | __init__.py __pycache__ android_use.py approval.py approval_continuati… |
|  | grep -rn "class Toolbox\|def tools(\|\"name\": \"" --include=*.py core/src/lamtools_core/tool/*. | core/src/lamtools_core/tool/context_history.py:232: "name": "search_co… |
| 10 | for f in core/src/lamtools_core/tool/*.py core/src/lamtools_core/plugins/bundled/workflow/backen | 2 core/src/lamtools_core/tool/context_history.py 21 core/src/lamtools_… |
|  | head -60 core/src/lamtools_core/tool/default_toolbox.py && echo "..." && sed -n '440,520p' core/ | from __future__ import annotations from lamtools_core.tool.question_sp… |
| 11 | echo "== manager_tools" && grep -n "name=\|ToolSpec(\|\"name\"" core/src/lamtools_core/plugin_sy | == manager_tools 39: ToolSpec( 40: name=PLUGIN_INSTALL_TOOL, 83: ToolS… |
|  | for f in $(find core/src/lamtools_core/plugins -name "tools.jsonc"); do echo "--- $f"; grep -c ' | --- core/src/lamtools_core/plugins/bundled/imagegen/tools/tools.jsonc … |
| 12 | echo "=== plan tools.jsonc" && head -40 core/src/lamtools_core/plugins/bundled/plan/tools/tools. | === plan tools.jsonc { // The plan plugin ships skills only (draft-pla… |
|  | python - <<'EOF' import json,re,pathlib for p in pathlib.Path('core/src/lamtools_core/plugins'). | core\src\lamtools_core\plugins\bundled\network-exploration\tools.jsonc… |
| 13 | python - <<'EOF' import re,pathlib p=pathlib.Path('core/src/lamtools_core/tool/default_toolbox.p | 21 ['read_file', 'list_dir', 'search_files', 'search_content', 'load_s… |
|  | grep -n "PLUGIN_.*_TOOL\s*=\|^PLUGIN" core/src/lamtools_core/plugin_system/manager_tools.py | he | 21:PLUGIN_INSTALL_TOOL = "plugin_install" 22:PLUGIN_DEPS_TOOL = "plugi… |
| 14 | grep -n "DEFAULT_TOOL_DEFINITIONS\|_TOOL_NAME,\|durable_tool_specs\|SUB_AGENT_TOOL_SPEC\|BROWSER | 17: SUB_AGENT_MESSAGE_TOOL_NAME, 19: SUB_AGENT_TOOL_NAME, 20: SUB_AGEN… |
|  | grep -rn "def tool_specs" -A 80 core/src/lamtools_core/tool/default_toolbox.py | sed -n '1,120p' | 1791: def tool_specs(self) -> list[ToolSpec]: 1792- specs = [ 1793- re… |
| 15 | sed -n '1060,1180p' core/src/lamtools_core/tool/default_toolbox.py | # user:“让 Agent Loop 能直接调用：打开/切换标签、快照、点击、输入、等待、截图”+ # (工具名用 browser，动作… |
|  | sed -n '230,340p' core/src/lamtools_core/tool/default_toolbox.py | # user:“无需做安全边界”+(桌面操作不再走审批，模型可以连续执行多步任务)。 "computer_use": AUTO_ALLOW,… |
| 16 | sed -n '970,1000p' core/src/lamtools_core/tool/default_toolbox.py && echo "=== try import count" | ["action"], ), }, # user:“AI 直接在屏幕上标记、绘制、互动”+(标注层工具：一次画一组标记， # 按 id 清除… |
| 17 | sed -n '1,80p' core/src/lamtools_core/tool/durable_tools.py | """Model-facing Goal and Arrange tools backed by the shared operation … |
|  | grep -rn "tools.jsonc" --include=*.py core/src | head -20 && echo "=== other plugin tool decls i | core/src/lamtools_core/app/base_agent.py:544: active_mode: str | None … |
| 18 | grep -rn "name=\"[a-z_]*\"\|name=\"workflow" core/src/lamtools_core/plugins/bundled/workflow/bac | === workflow tools.jsonc names "name": "workflow_graph" "name": "workf… |
|  | sed -n '70,120p' core/src/lamtools_core/plugins/bundled/workflow/backend/tools.py && echo "=== b | for name, ptype, desc, is_required, default in input_ports: entry: dic… |
| 19 | ls core/src/lamtools_core/plugins/bundled/ && echo "=== git plugin?" && ls core/src/lamtools_cor | imagegen network-exploration pipeline-checker plan study websearch wor… |
|  | python - <<'EOF' import json,re,pathlib tot=0 for p in sorted(pathlib.Path('core/src/lamtools_co | bundled 1 ['generate_image'] bundled 1 ['network_download'] bundled 1 … |
| 20 | grep -rn "ToolSpec(" --include=*.py core/src | grep -v "isinstance\|import\|: ToolSpec\|-> ToolS | 5 core/src/lamtools_core/plugins/bundled/workflow/backend/build_tools.… |
|  | grep -rn "ToolSpec(" --include=*.py core/src/lamtools_core/tool/default_toolbox.py | head -20 && | 1087: return ToolSpec( === _STUDY_TOOL_PROTOCOL 200:_STUDY_TOOL_PROTOC… |
| 21 | grep -n "_apply_session_start_hook" -A 60 core/src/lamtools_core/kernel/loop.py | head -80 | 2216: await self._apply_session_start_hook(state, turn_input) 2217- 22… |
|  | sed -n '60,110p' core/src/lamtools_core/llm/http_client.py && echo "=== mode_prompt_line callers | provider_extra: dict[str, Any] = field(default_factory=dict) model_ext… |
| 22 | sed -n '1100,1140p' core/src/lamtools_core/app/base_agent.py && echo "=== loop 4059-4090" && sed | if not isinstance(step, dict): continue steps[str(step.get("id", "?"))… |
|  | echo "== plugin_compaction" && head -60 core/src/lamtools_core/app/plugin_compaction.py && echo  | == plugin_compaction """user:“每一个地方 sunday 都有等价或者近似接口”+(插件手动压缩复用桌面命令的运… |
| 23 | echo "== dispatch_brief_for" && grep -rn "def dispatch_brief_for" -A 25 core/src/lamtools_core/a | == dispatch_brief_for 36:def dispatch_brief_for(active_mode: object) -… |
|  | ls core/src/lamtools_core/plugins/bundled/study/prompts/ && echo "=== study plugin.json agents"  | study-system.md === study plugin.json agents === workflow plugin.json … |
| 24 | sed -n '1,165p' core/src/lamtools_core/plugin_system/agent.py | """Agent takeover declarations: prompt, tools, approval, context and s… |
|  | find core/src/lamtools_core/plugins -path "*agents*" -name "*.md" | head -20 && echo "---" && he | --- [stderr] head: cannot open '' for reading: No such file or directo… |
| 25 | for f in core/src/lamtools_core/plugins/bundled/*/plugin.json; do echo "--- $f"; python -c " imp | --- core/src/lamtools_core/plugins/bundled/imagegen/plugin.json scope … |
|  | cat core/src/lamtools_core/plugins/bundled/study/plugin.json && echo "=== workflow plugin.json"  | { "id": "study", "name": "study", "version": "2.0.0", "description": "… |
| 26 | sed -n '400,470p' core/src/lamtools_core/tool/sub_agent_runner.py && echo "=== 1100-1160" && sed | independent_mcp = MCPToolRegistry( self.work_root, config_files=list(s… |
|  | grep -rn "repair_prompt" --include=*.py core/src | head -20 && echo "=== empty_stop_retry_instru | core/src/lamtools_core/app/base_agent.py:1119: verification_state.get(… |
| 27 | grep -n "context" core/src/lamtools_core/plugin_system/capabilities.py | head -30 && echo "=== r | 100: context: list[PluginContextSpec] = field(default_factory=list) 34… |
|  | grep -rn "active_mode" --include=*.py core/src/lamtools_core/app/live/turn_options.py | head -20 | 27:async def _latest_persisted_active_mode(*, context: "CoreLiveContex… |
| 28 | grep -rn "notes=" --include=*.py core/src/lamtools_core | grep -v "dsh_compat" | head -20 && ech | core/src/lamtools_core/app/http_agent_app.py:2373: notes=str(payload.g… |
|  | grep -rn "_messages_with_model_notes\|notes" core/src/lamtools_core/llm/adapter.py | head -20 && | === model notes source core/src/lamtools_core/cli.py:326: _messages_wi… |
| 29 | sed -n '320,360p' core/src/lamtools_core/kernel/loop.py && echo "=== shallow thinking enabled" & | message = replace( message, metadata={ key: value for key, value in me… |
|  | head -60 agent_docs/plugin_prompt_extensions.md 2>/dev/null || ls agent_docs | head -40 | # 插件提示词扩展 v1 <!-- user:“宿主能力补齐和接口完善与文档更新，自动化兼容脚本，脚本不必能处理所有问题，剩下问题交给 ag… |
| 30 | grep -rn "merge_system_messages" --include=*.py core/src | head && echo "=== cache_diagnostics 1 | core/src/lamtools_core/llm/__init__.py:233:def merge_system_messages(m… |
|  | sed -n '1425,1450p' core/src/lamtools_core/app/base_agent.py && echo "=== durable gating 1570-16 | "The previous model turn stopped with no final text and no tool calls.… |
| 31 | grep -rn "bundled_core_tool_specs" --include=*.py core/src | head && echo "=== git tools jsonc?" | core/src/lamtools_core/app/base_agent.py:2005: from lamtools_core.tool… |
| 32 | 输出正文 | — |

## Ra-2（chain8/variant，25 轮）

| 轮 | 动作 | 得到 |
| --- | --- | --- |
| 1 | ls core/src/lamtools_core/app/ 2>/dev/null | head -50; echo "---"; ls core/src/lamtools_core/ |  | __init__.py __pycache__ agent_app.py api_access.py approval_resolution… |
|  | grep -rn "system_prompt" --include=*.py core/src/lamtools_core/ | grep -vi "test" | head -80 | core/src/lamtools_core/app/base_agent.py:780: def _compose_system_prom… |
| 2 | echo "=== system_prompt_waterfall 定义/使用 ===" && grep -rn "system_prompt_waterfall\|SystemPromptW | === system_prompt_waterfall 定义/使用 === core/src/lamtools_core/app/base_… |
|  | echo "=== compaction 注入提示 ===" && grep -rn "compaction" --include=*.py core/src/lamtools_core/co | === compaction 注入提示 === core/src/lamtools_core/context_compaction/cont… |
|  | find . -name "tools.jsonc" -not -path "*/node_modules/*" | sort | ./.build/plugin-rebuild/live/plugins/bili-scroll/tools/tools.jsonc ./.… |
| 3 | cat core/src/lamtools_core/plugin_system/prompt_waterfall.py | """System-prompt waterfall for plugins. The upstream DSH host exposes … |
|  | sed -n '660,720p' core/src/lamtools_core/plugin_system/context.py | cached = getattr(self, "_telemetry_api_cache", None) if cached is None… |
|  | sed -n '1990,2140p' core/src/lamtools_core/app/base_agent.py | *, data_dir: str | Path, work_root: str | Path, ) -> None: """Create/r… |
| 4 | echo "=== waterfall.assemble 调用点 ===" && grep -rn "\.assemble(\|prompt_waterfall\|waterfall" --i | === waterfall.assemble 调用点 === core/src/lamtools_core/app/base_agent.p… |
|  | ls core/src/lamtools_core/plugin_system/ && echo "=== prompt_extensions.py ===" && wc -l core/sr | __init__.py __pycache__ account_access.py agent.py agent_access.py age… |
| 5 | sed -n '900,1000p' core/src/lamtools_core/app/base_agent.py | if not study_mode and self.plugin_context_files: from lamtools_core.pr… |
|  | ls core/src/lamtools_core/tool/ | head -60 && echo "=== toolbox ===" && grep -n "def default_cor | __init__.py __pycache__ android_use.py approval.py approval_continuati… |
| 6 | sed -n '1060,1160p' core/src/lamtools_core/tool/default_toolbox.py && echo "=== head ===" && sed | # user:“让 Agent Loop 能直接调用：打开/切换标签、快照、点击、输入、等待、截图”+ # (工具名用 browser，动作… |
|  | find core/src/lamtools_core/plugins -name "*.jsonc" | sort && echo "=== top plugins ===" && ls p | core/src/lamtools_core/plugins/bundled/imagegen/config/schema.jsonc co… |
| 7 | ls core/src/lamtools_core/plugins/bundled/ && echo "=== DEFAULT_TOOL_ORDER ===" && grep -n "DEFA | imagegen network-exploration pipeline-checker plan study websearch wor… |
|  | for f in core/src/lamtools_core/plugins/bundled/*/tools.jsonc core/src/lamtools_core/plugins/bun | ### core/src/lamtools_core/plugins/bundled/network-exploration/tools.j… |
| 8 | echo "=== plan/tools/tools.jsonc ===" && head -40 core/src/lamtools_core/plugins/bundled/plan/to | === plan/tools/tools.jsonc === { // The plan plugin ships skills only … |
|  | echo "=== manager_tools.py ===" && grep -n "name\":" core/src/lamtools_core/plugin_system/manage | === manager_tools.py === 92: "name": {"type": "string", "description":… |
| 9 | python -c " import re,json,pathlib p=pathlib.Path('core/src/lamtools_core/tool/default_toolbox.p | DEFAULT_TOOL_ORDER count = 29 ['"read_file"', '"list_dir"', '"search_f… |
|  | grep -rn "git_status\|git_diff" --include=*.jsonc core/src/ plugins/ | head -20; echo "=== top p | === top plugins tools === plugins/bili-scroll/tools/tools.jsonc plugin… |
| 10 | grep -rn "git_status" --include=*.py core/src/lamtools_core/ | grep -v test | head -20; echo "== | core/src/lamtools_core/app/auxiliary_chat.py:14:READ_ONLY_TOOLS = froz… |
|  | sed -n '37,150p' core/src/lamtools_core/plugin_system/manager_tools.py | def plugin_manager_tool_specs() -> list[ToolSpec]: return [ ToolSpec( … |
| 11 | sed -n '780,900p' core/src/lamtools_core/app/base_agent.py | def _compose_system_prompt( self, state: RuntimeState, *, study_mode: … |
|  | cat core/src/lamtools_core/prompt/movable.py | """Movable system-context blocks with an epoch-frozen leading prompt. … |
| 12 | echo "=== plan_movable_context 调用 ===" && grep -rn "plan_movable_context\|rebuild_movable_system | === plan_movable_context 调用 === core/src/lamtools_core/app/base_agent.… |
|  | echo "=== mode_tool_set / active_mode ===" && grep -rn "mode_tool_set\|active_mode\b" --include= | === mode_tool_set / active_mode === core/src/lamtools_core/app/auxilia… |
| 13 | sed -n '1120,1300p' core/src/lamtools_core/app/base_agent.py | ).strip() verification["evidence_call_ids"] = [ str(item) for item in … |
|  | sed -n '4530,4600p' core/src/lamtools_core/kernel/loop.py | request.metadata["reserved_output_tokens"] = reserved_output_tokens re… |
| 14 | grep -n "rebuild_movable\|MOVABLE_CONTEXT\|context_compaction_summary\|emit_runtime_context_snap | 49: HISTORICAL_TAIL_SYSTEM_MESSAGE_MARKER, 50: TAIL_SYSTEM_MESSAGE_MAR… |
|  | grep -n "def mode_prompt_line\|def dispatch_brief_for\|def mode_tool_set\|MODE_\|mode =" core/sr | 43:LEGACY_MODE_NAMES: dict[str, str] = {"consider": "chat", "execute":… |
| 15 | sed -n '4610,4680p' core/src/lamtools_core/kernel/loop.py; echo "=== 2230-2270 ==="; sed -n '223 | message = ( f"{message} The turn stopped without sending an oversized … |
|  | sed -n '1,200p' core/src/lamtools_core/tool/loadtools.py | """Load-tools configuration: mode-based tool set management. Controls … |
| 16 | grep -rn 'role="system"' --include=*.py core/src/lamtools_core/ | grep -v test | head -40 | core/src/lamtools_core/app/base_agent.py:1158: role="system", core/src… |
|  | echo "=== hooks 改 prompt? ===" && grep -rn "system\|prompt" --include=*.py core/src/lamtools_cor | === hooks 改 prompt? === 92: if hook.handler.type == "prompt": 93: retu… |
| 17 | echo "=== llm/__init__.py 220-260 ===" && sed -n '215,265p' core/src/lamtools_core/llm/__init__. | === llm/__init__.py 220-260 === if self.error: d["error"] = self.error… |
|  | sed -n '600,640p' core/src/lamtools_core/http/routes.py; echo "=== compaction/state 100-125 ===" | approval_policy = "require" if request.headers.get("origin") is not No… |
| 18 | echo "=== 顶层插件工具清单 ===" && for f in plugins/*/tools/tools.jsonc; do echo "### $f"; python -c " i | === 顶层插件工具清单 === ### plugins/bili-scroll/tools/tools.jsonc tools: 8 ['… |
|  | echo "=== 内置插件工具清单(解析) ===" && python -c " import json,re,pathlib files={ 'imagegen':'core/src/l | === 内置插件工具清单(解析) === imagegen: 1 -> ['generate_image'] network-explora… |
| 19 | python -c " import sys; sys.path.insert(0,'core/src') from lamtools_core.tool.default_toolbox im | android_control_available = False base count = 24 ['read_file', 'list_… |
|  | echo "=== with_shallow_thinking_prompt 调用 ===" && grep -rn "with_shallow_thinking_prompt\|_messa | === with_shallow_thinking_prompt 调用 === core/src/lamtools_core/cli.py:… |
| 20 | grep -n "def resolve_agent_plan" -A 45 core/src/lamtools_core/plugin_system/agent.py | head -60; | 166:def resolve_agent_plan( 167- agents: list[PluginAgentSpec], 168- *… |
|  | grep -n "AUXILIARY_INSTRUCTIONS" -A 20 core/src/lamtools_core/app/auxiliary_chat.py | head -40;  | 15:AUXILIARY_INSTRUCTIONS = ( 16- "You are the read-only assistant to … |
| 21 | sed -n '240,285p' core/src/lamtools_core/context_compaction/fitter.py; echo "=== adapter system  | """Return source-ordered drop units, keeping assistant/tool pairs.""" … |
|  | grep -rn "HISTORICAL_TAIL_SYSTEM_MESSAGE_MARKER\|TAIL_SYSTEM_MESSAGE_MARKER" --include=*.py core | core/src/lamtools_core/llm/profiles.py:19: HISTORICAL_TAIL_SYSTEM_MESS… |
| 22 | sed -n '1100,1150p' core/src/lamtools_core/llm/profiles.py | payload, profile=profile, thinking_budget=thinking_budget, reasoning_l… |
|  | echo "=== 会话中途 active_mode / instructions 变更 ===" && sed -n '1010,1060p' core/src/lamtools_core/ | === 会话中途 active_mode / instructions 变更 === return set() allowed = ( "r… |
| 23 | grep -rn "plugin_manager_tool_specs" --include=*.py core/src/ | head; echo "=== sub agent prompt | core/src/lamtools_core/plugin_system/manager_tools.py:37:def plugin_ma… |
|  | sed -n '200,240p' core/src/lamtools_core/tool/loadtools.py | ), "work": LoadToolMode( description="工作模式：使用全部工具，在这一轮里把事做完", tools=[]… |
| 24 | grep -n "def _messages_with_model_notes" core/src/lamtools_core/llm/http_client.py; grep -n "SHA | 65:def _messages_with_model_notes( 12:SHALLOW_THINKING_PROMPT = f"""Yo… |
|  | grep -n "context_compaction_summary" core/src/lamtools_core/context_compaction/state.py | head;  | 101: and message.metadata.get("key") == "context_compaction_summary" 1… |
| 25 | 输出正文 | — |

## Ra-3（r1/variant，45 轮）

| 轮 | 动作 | 得到 |
| --- | --- | --- |
| 1 | ls && echo "---" && ls core/src/lamtools_core/app/ | head -50 | 0.1.0 0.1.1 0.3.0 0.3.1 0.3.2 AGENTS.md CITATION.cff LICENSE MAINTENAN… |
|  | grep -rn "system_prompt" --include="*.py" core/src/lamtools_core/ -l | head -60 | core/src/lamtools_core/app/base_agent.py core/src/lamtools_core/kernel… |
| 2 | grep -rn "system_prompt" --include="*.py" core/src/lamtools_core/app/base_agent.py | head -80 | 780: def _compose_system_prompt( 992: system_prompt, blocks = self._co… |
|  | ls core/src/lamtools_core/prompt/ && echo "=== kernel ===" && ls core/src/lamtools_core/kernel/ | __init__.py __pycache__ movable.py === kernel === __init__.py __pycach… |
| 3 | sed -n '760,1010p' core/src/lamtools_core/app/base_agent.py | argument, so it must lead with the real id the model resolver accepts;… |
|  | sed -n '1980,2200p' core/src/lamtools_core/app/base_agent.py | return run_items def core_events_to_snapshot(events: list[CoreEvent], … |
| 4 | wc -l core/src/lamtools_core/prompt/movable.py core/src/lamtools_core/app/plugin_compaction.py c | 215 core/src/lamtools_core/prompt/movable.py 49 core/src/lamtools_core… |
|  | grep -rn "system_prompt" core/src/lamtools_core/kernel/loop.py | head -40 && echo "=== waterfall | 4572: if isinstance(epoch, dict) and isinstance(epoch.get("system_prom… |
| 5 | cat core/src/lamtools_core/prompt/movable.py | """Movable system-context blocks with an epoch-frozen leading prompt. … |
|  | cat core/src/lamtools_core/app/plugin_compaction.py && echo "=== prompt_extensions ===" && cat c | """user:“每一个地方 sunday 都有等价或者近似接口”+(插件手动压缩复用桌面命令的运行认领、控制记录和取消流程)。""" fr… |
| 6 | sed -n '1140,1360p' core/src/lamtools_core/app/base_agent.py | } def emit_runtime_context_snapshot(self, state: RuntimeState) -> Chat… |
|  | grep -rn "append_section\|replace_section\|prompt_waterfall\|system_prompt" --include="*.py" cor | core/src/lamtools_core/plugins/bundled/study/backend.py:27:def _load_s… |
| 7 | sed -n '1,80p' core/src/lamtools_core/plugins/bundled/study/backend.py && echo "=== STUDY prompt | from __future__ import annotations import asyncio import hashlib impor… |
|  | grep -rn "system_prompt\|append_section\|prompt" --include="*.py" core/src/lamtools_core/plugin_ | 92: if hook.handler.type == "prompt": 93: return self._run_prompt_hook… |
| 8 | grep -rn "additional_context" --include="*.py" core/src/lamtools_core/ | grep -v test | head -30 | core/src/lamtools_core/app/base_agent.py:1610: # C2 共识：hook additional… |
|  | ls core/src/lamtools_core/tool/ && echo "=== default_toolbox head ===" && grep -n "def \|ToolSpe | __init__.py __pycache__ android_use.py approval.py approval_continuati… |
| 9 | sed -n '451,520p' core/src/lamtools_core/tool/default_toolbox.py && echo "..." && sed -n '1040,1 | def _schema(properties: dict[str, Any], required: list[str] | None = N… |
|  | wc -l core/src/lamtools_core/tool/default_toolbox.py && grep -c "name=" core/src/lamtools_core/t | 3094 core/src/lamtools_core/tool/default_toolbox.py 53 98:_WORKFLOW_CO… |
| 10 | grep -rn "DEFAULT_TOOL_ORDER" --include="*.py" core/src/lamtools_core/ | grep -v test | head -10 | core/src/lamtools_core/tool/default_toolbox.py:251:DEFAULT_TOOL_ORDER:… |
|  | find . -name "tools.jsonc" -not -path "*/node_modules/*" | head -40 && echo "=== count ===" && f | ./.build/plugin-rebuild/live/plugins/bili-scroll/tools/tools.jsonc ./.… |
| 11 | sed -n '240,455p' core/src/lamtools_core/tool/default_toolbox.py | # 由宿主拒绝未经审批的声明，与 computer_use 一样不逐条弹审批)。 BROWSER_TOOL_NAME: AUTO_ALLOW… |
|  | find core/src/lamtools_core/plugins plugins -name "tools.jsonc" 2>/dev/null | sort | core/src/lamtools_core/plugins/bundled/imagegen/tools/tools.jsonc core… |
| 12 | ls core/src/lamtools_core/plugins/bundled/ && echo "=== workflow build_tools ===" && grep -n "\" | imagegen network-exploration pipeline-checker plan study websearch wor… |
|  | for f in core/src/lamtools_core/plugins/bundled/*/tools.jsonc core/src/lamtools_core/plugins/bun | ### core/src/lamtools_core/plugins/bundled/network-exploration/tools.j… |
| 13 | head -60 core/src/lamtools_core/plugins/bundled/study/tools.jsonc && echo "===== plan =====" &&  | { "tools": [ { "name": "get_knowledge_net", "description": "Read a sco… |
|  | sed -n '30,150p' core/src/lamtools_core/plugin_system/manager_tools.py | def _session_id(call: ToolCall) -> str: metadata = call.metadata if is… |
| 14 | sed -n '1,130p' core/src/lamtools_core/tool/default_toolbox.py | from __future__ import annotations from lamtools_core.tool.question_sp… |
|  | sed -n '20,215p' core/src/lamtools_core/plugins/bundled/workflow/backend/build_tools.py | OperationExecutor = Callable[[str, dict[str, Any], dict[str, Any]], Aw… |
| 15 | PYTHONPATH=core/src python -c " from lamtools_core.tool.default_toolbox import default_core_tool | DEFAULT_TOOL_ORDER 29 default_core_tool_specs 24 ['read_file', 'list_d… |
|  | PYTHONPATH=core/src python -c " import re,json,pathlib def strip(s): s=re.sub(r'//[^\n]*','',s)  | 1 core/src/lamtools_core/plugins/bundled\imagegen\tools\tools.jsonc ['… |
| 16 | ls -d core/src/lamtools_core/plugins/bundled/*/ && grep -rn "git_status" --include="*.jsonc" cor | core/src/lamtools_core/plugins/bundled/imagegen/ core/src/lamtools_cor… |
|  | sed -n '1780,1910p' core/src/lamtools_core/tool/default_toolbox.py | The generic callback keeps those stale snapshots from advertising or e… |
| 17 | PYTHONPATH=core/src python -c " from lamtools_core.tool.durable_tools import durable_tool_specs  | goal+arrange ['goal', 'arrange'] none [] core/src/lamtools_core/app/ht… |
|  | ls core/src/lamtools_core/plugins/bundled/*/plugin.jsonc 2>/dev/null; echo "---git---"; grep -rl | ---git--- core/src/lamtools_core/app/auxiliary_chat.py core/src/lamtoo… |
| 18 | ls core/src/lamtools_core/plugins/bundled/study/ core/src/lamtools_core/plugins/bundled/workflow | core/src/lamtools_core/plugins/bundled/study/: __init__.py __pycache__… |
|  | sed -n '2190,2260p' core/src/lamtools_core/app/http_agent_app.py | from lamtools_core.config.root import core_config_file from lamtools_c… |
| 19 | grep -rln "\"git" core/src/lamtools_core/plugins/bundled/*/plugin.json 2>/dev/null; ls core/src/ | config plugin.json tools === imagegen plugin.json === { "name": "image… |
|  | grep -n "def _read_tools" -A 60 core/src/lamtools_core/plugin_system/capabilities.py | head -80 | 135:def _read_tools(manifest: PluginManifest) -> list[PluginToolSpec]:… |
| 20 | grep -rn "bundled_core_tool_specs" --include="*.py" core/src/lamtools_core/ | head -20 | core/src/lamtools_core/app/base_agent.py:2005: from lamtools_core.tool… |
|  | grep -rn "plugin_manager_tool_specs\|_exclusive_tool_modes\|EXCLUSIVE" --include="*.py" core/src | core/src/lamtools_core/plugin_system/manager_tools.py:37:def plugin_ma… |
| 21 | sed -n '1500,1660p' core/src/lamtools_core/tool/default_toolbox.py | # 用量账本与启停账本同目录；只读面板与记账共用同一文件。 self.skill_usage_store = skill_usage_sto… |
| 22 | sed -n '4480,4640p' core/src/lamtools_core/kernel/loop.py | llm_client=self.llm_client, estimate_request_tokens=lambda messages, f… |
|  | grep -rn "rebuild_movable_system_context\|emit_runtime_context_snapshot\|RUNTIME_CONTEXT_METADAT | core/src/lamtools_core/app/base_agent.py:63: RUNTIME_CONTEXT_DELTA_KEY… |
| 23 | grep -n "_runtime_context_fields" -A 60 core/src/lamtools_core/app/base_agent.py | sed -n '1,90p | 1076: def _runtime_context_fields( 1077- self, 1078- state: RuntimeSta… |
|  | grep -rn 'role="system"' --include="*.py" core/src/lamtools_core/app/ core/src/lamtools_core/ker | core/src/lamtools_core/app/base_agent.py:1158: role="system", core/src… |
| 24 | sed -n '2210,2270p' core/src/lamtools_core/kernel/loop.py && echo "=== 4095-4130 ===" && sed -n  | # state.metadata instead of holding a separate policy reference. if st… |
|  | grep -n "system\|prompt" core/src/lamtools_core/app/auxiliary_chat.py | head -30 && echo "=== qq | === qqbot 100-170 === self.data_dir = Path(data_dir) self.work_root = … |
| 25 | grep -rn "def mode_prompt_line" -A 25 core/src/lamtools_core/tool/loadtools.py | head -40; echo  | 138:def mode_prompt_line( 139- load_tools: LoadTools, 140- active_mode… |
|  | python -c " import json,re,pathlib p=pathlib.Path('core/src/lamtools_core/plugins/bundled/study/ | { "id": "study", "name": "study", "version": "2.0.0", "description": "… |
| 26 | python -c " import json,pathlib,re t=pathlib.Path('core/src/lamtools_core/plugins/bundled/study/ | "agent": { "mode": "study", "prompt": "./prompts/study-system.md", "ap… |
|  | grep -rn "def resolve_agent_plan" -A 60 core/src/lamtools_core/plugin_system/agent.py | head -80 | 166:def resolve_agent_plan( 167- agents: list[PluginAgentSpec], 168- *… |
| 27 | cat core/src/lamtools_core/runtime/context_delta.py && ls core/src/lamtools_core/runtime/ && ech | """Shared keys and predicate for append-only runtime context updates. … |
|  | grep -rn "_cached_subagent_guide\|_cached_subagent_roles\|_cached_subagent_strategy" -A 25 core/ | 607: def _cached_subagent_guide(self) -> str: 608- if self._subagent_g… |
| 28 | grep -rn "class .*Compaction\|replacement_messages" --include="*.py" core/src/lamtools_core/ | g | core/src/lamtools_core/app/plugin_compaction.py:8:class PluginCompacti… |
|  | grep -rn "movable\|system_prompt\|runtime_context" --include="*.py" core/src/lamtools_core/runti | 25: """Use the movable-context epoch so compaction starts a fresh free… |
| 29 | grep -rn "request_local_late_context\|agent_preset_prompt" --include="*.py" core/src/lamtools_co | core/src/lamtools_core/app/auxiliary_chat.py:60: if (row.get("metadata… |
|  | grep -rn "TAIL_SYSTEM_MESSAGE_MARKER" --include="*.py" core/src/lamtools_core/ | grep -v test |  | core/src/lamtools_core/app/base_agent.py:25: HISTORICAL_TAIL_SYSTEM_ME… |
| 30 | grep -rn "Instructions from:" --include="*.py" core/src/lamtools_core/ | grep -v test | head -10 | core/src/lamtools_core/app/base_agent.py:919: content=f"Instructions f… |
|  | grep -rn "memory/INDEX.md\|INDEX.md" --include="*.py" core/src/lamtools_core/app/project_context | core/src/lamtools_core/tool/memory_tools.py:5:generated ``INDEX.md`` i… |
| 31 | sed -n '24,110p' core/src/lamtools_core/app/project_context.py && grep -rn "project_context_file | class ContextConfig: addition: list[dict[str, object]] = field(default… |
|  | ls core/.lam/core/config/ 2>/dev/null; ls .lam/core/config/ 2>/dev/null | head -20; grep -rn "me | AGENTS.md README.md access_tools.jsonc command hooks.json imagegen.jso… |
| 32 | cat core/.lam/core/config/load_context.jsonc 2>/dev/null | head -40; echo "=== DEFAULT_PROJECT_C | // 全局上下文加载配置（load_context） // addition: 追加加载的上下文文件（相对工作区根或绝对路径） // exc… |
|  | ls core/ && echo "=== rust? ===" && ls core/rust 2>/dev/null; grep -rln "system_prompt\|systemPr | Caddyfile Dockerfile LamTools README.md __pycache__ _swap_checkboxes.p… |
| 33 | grep -n "system_prompt\|fn \|struct \|movable\|epoch\|notice" core/sunday-core/crates/sunday-con | 19:pub struct Policy { 29: fn default() -> Self { 40: fn summarize(&se… |
|  | grep -n "system_prompt\|system" core/sunday-core/crates/sunday-llm/src/anthropic.rs | head -30 & | 4://! the system prompt is a top-level field, `max_tokens` is mandator… |
| 34 | grep -rn "system_prompt\|instructions" --include="*.rs" core/sunday-core/crates/sunday-agent/src | core/sunday-core/crates/sunday-agent/src/lib.rs:84: /// Moves pending … |
|  | grep -rn "fn .*spec\|ToolSpec\|registry" --include="*.rs" core/sunday-core/crates/sunday-tools/s | core/sunday-core/crates/sunday-tools/src/file_read.rs:8: CoreError, Ho… |
| 35 | head -20 core/src/lamtools_core/plugins/bundled/websearch/tools/tools.jsonc && echo "=== imagege | { "tools": [ { "name": "web_search", "permission": "auto_allow", "hand… |
|  | cat core/runtime-rs/pyproject.toml 2>/dev/null | head -20; grep -rn "sunday_core\|runtime_rs" -- | core/src/lamtools_core/app/rust_db.py:1:"""Python bridge to the native… |
| 36 | sed -n '190,240p' core/src/lamtools_core/plugin_system/capabilities.py; echo "=== loadtools.json | tools.append( PluginToolSpec( name=name, handler=handler, description=… |
| 37 | sed -n '985,1035p' core/src/lamtools_core/kernel/loop.py; echo "=== _frozen_tools ==="; grep -n  | cut = len(history) - max_hist while cut > 0 and history[cut].role == "… |
| 38 | sed -n '1,60p' core/src/lamtools_core/plugin_system/agent_presets.py && grep -n "def \|class " c | """Host-owned agent presets. An agent preset is a named bundle applied… |
| 39 | grep -rn "INDEX.md" --include="*.py" core/src/lamtools_core/ | grep -v test | head -20 | core/src/lamtools_core/app/http_agent_app.py:2787: ``INDEX.md`` is gen… |
|  | sed -n '1136,1147p' core/src/lamtools_core/app/base_agent.py | "processes": processes, "plan": plan, "verification": verification, "e… |
| 40 | sed -n '95,170p' core/src/lamtools_core/config/defaults.py; grep -rn "context_files\|project_con | config_dir.mkdir(parents=True, exist_ok=True) except OSError: _log.war… |
| 41 | grep -rn "project_context_files=" --include="*.py" core/src/lamtools_core/ | grep -v test | head | [command] cd /e/LamTools && grep -rn "project_context_files=" --includ… |
| 42 | grep -n "memory\|index" core/src/lamtools_core/app/project_context.py | head -30 | 10:from lamtools_core.mem import library as memory_library 69: # user:… |
| 43 | ls plugins/ && echo "=== plugin dirs with plugin.json ===" && ls plugins/*/plugin.json 2>/dev/nu | bili-scroll excalidraw lamtools-rag qq-bot === plugin dirs with plugin… |
| 44 | sed -n '95,135p' core/src/lamtools_core/plugin_system/runtime.py | metadata["overrides_core_tool"] = True return ToolSpec( name=tool.name… |
| 45 | 输出正文 | — |

## Ra-4（r2/variant，47 轮）

| 轮 | 动作 | 得到 |
| --- | --- | --- |
| 1 | ls && echo "---" && ls core/src/lamtools_core/app/ | head -50 | 0.1.0 0.1.1 0.3.0 0.3.1 0.3.2 AGENTS.md CITATION.cff LICENSE MAINTENAN… |
|  | search_content core/src/lamtools_core | 匹配34处；扫描775项：core/src/lamtools_core/app/base_agent.py:780: def _compose_system_prom… |
| 2 | sed -n '760,1060p' core/src/lamtools_core/app/base_agent.py | argument, so it must lead with the real id the model resolver accepts;… |
|  | sed -n '2020,2200p' core/src/lamtools_core/app/base_agent.py | command_names = {c.name for c in load_command_catalog(core_roots=defau… |
| 3 | ls core/src/lamtools_core/prompt/ && echo "=== movable.py ===" && cat core/src/lamtools_core/pro | __init__.py __pycache__ movable.py === movable.py === """Movable syste… |
|  | cat core/src/lamtools_core/plugin_system/prompt_waterfall.py | """System-prompt waterfall for plugins. The upstream DSH host exposes … |
| 4 | grep -rn "plan_movable_context\|format_movable_context_notice\|rebuild_movable_system_context\|m | core/src/lamtools_core/app/base_agent.py:40: format_movable_context_no… |
|  | sed -n '640,760p' core/src/lamtools_core/plugin_system/context.py && echo "=== prompt_extensions | from .credential_controller import PluginCredentialController return P… |
| 5 | sed -n '1150,1300p' core/src/lamtools_core/app/base_agent.py | ) if state.metadata is None: state.metadata = {} state.metadata[RUNTIM… |
|  | sed -n '4520,4640p' core/src/lamtools_core/kernel/loop.py | metrics.pop("context_usage_prompt_tokens", None) # Keep raw request-on… |
| 6 | grep -rn "TAIL_SYSTEM_MESSAGE_MARKER\|role=\"system\"" --include=*.py core/src/lamtools_core | g | core/src/lamtools_core/app/base_agent.py:25: HISTORICAL_TAIL_SYSTEM_ME… |
|  | grep -rn "RUNTIME_CONTEXT_METADATA_KEY\|request_local_late_context\|RUNTIME_CONTEXT_DELTA_KEY" - | core/src/lamtools_core/app/auxiliary_chat.py:60: if (row.get("metadata… |
| 7 | echo "=== loop 2220-2280 ===" && sed -n '2200,2290p' core/src/lamtools_core/kernel/loop.py && ec | === loop 2220-2280 === previous_status, previous_owner.get("pid"), ) a… |
|  | echo "=== controller 610-680 ===" && sed -n '600,690p' core/src/lamtools_core/context_compaction | === controller 610-680 === if message.metadata.get("key") == "context_… |
| 8 | echo "=== http_client 40-110 ===" && sed -n '40,110p' core/src/lamtools_core/llm/http_client.py  | === http_client 40-110 === _logger = logging.getLogger(__name__) @data… |
|  | head -80 core/src/lamtools_core/app/plugin_compaction.py && echo "=== grep compaction hook ==="  | """user:“每一个地方 sunday 都有等价或者近似接口”+(插件手动压缩复用桌面命令的运行认领、控制记录和取消流程)。""" fr… |
| 9 | grep -rn "additional_context\|additionalContext" --include=*.py core/src/lamtools_core/kernel/lo | core/src/lamtools_core/kernel/loop.py:2225: # additional_context 注入用户消… |
|  | grep -rn "def _apply_session_start_hook" -A 60 core/src/lamtools_core/kernel/loop.py | head -80 | 4042: async def _apply_session_start_hook( 4043- self, 4044- state: Ru… |
| 10 | grep -rn "messages.append\|messages.insert\|messages\[0\] =" --include=*.py core/src/lamtools_co | core/src/lamtools_core/app/base_agent.py:1226: history_messages.append… |
|  | grep -rn "_cached_subagent_guide\|_build_project_context_parts\|_cached_subagent_roles\|_cached_ | core/src/lamtools_core/app/base_agent.py:607: def _cached_subagent_gui… |
| 11 | sed -n '1,140p' core/src/lamtools_core/prompt/__init__.py | """Prompt assembly protocol types and interfaces.""" from dataclasses … |
|  | sed -n '2560,2620p' core/src/lamtools_core/kernel/loop.py && echo "=== guidance ===" && grep -rn | if len(recent_fingerprints) > window: del recent_fingerprints[:-window… |
| 12 | ls core/src/lamtools_core/ && echo "=== tools dir ===" && ls core/src/lamtools_core/tools 2>/dev | __init__.py __pycache__ agent.py app artifact async_tasks.py attachmen… |
|  | sed -n '1,80p' core/src/lamtools_core/plugins/bundled/study/backend.py && echo "=== study manife | from __future__ import annotations import asyncio import hashlib impor… |
| 13 | find core/src/lamtools_core/plugins/bundled -maxdepth 2 -name "tools.jsonc" -o -maxdepth 2 -name | core/src/lamtools_core/plugins/bundled/imagegen/plugin.json core/src/l… |
|  | grep -rn "ToolSpec(\|name=\"" --include=*.py core/src/lamtools_core/tool/*.py | head -60 && echo | core/src/lamtools_core/tool/command_runner.py:755: return CommandShell… |
| 14 | grep -rn "ToolSpec(" --include=*.py core/src/lamtools_core | grep -v test | wc -l && echo "--- b | 19 --- by file --- 5 core/src/lamtools_core/plugins/bundled/workflow/b… |
|  | grep -rn "def .*tool.*spec\|_specs\|tools_specs\|def tool_specs" --include=*.py core/src/lamtool | 33: durable_tool_specs, 1079:# default_core_tool_specs() 输出（基础集 = 15），… |
| 15 | sed -n '1000,1140p' core/src/lamtools_core/tool/default_toolbox.py | { "action": { "type": "string", "enum": [ "status", "snapshot", "tap",… |
|  | grep -rn "CORE_TOOL\|BASE_TOOL\|_CORE_SPEC" --include=*.py core/src/lamtools_core/tool/default_t | === 129:def _workflow_context_from_metadata(metadata: Mapping[str, Any… |
| 16 | grep -n "DEFAULT_TOOL_ORDER\|DEFAULT_TOOL_CATEGORIES\|DEFAULT_TOOL_PERMISSIONS" core/src/lamtool | 209:DEFAULT_TOOL_PERMISSIONS: dict[str, PermissionTier] = { 251:DEFAUL… |
|  | grep -rn "DEFAULT_TOOL_ORDER" --include=*.py core/src | head && grep -rn "DEFAULT_TOOL_CATEGORIE | core/src/lamtools_core/tool/default_toolbox.py:251:DEFAULT_TOOL_ORDER:… |
| 17 | sed -n '200,340p' core/src/lamtools_core/tool/default_toolbox.py | parent_call_id: str = "", parent_run_id: str = "", parent_turn_id: str… |
| 18 | for f in core/src/lamtools_core/plugins/bundled/*/tools.jsonc; do echo "=== $f ==="; grep -c "\" | === core/src/lamtools_core/plugins/bundled/network-exploration/tools.j… |
|  | head -60 core/src/lamtools_core/plugins/bundled/workflow/tools.jsonc && echo "..." && grep -n "d | { "tools": [ { "name": "workflow_graph", "permission": "auto_allow", "… |
| 19 | grep -n "PLUGIN_INSTALL_TOOL\s*=\|PLUGIN_[A-Z_]*TOOL\s*=\|name=PLUGIN" -E core/src/lamtools_core | === names === |
|  | grep -n "PLUGIN_[A-Z_]*_TOOL = \|^PLUGIN" core/src/lamtools_core/plugin_system/manager_tools.py  | 21:PLUGIN_INSTALL_TOOL = "plugin_install" 22:PLUGIN_DEPS_TOOL = "plugi… |
| 20 | sed -n '100,215p' core/src/lamtools_core/plugins/bundled/workflow/backend/build_tools.py | "fallback_port": {"type": "string"}, "error_value": {"type": "string"}… |
|  | sed -n '20,40p' core/src/lamtools_core/tool/durable_tools.py && sed -n '60,90p' core/src/lamtool | # +(模型侧三种收口动作都收敛到 goal.update 的两个状态上)。 _GOAL_ACTION_STATUS: dict[str, … |
| 21 | find core/src/lamtools_core/plugins -name "*.jsonc" -o -name "plugin.json" | sort && echo "=== a | core/src/lamtools_core/plugins/bundled/imagegen/config/schema.jsonc co… |
| 22 | for f in $(find core/src/lamtools_core/plugins -name "tools.jsonc" | sort); do echo "--- $f"; gr | --- core/src/lamtools_core/plugins/bundled/imagegen/tools/tools.jsonc … |
|  | grep -rn "git_status" --include=*.jsonc --include=*.json core/src/lamtools_core/plugins core/ 2> | [command] cd /e/LamTools && grep -rn "git_status" --include=*.jsonc --… |
| 23 | cat core/src/lamtools_core/plugins/bundled/plan/tools/tools.jsonc; echo "=== plan manifest ==="; | { // The plan plugin ships skills only (draft-plan / refine-plan / exe… |
|  | grep -rn "git_status" core/src/lamtools_core/plugins/ 2>/dev/null | head -5; echo "---"; grep -r | --- 38:def make_git_status_handler( 44: async def git_status(call: Too… |
| 24 | grep -rn "bundled_core_tool_specs" --include=*.py core/src | head -10; echo "=== git plugin sear | core/src/lamtools_core/app/base_agent.py:2005: from lamtools_core.tool… |
|  | grep -rn "core_tool\|CORE_TOOL\|core:\|core_constant" --include=*.py core/src/lamtools_core/plug | [command] cd /e/LamTools && grep -rn "core_tool\|CORE_TOOL\|core:\|cor… |
| 25 | sed -n '80,180p' core/src/lamtools_core/plugin_system/runtime.py | input_schema = dict(base_input) if isinstance(base_input, dict) else {… |
| 26 | python -c " import sys sys.path.insert(0,'core/src') from lamtools_core.tool.default_toolbox imp | ORDER 29 default_core 24 ['read_file', 'list_dir', 'search_files', 'se… |
|  | grep -rn "def android_control_available" -A 15 core/src/lamtools_core/tool/android_use.py core/s | core/src/lamtools_core/tool/android_use.py:43:def android_control_avai… |
| 27 | python -c " import re p='core/src/lamtools_core/plugin_system/manager_tools.py' s=open(p,encodin | ['PLUGIN_INSTALL_TOOL', 'PLUGIN_DEPS_TOOL', 'PLUGIN_LIST_TOOL', 'PLUGI… |
|  | grep -n "ToolSpec(\|def workflow_build_tool_specs\|def manifest" core/src/lamtools_core/plugins/ | 90: ToolSpec( === workflow backend files === __init__.py __pycache__ a… |
| 28 | sed -n '60,120p' core/src/lamtools_core/plugins/bundled/workflow/backend/tools.py | def workflow_tool_specs(enrolled: list[WorkflowDef]) -> list[ToolSpec]… |
|  | grep -rn "def tool_specs" -A 12 core/src/lamtools_core/plugins/bundled/workflow/backend/__init__ | core/src/lamtools_core/plugins/bundled/workflow/backend/__init__.py:20… |
| 29 | head -40 core/src/lamtools_core/plugins/bundled/study/tools.jsonc && echo "=== websearch ===" && | { "tools": [ { "name": "get_knowledge_net", "description": "Read a sco… |
| 30 | for f in core/src/lamtools_core/plugins/bundled/*/plugin.json; do echo "=== $f"; cat "$f"; done  | === core/src/lamtools_core/plugins/bundled/imagegen/plugin.json { "nam… |
|  | ls core/src/lamtools_core/plugins/bundled/study/prompts/ && head -30 core/src/lamtools_core/plug | study-system.md # Study System Prompt In one sentence: You are the Stu… |
| 31 | sed -n '30,120p' core/src/lamtools_core/plugins/bundled/study/plugin.json && echo "=== workflow  | "study:" ] }, "ui": { "modes": [ { "id": "study", "title": "Study", "e… |
|  | find core/src/lamtools_core/plugins -name "agent*.jsonc" -o -name "agents*" | head; echo "=== re | core/src/lamtools_core/plugins/bundled/study/skills/teach-humanities/a… |
| 32 | python - <<'EOF' import json,re,glob,os for p in sorted(glob.glob('core/src/lamtools_core/plugin | core/src/lamtools_core/plugins/bundled\imagegen\plugin.json | agent: n… |
|  | grep -n "\"agent\"" -A 12 core/src/lamtools_core/plugins/bundled/study/plugin.json | head -30; e | 123: "agent": { 124- "mode": "study", 125- "prompt": "./prompts/study-… |
| 33 | grep -rn "\.prompts\b\|prompts\.section\|prompts\.variable\|on_assemble" --include=*.py core/src | [command] cd /e/LamTools && grep -rn "\.prompts\b\|prompts\.section\|p… |
|  | grep -rn "system_prompt_waterfall\|prompt_waterfall" --include=*.py core/src/lamtools_core | gre | core/src/lamtools_core/app/base_agent.py:575: prompt_waterfall: Any | … |
| 34 | grep -rn "context" core/src/lamtools_core/plugin_system/capabilities.py | head -30 | 100: context: list[PluginContextSpec] = field(default_factory=list) 34… |
|  | grep -rn "\"context\"\|'context'" core/src/lamtools_core/plugin_system/engine.py core/src/lamtoo | core/src/lamtools_core/plugin_system/capabilities.py:349: raw = manife… |
| 35 | sed -n '740,790p' core/src/lamtools_core/app/base_agent.py && echo "=== project_context ===" &&  | step_index: int, ) -> PromptContext: return PromptContext( session_id=… |
|  | grep -rn "instructions" --include=*.py core/src/lamtools_core/app/base_agent.py | head -20 && ec | 170: "Tools: use available tools as needed; tool results are evidence,… |
| 36 | sed -n '1255,1290p' core/src/lamtools_core/app/default_agent.py && echo "=== grep turn_instructi | if live_key in runtime_snapshot: state.metadata[live_key] = runtime_sn… |
|  | grep -n "def _runtime_context_text" -A 60 core/src/lamtools_core/app/base_agent.py | head -70 | 344:def _runtime_context_text(fields: Mapping[str, Any]) -> str: 345- … |
| 37 | sed -n '404,470p' core/src/lamtools_core/app/base_agent.py | if retry: lines.extend(["", retry]) return "\n".join(lines) def _runti… |
|  | grep -n "def _runtime_context_fields" -A 55 core/src/lamtools_core/app/base_agent.py | head -65 | 1076: def _runtime_context_fields( 1077- self, 1078- state: RuntimeSta… |
| 38 | grep -rn "trigger=\"manual\"\|\"manual\"\|compact_now" --include=*.py core/src/lamtools_core/ker | core/src/lamtools_core/context_compaction/controller.py:162: trigger=t… |
|  | grep -rn "def persist_compaction" -A 40 core/src/lamtools_core/kernel/loop.py | head -55 | [command] cd /e/LamTools && grep -rn "def persist_compaction" -A 40 co… |
| 39 | sed -n '4636,4720p' core/src/lamtools_core/kernel/loop.py | result = replace(result, replacement_messages=replacement, after_token… |
| 40 | sed -n '420,470p' core/src/lamtools_core/tool/sub_agent_runner.py && echo "=== AUX ===" && grep  | loop_policy=self._loop_policy_template, compact_trigger_tokens=self.co… |
|  | grep -rn "request_local_late_context\|late_context" --include=*.py core/src/lamtools_core/tool/s | core/src/lamtools_core/tool/sub_agent_runner.py:814: late_context: str… |
| 41 | grep -rn "merge_system_messages\|_messages_with_model_notes\|with_shallow_thinking_prompt" --inc | core/src/lamtools_core/cli.py:326: _messages_with_model_notes, core/sr… |
|  | sed -n '1740,1800p' core/src/lamtools_core/llm/profiles.py | max_tokens: int, temperature: float, stream: bool = False, top_p: floa… |
| 42 | sed -n '195,235p' core/src/lamtools_core/context_compaction/planner.py && echo "=== compaction_i | # user:“用户消息那个也许可以取消？”+(不再追加近期用户原话列表，只保护当前最后一条真实用户请求)。 latest_user = n… |
| 43 | grep -rn "def compaction_input_messages" -A 30 --include=*.py core/src/lamtools_core | head -40 | core/src/lamtools_core/kernel/loop.py:275:def compaction_input_message… |
| 44 | ls plugins 2>/dev/null | head -20; echo "---"; grep -rln "on_assemble\|prompts.section\|system_p | bili-scroll excalidraw lamtools-rag qq-bot --- plugins/qq-bot/qqbot/ag… |
| 45 | grep -n "on_assemble\|prompts.section\|prompt_waterfall" plugins/qq-bot/qqbot/agent_bridge.py |  | 115: self.prompt_waterfall: Any | None = None 125: waterfall = service… |
| 46 | for f in plugins/*/tools/tools.jsonc; do echo "--- $f"; grep -o "\"name\": *\"[A-Za-z0-9_.:-]*\" | --- plugins/bili-scroll/tools/tools.jsonc "bili_status" "bili_config" … |
| 47 | 输出正文 | — |

## Rb-1（v1/variant，34 轮）

| 轮 | 动作 | 得到 |
| --- | --- | --- |
| 1 | ls E:/LamTools/core/src/lamtools_core/app/ 2>/dev/null | head -50; echo "---"; ls E:/LamTools/co | __init__.py __pycache__ agent_app.py api_access.py approval_resolution… |
|  | search_content E:/LamTools/core/src/lamtools_core | 匹配34处；扫描775项：core/src/lamtools_core/app/base_agent.py:780: def _compose_system_prom… |
| 2 | sed -n '760,1060p' core/src/lamtools_core/app/base_agent.py | argument, so it must lead with the real id the model resolver accepts;… |
|  | search_content E:/LamTools/core/src/lamtools_core/plugin_system | 匹配2处；扫描126项：core/src/lamtools_core/plugin_system/context.py:690: waterfall = self.… |
| 3 | cat core/src/lamtools_core/prompt/movable.py | """Movable system-context blocks with an epoch-frozen leading prompt. … |
|  | ls core/src/lamtools_core/prompt/ core/src/lamtools_core/context_compaction/ core/src/lamtools_c | core/src/lamtools_core/context_compaction/: __init__.py __pycache__ co… |
| 4 | cat core/src/lamtools_core/plugin_system/prompt_waterfall.py | """System-prompt waterfall for plugins. The upstream DSH host exposes … |
|  | cat core/src/lamtools_core/plugin_system/prompt_extensions.py; echo "=====CONTEXT 640-760"; sed  | """user:“每一个地方 sunday 都有等价或者近似接口”+(提示词贡献绑定已有启动所有权，复用原提示词流水线)。""" from … |
| 5 | grep -rn "plan_movable_context\|format_movable_context_notice\|rebuild_movable_system_context\|M | core/src/lamtools_core/app/base_agent.py:37: MOVABLE_CONTEXT_METADATA_… |
|  | grep -rn "role=\"system\"\|role='system'\|ChatMessage(role=\"system\"" --include=*.py core/src/l | core/src/lamtools_core/app/base_agent.py:1158: role="system", core/src… |
| 6 | sed -n '1140,1300p' core/src/lamtools_core/app/base_agent.py | } def emit_runtime_context_snapshot(self, state: RuntimeState) -> Chat… |
|  | sed -n '4540,4600p' core/src/lamtools_core/kernel/loop.py; echo "===260-300"; sed -n '255,300p'  | "context_compaction_retained_steps": retained_steps, "context_compacte… |
| 7 | echo "=== compaction/state.py 80-150"; sed -n '80,150p' core/src/lamtools_core/context_compactio | === compaction/state.py 80-150 # the keyword; detect that shape withou… |
|  | echo "=== http_client 50-110"; sed -n '50,110p' core/src/lamtools_core/llm/http_client.py; echo  | === http_client 50-110 model_record_id: str model_id: str display_name… |
| 8 | grep -rn "TAIL_SYSTEM_MESSAGE_MARKER" --include=*.py core/src | grep -v "kernel/loop.py\|base_ag | core/src/lamtools_core/context_compaction/planner.py:17:from lamtools_… |
|  | grep -rn "prompt_waterfall\|SystemPromptWaterfall" --include=*.py core/src | grep -v "prompt_wat | core/src/lamtools_core/app/base_agent.py:575: prompt_waterfall: Any | … |
| 9 | grep -rn "\.prompts\b\|prompts\." --include=*.py --include=*.jsonc core/src/lamtools_core/plugin | === root plugins dirs imagegen network-exploration pipeline-checker pl… |
|  | cat core/src/lamtools_core/plugin_system/agent.py | head -120 | """Agent takeover declarations: prompt, tools, approval, context and s… |
| 10 | find . -name "tools.jsonc" -not -path "*/node_modules/*" -not -path "*/.worktrees/*" 2>/dev/null | ./.build/plugin-rebuild/live/plugins/bili-scroll/tools/tools.jsonc ./.… |
|  | ls core/src/lamtools_core/tool/ 2>/dev/null; echo "=== plugins in core/plugins"; find core/plugi | __init__.py __pycache__ android_use.py approval.py approval_continuati… |
| 11 | ls core/src/lamtools_core/plugins/bundled/; echo "=== all source tools.jsonc"; find core/src cor | imagegen network-exploration pipeline-checker plan study websearch wor… |
|  | wc -l core/src/lamtools_core/tool/default_toolbox.py && grep -n "def \|ToolDefinition\|name=\""  | 3094 core/src/lamtools_core/tool/default_toolbox.py 129:def _workflow_… |
| 12 | grep -n "^def \|^_TOOL\|^TOOL\|^CORE_\|^[A-Z_]* =\|category=" core/src/lamtools_core/tool/defaul | 98:_WORKFLOW_CONTEXT_METADATA_KEYS = ( 129:def _workflow_context_from_… |
|  | sed -n '451,560p' core/src/lamtools_core/tool/default_toolbox.py | def _schema(properties: dict[str, Any], required: list[str] | None = N… |
| 13 | sed -n '1,100p' core/src/lamtools_core/tool/default_toolbox.py; echo "=== context_history"; grep | from __future__ import annotations from lamtools_core.tool.question_sp… |
|  | sed -n '1081,1160p' core/src/lamtools_core/tool/default_toolbox.py | _BUNDLED_PLUGIN_TOOL_NAMES = frozenset({"git_status", "git_diff", "web… |
| 14 | grep -rn "DEFAULT_TOOL_ORDER\s*=\|DEFAULT_TOOL_CATEGORIES\s*=\|DEFAULT_TOOL_PERMISSIONS\s*=" --i | [command] cd E:/LamTools && grep -rn "DEFAULT_TOOL_ORDER\s*=\|DEFAULT_… |
|  | cat core/src/lamtools_core/plugins/bundled/workflow/tools.jsonc | head -60; echo "=== study"; ca | { "tools": [ { "name": "workflow_graph", "permission": "auto_allow", "… |
| 15 | grep -rn "DEFAULT_TOOL_ORDER" --include=*.py core/src | head -20 | core/src/lamtools_core/tool/default_toolbox.py:251:DEFAULT_TOOL_ORDER:… |
|  | python - <<'EOF' import json, re, glob, os paths = sorted(glob.glob('core/src/lamtools_core/plug | core/src/lamtools_core/plugins/bundled\imagegen\tools\tools.jsonc: 1 -… |
| 16 | sed -n '206,460p' core/src/lamtools_core/tool/default_toolbox.py | DEFAULT_COMMAND_TIMEOUT = 120 DEFAULT_TOOL_PERMISSIONS: dict[str, Perm… |
| 17 | grep -rn "ToolSpec(" --include=*.py core/src/lamtools_core | grep -v "plugin_system/tool_schema. | core/src/lamtools_core/app/auxiliary_chat.py:189: spec = ToolSpec(name… |
|  | grep -rn "MEMORY_TOOL_NAME\s*=\|LIBRARY_TOOL_NAME\s*=\|DESKTOP_OVERLAY_TOOL_NAME\s*=\|BROWSER_TO | core/src/lamtools_core/agent.py:15:SUB_AGENT_TOOL_NAME = "sub_agent" c… |
| 18 | sed -n '1,160p' core/src/lamtools_core/plugin_system/manager_tools.py | """模型可调插件管理工具（F2 共识：skill 引导插件安装的调用通道）。 照抄 durable_tools 骨架（operation … |
|  | sed -n '80,215p' core/src/lamtools_core/plugins/bundled/workflow/backend/build_tools.py | "max_iterations": {"type": "integer"}, "condition": {"type": "string"}… |
| 19 | grep -rn "request_local_late_context" --include=*.py core/src | head -20; echo "=== goal continu | core/src/lamtools_core/app/auxiliary_chat.py:60: if (row.get("metadata… |
|  | grep -rn "system_instruction\|prompt_submit\|additional_context" --include=*.py core/src/lamtool | core/src/lamtools_core/plugin_system/hook_engine.py:61: if result.addi… |
| 20 | for f in core/src/lamtools_core/plugins/bundled/*/plugin.jsonc core/src/lamtools_core/plugins/bu | --- core/src/lamtools_core/plugins/bundled/*/plugin.jsonc --- core/src… |
|  | sed -n '1100,1160p' core/src/lamtools_core/llm/profiles.py | payload, profile=profile, thinking_budget=thinking_budget, reasoning_l… |
| 21 | ls core/src/lamtools_core/plugins/bundled/study/ core/src/lamtools_core/plugins/bundled/workflow | core/src/lamtools_core/plugins/bundled/study/: __init__.py __pycache__… |
|  | sed -n '1,60p' core/src/lamtools_core/plugins/bundled/study/backend.py; echo "=== STUDY prompts  | from __future__ import annotations import asyncio import hashlib impor… |
| 22 | cat core/src/lamtools_core/plugins/bundled/study/plugin.json; echo "=== workflow"; cat core/src/ | { "id": "study", "name": "study", "version": "2.0.0", "description": "… |
|  | grep -rn "\"agent\"" core/src/lamtools_core/plugins/bundled/*/plugin.json; echo "=== resolve_age | core/src/lamtools_core/plugins/bundled/study/plugin.json:123: "agent":… |
| 23 | sed -n '1,80p' core/src/lamtools_core/plugin_system/compaction_access.py; echo "=== app/plugin_c | """user:“宿主能力补齐和接口完善与文档更新”+(手动压缩固定启动代与目录，等待真实宿主结果，不冒充 DSH 压缩引擎)。""" fr… |
|  | grep -n "system\|prompt" core/src/lamtools_core/tool/sub_agent_runner.py | sed -n '1,80p' | 37: approved_tool_continuation_prompt, 38: approved_tool_failure_conti… |
| 24 | grep -rn "merge_system_messages" --include=*.py core/src | grep -v "def merge_system_messages";  | core/src/lamtools_core/llm/__init__.py:301: "merge_system_messages", =… |
|  | grep -rn "agent_preset_prompt" --include=*.py core/src | head -20; echo "=== presets registry";  | core/src/lamtools_core/app/base_agent.py:558: agent_preset_prompt: str… |
| 25 | for f in core/src/lamtools_core/plugins/bundled/imagegen/tools/tools.jsonc core/src/lamtools_cor | --- core/src/lamtools_core/plugins/bundled/imagegen/tools/tools.jsonc … |
|  | grep -n "plugin_context_files" -r core/src/lamtools_core --include=*.py | head; echo "=== _runti | core/src/lamtools_core/app/base_agent.py:574: plugin_context_files: li… |
| 26 | grep -rln "\"git_status\"" --include=*.json --include=*.jsonc . 2>/dev/null | grep -v "node_modu | [command] cd E:/LamTools && grep -rln "\"git_status\"" --include=*.jso… |
|  | sed -n '2140,2175p' core/src/lamtools_core/app/base_agent.py | if isinstance(metadata, dict): metadata.setdefault("plugin", handle.pl… |
| 27 | grep -rl "git_status" core/src/lamtools_core/plugins 2>/dev/null | head; echo "--- bundled plugi | --- bundled plugins dir core/src/lamtools_core/plugins/__pycache__/ co… |
|  | grep -rn "plugin_manager_tool_specs" --include=*.py core/src | head | core/src/lamtools_core/plugin_system/manager_tools.py:37:def plugin_ma… |
| 28 | sed -n '1560,1660p' core/src/lamtools_core/tool/default_toolbox.py | continue if spec.name in plugin_seen: self._plugin_conflicts[spec.name… |
| 29 | sed -n '4600,4700p' core/src/lamtools_core/kernel/loop.py | # user:“无法生成满足模型窗口约束的合法请求时，停止本次调用并明确 # 报告原因，保留历史与任务状态，支持后续重试”+(拟合器已经把摘… |
| 30 | grep -rn "compacted\b" --include=*.py core/src/lamtools_core/app/base_agent.py | head -10; echo  | === _runtime_context_text 344:def _runtime_context_text(fields: Mappin… |
|  | grep -rn "context_compaction_summary\|Compaction summary\|compaction notice" --include=*.py core | core/src/lamtools_core/kernel/loop.py:258: if message.role == "system"… |
| 31 | grep -rn "_is_marked_tail_system_message\|_is_historical_tail_system_message" --include=*.py cor | core/src/lamtools_core/llm/profiles.py:1120:def _is_marked_tail_system… |
| 32 | python - <<'EOF' import re src = open('core/src/lamtools_core/tool/default_toolbox.py', encoding | DEFAULT_TOOL_ORDER 23 categories entries 23 Counter({'file_read': 4, '… |
| 33 | grep -n "self._specs = \[\|durable_specs = durable_tool_specs\|plugin_manager_specs = (" core/sr | 1580: durable_specs = durable_tool_specs( 1606: plugin_manager_specs =… |
| 34 | 输出正文 | — |

## Rb-2（v2/variant，28 轮）

| 轮 | 动作 | 得到 |
| --- | --- | --- |
| 1 | search_content E:/LamTools/core/src/lamtools_core | 匹配34处；扫描775项：core/src/lamtools_core/app/base_agent.py:780: def _compose_system_prom… |
|  | search_files E:/LamTools | 匹配3处；扫描100001项：.codex-tmp/wheel-install-green/lamtools_core/app/base_agent.py .codex-… |
| 2 | sed -n '760,1060p' core/src/lamtools_core/app/base_agent.py | argument, so it must lead with the real id the model resolver accepts;… |
|  | sed -n '2000,2180p' core/src/lamtools_core/app/base_agent.py | from lamtools_core.plugin_system.agent_presets import build_agent_pres… |
| 3 | cat core/src/lamtools_core/prompt/movable.py | """Movable system-context blocks with an epoch-frozen leading prompt. … |
|  | sed -n '4400,4700p' core/src/lamtools_core/kernel/loop.py | async def _persist_runtime_context_metrics( self, state: RuntimeState,… |
| 4 | sed -n '1140,1330p' core/src/lamtools_core/app/base_agent.py | } def emit_runtime_context_snapshot(self, state: RuntimeState) -> Chat… |
|  | grep -rn "format_movable_context_notice\|plan_movable_context\|MOVABLE_CONTEXT_NOTICE_KEY\|compa | ./lamtools_core/app/base_agent.py:38: MOVABLE_CONTEXT_NOTICE_KEY, ./la… |
| 5 | grep -rn "TAIL_SYSTEM_MESSAGE_MARKER\|RUNTIME_CONTEXT_DELTA_KEY\|RUNTIME_CONTEXT_METADATA_KEY" - | ./lamtools_core/app/base_agent.py:25: HISTORICAL_TAIL_SYSTEM_MESSAGE_M… |
|  | sed -n '620,760p' lamtools_core/plugin_system/context.py && echo ======= && sed -n '1,120p' lamt | from .settings_access import PluginSettingsAPI return PluginSettingsAP… |
| 6 | sed -n '2200,2300p' lamtools_core/kernel/loop.py && echo ==== && sed -n '320,360p' lamtools_core | previous_status, previous_owner.get("pid"), ) await self.state_store.s… |
|  | sed -n '1,160p' lamtools_core/plugin_system/prompt_extensions.py && echo ==== && grep -rn "on_as | """user:“每一个地方 sunday 都有等价或者近似接口”+(提示词贡献绑定已有启动所有权，复用原提示词流水线)。""" from … |
| 7 | grep -rn "prompts\." --include=*.py lamtools_core | grep -v "plugin_system/prompt" | head -30 && | lamtools_core/plugin_system/dsh_compat/migration.py:340: item.update(s… |
|  | sed -n '1,80p' lamtools_core/plugins/bundled/study/backend.py && echo ==== && grep -rn "_STUDY_T | from __future__ import annotations import asyncio import hashlib impor… |
| 8 | sed -n '600,690p' lamtools_core/context_compaction/controller.py && echo ==== && sed -n '80,140p | if message.metadata.get("key") == "context_compaction_summary" else me… |
|  | grep -rn "def default_core_tool_specs\|def bundled_core_tool_specs\|def default_toolbox\|tool_sp | 33: durable_tool_specs, 1079:# default_core_tool_specs() 输出（基础集 = 15），… |
| 9 | sed -n '1040,1200p' lamtools_core/tool/default_toolbox.py && echo ==DIR== && ls lamtools_core/to | "description": "snapshot 最多返回多少个元素，默认 80。", }, "max_width": { "type": … |
|  | ls lamtools_core/tool/specs 2>/dev/null | head -40; grep -rn "def tool_specs\|^def \|_SPECS = \| | lamtools_core/tool/android_use.py:43:def android_control_available() -… |
| 10 | grep -n "DEFAULT_TOOL_ORDER\|DEFAULT_TOOL_CATEGORIES\|DEFAULT_TOOL_PERMISSIONS" -A 40 lamtools_c | 209:DEFAULT_TOOL_PERMISSIONS: dict[str, PermissionTier] = { 210- "read… |
|  | grep -n "plugin_manager_tool_specs" -A 40 lamtools_core/plugin_system/manager_tools.py | sed -n  | 37:def plugin_manager_tool_specs() -> list[ToolSpec]: 38- return [ 39-… |
| 11 | python -c " import json,re,glob,io def strip(t): t=re.sub(r'//[^\n]*','',t) t=re.sub(r'/\*.*?\*/ | core/src/lamtools_core/plugins/bundled\imagegen\tools\tools.jsonc 1 ['… |
|  | grep -n "PLUGIN_INSTALL_TOOL\|^\s*name=\|^def \|_TOOL\b" lamtools_core/plugin_system/manager_too | 21:PLUGIN_INSTALL_TOOL = "plugin_install" 22:PLUGIN_DEPS_TOOL = "plugi… |
| 12 | cat core/src/lamtools_core/plugins/bundled/plan/tools/tools.jsonc | { // The plan plugin ships skills only (draft-plan / refine-plan / exe… |
|  | python -c " from lamtools_core.tool.default_toolbox import default_core_tool_specs, bundled_core | default 24 ['read_file', 'list_dir', 'search_files', 'search_content',… |
| 13 | grep -rn "prompt_waterfall" --include=*.py lamtools_core | head -30 && echo ==AGENT== && grep -r | lamtools_core/app/base_agent.py:575: prompt_waterfall: Any | None = No… |
|  | grep -rn "additional_context\|systemMessage\|role=\"system\"" --include=*.py lamtools_core/plugi | lamtools_core/plugin_system/hook_engine.py:61: if result.additional_co… |
| 14 | grep -rn "_apply_session_start_hook" -A 40 lamtools_core/kernel/loop.py | head -60 && echo ==FRO | 2216: await self._apply_session_start_hook(state, turn_input) 2217- 22… |
|  | sed -n '1,80p' lamtools_core/runtime/context_delta.py && echo ==GUIDE== && grep -rn "def build_m | """Shared keys and predicate for append-only runtime context updates. … |
| 15 | sed -n '4059,4095p' lamtools_core/kernel/loop.py && echo ==DELTA== && grep -rn "def _runtime_con | if decision.status_message: await self._emit_hook_status(state, "", de… |
|  | sed -n '1100,1150p' lamtools_core/llm/profiles.py && echo ==CACHE== && sed -n '120,170p' lamtool | payload, profile=profile, thinking_budget=thinking_budget, reasoning_l… |
| 16 | grep -rn "STUDY_SYSTEM_PROMPT" --include=*.py lamtools_core | head && echo ==MANIFEST== && grep  | lamtools_core/plugins/bundled/study/backend.py:43:STUDY_SYSTEM_PROMPT … |
|  | grep -rn "AUXILIARY_INSTRUCTIONS" -A 12 lamtools_core/app/auxiliary_chat.py | head -25 && echo = | 15:AUXILIARY_INSTRUCTIONS = ( 16- "You are the read-only assistant to … |
| 17 | ls study workflow plan && echo == && sed -n '370,400p' study/backend.py | plan: __pycache__ eval_manifest.py plugin.json skills tools study: __i… |
|  | for f in $(find . -maxdepth 3 -name "*.jsonc" | head -40); do echo "== $f"; grep -n "agents\|pro | == ./imagegen/config/schema.jsonc == ./imagegen/tools/tools.jsonc == .… |
| 18 | for f in $(find . -maxdepth 2 -name "plugin.json"); do echo "== $f"; grep -n "agents\|prompt\|in | == ./imagegen/plugin.json == ./network-exploration/plugin.json == ./pi… |
|  | ls study/prompts workflow/backend && echo == && grep -rn "agent_preset" --include=*.jsonc . | he | study/prompts: study-system.md workflow/backend: __init__.py __pycache… |
| 19 | sed -n '110,140p' study/plugin.json && echo ==PRESET== && cd /e/LamTools && grep -rn "agent_pres | ], "default": "" }, { "flags": [ "--token" ], "default": "" } ] } ] },… |
|  | grep -rn "instructions" --include=*.py core/src/lamtools_core/app/default_agent.py | head -20 && | 100: instructions: str = DEFAULT_CORE_INSTRUCTIONS 300: instructions=s… |
| 20 | grep -rn "messages\[0\]" --include=*.py lamtools_core | head -20 && echo ==HOOKCTX== && sed -n ' | lamtools_core/kernel/loop.py:4572: if isinstance(epoch, dict) and isin… |
| 21 | grep -rln "git_status" --include=*.jsonc core/ | head -10 && echo == && find core -name "tools.j | core/.lam/core/config/access_tools.jsonc core/.lam/core/config/loadtoo… |
| 22 | find core -type d -name "bundled" -not -path "*/target/*" -not -path "*/node_modules/*" | head - | core/desktop/dist/assets/src/lamtools_core/plugins/bundled core/deskto… |
| 23 | ls core/desktop/src-tauri/lamcore-backend/_internal/resources/plugins/bundled/ && echo ==GIT== & | git imagegen websearch workflow ==GIT== ['git_status', 'git_diff'] plu… |
| 24 | grep -rn "git_status" --include=*.py --include=*.json --include=*.jsonc core/src core/config age | core/src/lamtools_core/app/auxiliary_chat.py:14:READ_ONLY_TOOLS = froz… |
| 25 | grep -rn "bundled_core_tool_specs" --include=*.py core/src | head -10 && echo == && grep -rn "co | core/src/lamtools_core/app/base_agent.py:2005: from lamtools_core.tool… |
| 26 | sed -n '95,140p' core/src/lamtools_core/plugin_system/runtime.py && echo ==RESOLVE== && sed -n ' | metadata["overrides_core_tool"] = True return ToolSpec( name=tool.name… |
| 27 | grep -n "goal_continuation_message(reminder)\|turn_origin in {\"member_wake\", \"turn_resume\"}\ | 2226: hook_user_content = ( 2239: if turn_origin in {"member_wake", "t… |
| 28 | 输出正文 | — |

## Rc-1（v3a/variant，45 轮）

| 轮 | 动作 | 得到 |
| --- | --- | --- |
| 1 | ls E:/LamTools/core/src/lamtools_core/app/ | head -60 | __init__.py __pycache__ agent_app.py api_access.py approval_resolution… |
|  | grep -rln "system_prompt\|systemPrompt" --include=*.py --include=*.ts --include=*.rs --include=* | core/src/lamtools_core/app/base_agent.py core/src/lamtools_core/kernel… |
| 2 | ls core/src/lamtools_core/prompt/ && echo "---" && ls core/src/lamtools_core/plugin_system/ && e | __init__.py __pycache__ movable.py --- __init__.py __pycache__ account… |
|  | grep -rn "system_prompt" --include=*.py core/src | grep -v "base_agent.py" | head -100 | core/src/lamtools_core/kernel/loop.py:4572: if isinstance(epoch, dict)… |
| 3 | read_file E:/LamTools/core/src/lamtools_core/prompt/movable.py | """Movable system-context blocks with an epoch-frozen leading prompt. … |
|  | read_file E:/LamTools/core/src/lamtools_core/plugin_system/prompt_waterfall.py | """System-prompt waterfall for plugins. The upstream DSH host exposes … |
| 4 | grep -n "def .*prompt\|system_prompt\|movable\|waterfall\|PromptAssembly\|PromptContext" core/sr | 35:from lamtools_core.prompt import PromptContext, PromptPart 36:from … |
|  | grep -rn "movable\|MovableBlock\|movable_system_context" --include=*.py core/src | grep -v "prom | core/src/lamtools_core/app/base_agent.py:36:from lamtools_core.prompt.… |
| 5 | read_file E:/LamTools/core/src/lamtools_core/app/base_agent.py | " not in content and artifact_metadata.get("stdout"): lines.append(f"s… |
| 6 | sed -n '740,1010p' core/src/lamtools_core/app/base_agent.py | step_index: int, ) -> PromptContext: return PromptContext( session_id=… |
| 7 | sed -n '1167,1360p' core/src/lamtools_core/app/base_agent.py | async def build_model_request(self, state: RuntimeState, context: Prom… |
|  | sed -n '440,520p' core/src/lamtools_core/kernel/loop.py && echo "=====990-1040====" && sed -n '9 | }) repaired.append(ChatMessage( role="user", content=content, metadata… |
| 8 | grep -rn "role=\"system\"" --include=*.py core/src | grep -v "test" | head -60 | core/src/lamtools_core/app/base_agent.py:1158: role="system", core/src… |
|  | cat core/src/lamtools_core/plugin_system/prompt_extensions.py | head -200 | """user:“每一个地方 sunday 都有等价或者近似接口”+(提示词贡献绑定已有启动所有权，复用原提示词流水线)。""" from … |
| 9 | echo "=== loop 2200-2290 ===" && sed -n '2200,2295p' core/src/lamtools_core/kernel/loop.py | === loop 2200-2290 === previous_status, previous_owner.get("pid"), ) a… |
|  | echo "=== http_client 40-110 ===" && sed -n '40,110p' core/src/lamtools_core/llm/http_client.py  | === http_client 40-110 === _logger = logging.getLogger(__name__) @data… |
| 10 | echo "=== compaction controller 600-700 ===" && sed -n '600,700p' core/src/lamtools_core/context | === compaction controller 600-700 === if message.metadata.get("key") =… |
|  | grep -rn "_messages_with_model_notes\|with_shallow_thinking_prompt" --include=*.py core/src | he | core/src/lamtools_core/cli.py:326: _messages_with_model_notes, core/sr… |
| 11 | grep -rn "history_compacted\|compaction_notice\|Context was compacted\|was compacted\|compacted\ | 998: await self._emit_history_compacted(state, trimmed, len(history)) … |
|  | cat core/src/lamtools_core/runtime/tool_freeze.py | head -140 | """Freeze the model-visible tool array for one compaction cycle. user:… |
| 12 | grep -rn "request_local_late_context" --include=*.py core/src | head -20 && echo "=== mode_promp | core/src/lamtools_core/app/auxiliary_chat.py:60: if (row.get("metadata… |
|  | grep -rn "additional_context\|systemMessage\|system_prompt" --include=*.py core/src/lamtools_cor | core/src/lamtools_core/plugin_system/hook_engine.py:61: if result.addi… |
| 13 | grep -rn "mode_prompt_line" --include=*.py core/src | head -20 && echo "=== context_delta ===" & | core/src/lamtools_core/app/base_agent.py:78:from lamtools_core.tool.lo… |
|  | grep -rn "emit_runtime_context_snapshot" -A 40 core/src/lamtools_core/app/base_agent.py | head - | 1142: def emit_runtime_context_snapshot(self, state: RuntimeState) -> … |
| 14 | grep -rn "plugin_context_files" --include=*.py core/src | head -20 && echo "=== resolve_agent_pl | core/src/lamtools_core/app/base_agent.py:574: plugin_context_files: li… |
|  | sed -n '1,60p' core/src/lamtools_core/plugins/bundled/study/backend.py && echo "=== study manife | from __future__ import annotations import asyncio import hashlib impor… |
| 15 | sed -n '2090,2250p' core/src/lamtools_core/app/base_agent.py | ) if core_plugins_root() not in roots: roots.append(core_plugins_root(… |
|  | sed -n '1,80p' core/src/lamtools_core/plugin_system/agent_presets.py && echo "=== agent.py read_ | """Host-owned agent presets. An agent preset is a named bundle applied… |
| 16 | ls core/src/lamtools_core/tool/ && echo "=== default_toolbox head ===" && sed -n '1,120p' core/s | __init__.py __pycache__ android_use.py approval.py approval_continuati… |
| 17 | grep -rn "ToolSpec(" --include=*.py core/src | awk -F: '{print $1}' | sort | uniq -c | sort -rn  | 5 core/src/lamtools_core/plugins/bundled/workflow/backend/build_tools.… |
|  | find core/src/lamtools_core/plugins -name "tools.jsonc" | sort && echo "=== 用户/项目插件目录 ===" && ls | core/src/lamtools_core/plugins/bundled/imagegen/tools/tools.jsonc core… |
| 18 | grep -n "def build_core_toolbox" -A 80 core/src/lamtools_core/tool/default_toolbox.py | head -12 | 3059:def build_core_toolbox(**kwargs: Any) -> CoreToolbox: 3060- retur… |
|  | ls core/src/lamtools_core/plugins/bundled/ && echo "=== plugins dir at repo root ===" && ls plug | imagegen network-exploration pipeline-checker plan study websearch wor… |
| 19 | grep -n "def default_core_tool_specs" core/src/lamtools_core/tool/default_toolbox.py && sed -n " | 1104:def default_core_tool_specs() -> list[ToolSpec]: def default_core… |
|  | for d in plugins/*/; do echo "== $d"; ls "$d"; done 2>/dev/null | head -60 | == plugins/bili-scroll/ LICENSE NOTICE.md README.md __pycache__ backen… |
| 20 | grep -n "DEFAULT_TOOL_ORDER" -A 80 core/src/lamtools_core/tool/default_toolbox.py | head -110 && | 251:DEFAULT_TOOL_ORDER: tuple[str, ...] = ( 252- "read_file", 253- "li… |
|  | head -60 core/src/lamtools_core/plugins/bundled/plan/tools/tools.jsonc && echo "=== count by fil | { // The plan plugin ships skills only (draft-plan / refine-plan / exe… |
| 21 | for f in $(find core/src/lamtools_core/plugins -name tools.jsonc); do echo "== $f"; grep -n '^\s | == core/src/lamtools_core/plugins/bundled/imagegen/tools/tools.jsonc 4… |
|  | ls plugins/bili-scroll/tools plugins/lamtools-rag/tools 2>/dev/null && echo "=== qq-bot/excalidr | plugins/bili-scroll/tools: tools.jsonc plugins/lamtools-rag/tools: too… |
| 22 | head -40 core/src/lamtools_core/plugins/bundled/workflow/tools.jsonc && echo "=== jsonc loader = | { "tools": [ { "name": "workflow_graph", "permission": "auto_allow", "… |
| 23 | grep -n "ToolSpec(" -A 3 core/src/lamtools_core/plugin_system/manager_tools.py | grep -n "\"name | 2:40- name=PLUGIN_INSTALL_TOOL, 7:84- name=PLUGIN_DEPS_TOOL, 12:100- n… |
|  | grep -n "ToolSpec(" -A 4 core/src/lamtools_core/plugins/bundled/workflow/backend/build_tools.py  | 111- name="workflow_graph", 123- name="workflow_add_node", 168- name="… |
| 24 | python -c " import importlib.util, json, glob spec = importlib.util.spec_from_file_location('j', | core/src/lamtools_core/plugins\bundled\imagegen\tools\tools.jsonc: 1 -… |
|  | grep -n "^PLUGIN_.*_TOOL = \|^PLUGIN_.*TOOL: str" core/src/lamtools_core/plugin_system/manager_t | 21:PLUGIN_INSTALL_TOOL = "plugin_install" 22:PLUGIN_DEPS_TOOL = "plugi… |
| 25 | python -c " import re src=open('core/src/lamtools_core/tool/default_toolbox.py',encoding='utf-8' | defs start None 21 ['read_file', 'list_dir', 'search_files', 'search_c… |
|  | grep -rn "durable_tool_specs\|goal_tool\|arrange" --include=*.py core/src/lamtools_core/tool/def | 33: durable_tool_specs, 1437: enable_goal_tool: bool = False, 1438: en… |
| 26 | grep -n "DEFAULT_TOOL_DEFINITIONS" core/src/lamtools_core/tool/default_toolbox.py | head -5 && s | 460:DEFAULT_TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = ( 1085: ite… |
|  | grep -rn "bundled/git\|\"git\"" --include=*.py core/src/lamtools_core/plugin_system/paths.py cor | === bundled plugin json === -- core/src/lamtools_core/plugins/bundled/… |
| 27 | python -c " import re src=open('core/src/lamtools_core/tool/default_toolbox.py',encoding='utf-8' | entries: 0 [] |
|  | sed -n '1595,1620p' core/src/lamtools_core/tool/default_toolbox.py && echo "=== manager specs == | and "operation_level" not in (spec.metadata or {}) and spec.name not i… |
| 28 | python - <<'PY' import re src=open('core/src/lamtools_core/tool/default_toolbox.py',encoding='ut | declared entries: 0 |
| 29 | python - <<'PY' import re src=open('core/src/lamtools_core/tool/default_toolbox.py',encoding='ut | declared entries: 25 ['"name": "read_file",', '"name": "list_dir",', '… |
| 30 | sed -n '270,300p' core/src/lamtools_core/kernel/loop.py && echo "=== 4650-4720 ===" && sed -n '4 | continue result.append(message) return result def compaction_input_mes… |
|  | grep -rn "enable_goal_tool\|enable_arrange_tool\|enable_plugin_manager" --include=*.py core/src/ | 821: enable_goal_tool=goal_manager is not None, 822: enable_arrange_to… |
| 31 | grep -n "candidate_state" core/src/lamtools_core/kernel/loop.py && echo "=== MOVABLE refs in loo | 4567: candidate_state = copy.deepcopy(state) 4570: rebuild_movable(can… |
| 32 | cat core/src/lamtools_core/plugins/bundled/study/plugin.json && echo "=== usage ===" && grep -rn | { "id": "study", "name": "study", "version": "2.0.0", "description": "… |
|  | grep -rn "system_prompt\|systemPrompt" core/src/lamtools_core/plugin_system/dsh_compat/migration | 336: if kind == "services" and name == "systemPrompt": 571: for match … |
| 33 | grep -rn "prompts\.section\|prompts\.variable\|prompts\.on_assemble\|system_prompt_waterfall" -- | plugins/qq-bot/qqbot/agent_bridge.py:125: waterfall = service("system_… |
|  | grep -n "_apply_session_start_hook" -A 40 core/src/lamtools_core/kernel/loop.py | head -60 | 2216: await self._apply_session_start_hook(state, turn_input) 2217- 22… |
| 34 | sed -n '4059,4130p' core/src/lamtools_core/kernel/loop.py && echo "=== qq-bot bridge 100-150 === | if decision.status_message: await self._emit_hook_status(state, "", de… |
| 35 | grep -rn "ShallowThinkingClient(\|set_enabled" --include=*.py core/src/lamtools_core | grep -v s | core/src/lamtools_core/app/command_execution.py:338: provider = Shallo… |
|  | grep -rn "\"context\"\|context:" core/src/lamtools_core/plugins/bundled/*/plugin.json | head -10 | core/src/lamtools_core/plugins/bundled/study/plugin.json:74: "context"… |
| 36 | sed -n '3295,3345p' core/src/lamtools_core/kernel/loop.py && echo "=== default_agent 3505-3535 = | if not isinstance(patch, dict) or not patch: return self._applied_sett… |
| 37 | grep -n "def apply_runtime_settings" -A 45 core/src/lamtools_core/app/base_agent.py | head -70 | 1003: def apply_runtime_settings(self, state: RuntimeState, patch: obj… |
|  | grep -rn "system\|prompt" core/src/lamtools_core/app/memory_resume_supervisor.py | head -20 && e | 88:def memory_resume_continuation_prompt( 340: wake_messages_prompt, 3… |
| 38 | grep -rn "goal_manager = \|arrange_manager = " core/src/lamtools_core/app/default_agent.py | hea | [command] cd E:/LamTools && grep -rn "goal_manager = \|arrange_manager… |
|  | grep -rn "def operation_tool_specs\|operation_levels\|native_operation" --include=*.py core/src/ | === plugin runtime tool specs count check === |
| 39 | grep -rn "goal_manager" core/src/lamtools_core/app/default_agent.py | head -10 && sed -n '815,82 | 273: goal_manager: GoalManager | None = None, 648: if goal_manager is … |
| 40 | grep -rn "git_status\|git_diff" --include=*.json --include=*.jsonc core/src/lamtools_core/plugin | --- 38:def make_git_status_handler( 44: async def git_status(call: Too… |
|  | grep -rn "def assemble" -A 60 core/src/lamtools_core/plugin_system/runtime.py | sed -n '1,80p' | 126: def assemble(self, manifests: list[Any] | None = None) -> Runtime… |
| 41 | python - <<'PY' import json, glob for f in sorted(glob.glob('core/src/lamtools_core/plugins/bund | core/src/lamtools_core/plugins/bundled\imagegen\plugin.json: tools=fil… |
| 42 | python - <<'PY' import re src=open('core/src/lamtools_core/tool/default_toolbox.py',encoding='ut | 23 ['read_file', 'list_dir', 'search_files', 'search_content', 'load_s… |
| 43 | ls core/src/lamtools_core/plugins/bundled/study/prompts/ && head -12 core/src/lamtools_core/plug | study-system.md # Study System Prompt In one sentence: You are the Stu… |
|  | grep -n "_cached_subagent_guide\|_cached_subagent_roles\|_cached_subagent_strategy" -A 12 core/s | 607: def _cached_subagent_guide(self) -> str: 608- if self._subagent_g… |
| 44 | sed -n '320,350p' core/src/lamtools_core/plugin_system/dsh_compat/migration.py && sed -n '560,58 | elif name == "list": item.update(suggestedContract="skill.list", diffe… |
|  | grep -rn "system_prompt\|systemPrompt" --include=*.ts --include=*.vue core/ui/src/components/Dir | 109:const systemPrompt = ref('') 367: system: systemPrompt.value, 487:… |
| 45 | 输出正文 | — |

## Rc-2（v3b/variant，33 轮）

| 轮 | 动作 | 得到 |
| --- | --- | --- |
| 1 | ls && echo "---" && ls core/src/lamtools_core/app/ 2>/dev/null | head -50 | 0.1.0 0.1.1 0.3.0 0.3.1 0.3.2 AGENTS.md CITATION.cff LICENSE MAINTENAN… |
|  | search_content core/src | 匹配34处；扫描779项：core/src/lamtools_core/app/base_agent.py:780: def _compose_system_prom… |
| 2 | sed -n '760,1060p' core/src/lamtools_core/app/base_agent.py | argument, so it must lead with the real id the model resolver accepts;… |
|  | sed -n '2030,2160p' core/src/lamtools_core/app/base_agent.py && echo "=== context.py waterfall = | agent_presets = plugin_context.services.get("agent_presets") fresh_pre… |
| 3 | cat core/src/lamtools_core/prompt/movable.py | """Movable system-context blocks with an epoch-frozen leading prompt. … |
|  | grep -rn "movable" --include=*.py core/src | grep -v "prompt/movable.py" | head -60 | core/src/lamtools_core/app/base_agent.py:36:from lamtools_core.prompt.… |
| 4 | sed -n '1150,1300p' core/src/lamtools_core/app/base_agent.py | ) if state.metadata is None: state.metadata = {} state.metadata[RUNTIM… |
|  | sed -n '4540,4650p' core/src/lamtools_core/kernel/loop.py && echo "=== tool_freeze ===" && cat c | "context_compaction_retained_steps": retained_steps, "context_compacte… |
| 5 | cat core/src/lamtools_core/plugin_system/prompt_waterfall.py | """System-prompt waterfall for plugins. The upstream DSH host exposes … |
|  | grep -rn "prompt_waterfall\|PromptAssembly\|prompts.assemble\|on_assemble" --include=*.py --incl | core/src/lamtools_core/app/base_agent.py:575: prompt_waterfall: Any | … |
| 6 | sed -n '1,140p' core/src/lamtools_core/plugin_system/prompt_extensions.py | """user:“每一个地方 sunday 都有等价或者近似接口”+(提示词贡献绑定已有启动所有权，复用原提示词流水线)。""" from … |
|  | grep -rn "TAIL_SYSTEM_MESSAGE_MARKER\|RUNTIME_CONTEXT_DELTA_KEY\|request_local_late_context" --i | core/src/lamtools_core/app/auxiliary_chat.py:60: if (row.get("metadata… |
| 7 | sed -n '2200,2290p' core/src/lamtools_core/kernel/loop.py && echo "=== 270-360 ===" && sed -n '2 | previous_status, previous_owner.get("pid"), ) await self.state_store.s… |
|  | cat core/src/lamtools_core/app/plugin_compaction.py | head -80 && echo "=== grep compaction noti | """user:“每一个地方 sunday 都有等价或者近似接口”+(插件手动压缩复用桌面命令的运行认领、控制记录和取消流程)。""" fr… |
| 8 | grep -rn "compaction" --include=*.py core/src/lamtools_core/kernel/loop.py | grep -in "notice\|a | 6:258: if message.role == "system" and metadata.get("key") == "context… |
|  | grep -rn "role=\"system\"\|role='system'" --include=*.py core/src/lamtools_core/app core/src/lam | core/src/lamtools_core/app/base_agent.py:1158: role="system", core/src… |
| 9 | sed -n '240,275p' core/src/lamtools_core/kernel/loop.py && echo "=== 2580-2660 ===" && sed -n '2 | def _retained_history_messages( history: list[ChatMessage], replacemen… |
|  | grep -rn "context_compaction_summary" --include=*.py core/src | head -30 | core/src/lamtools_core/context_compaction/controller.py:600: if messag… |
| 10 | sed -n '580,680p' core/src/lamtools_core/context_compaction/controller.py | "Context compaction failed to fit within limit: latest user " "message… |
|  | sed -n '80,140p' core/src/lamtools_core/context_compaction/state.py | # the keyword; detect that shape without a second read. raw_history = … |
| 11 | ls core/src/lamtools_core/tool/ && echo "=== bundled plugins ===" && ls core/src/lamtools_core/p | __init__.py __pycache__ android_use.py approval.py approval_continuati… |
|  | find . -name "tools.jsonc" -not -path "*/node_modules/*" | head -40 && echo "=== count ===" && f | ./.build/plugin-rebuild/live/plugins/bili-scroll/tools/tools.jsonc ./.… |
| 12 | find core/src plugins -name "tools.jsonc" -o -name "tools.json" | grep -v node_modules | sort | core/src/lamtools_core/plugins/bundled/imagegen/tools/tools.jsonc core… |
|  | grep -rn "ToolSpec(\|def tool_specs\|\"name\": \"" core/src/lamtools_core/tool/default_toolbox.p | 463: "name": "read_file", 480: "name": "list_dir", 485: "name": "searc… |
| 13 | sed -n '440,470p' core/src/lamtools_core/tool/default_toolbox.py && echo "..." && sed -n '820,86 | "status": {"type": "string", "enum": ["ok", "failed", "skipped", "bloc… |
|  | grep -rln "workflow_" --include=*.py core/src | head -20 && echo "=== control ===" && grep -rn " | core/src/lamtools_core/app/base_agent.py core/src/lamtools_core/plugin… |
| 14 | sed -n '280,340p' core/src/lamtools_core/tool/default_toolbox.py && echo "=== names indented 8 = | "question", ) DEFAULT_TOOL_CATEGORIES: dict[str, str] = { "android_use… |
|  | for f in core/src/lamtools_core/plugins/bundled/*/tools.jsonc core/src/lamtools_core/plugins/bun | --- core/src/lamtools_core/plugins/bundled/network-exploration/tools.j… |
| 15 | python - <<'EOF' import json,re,glob,os files = glob.glob('core/src/lamtools_core/plugins/bundle | core/src/lamtools_core/plugins/bundled\imagegen\tools\tools.jsonc 1 ['… |
|  | cat core/src/lamtools_core/tool/durable_tools.py | head -120 | """Model-facing Goal and Arrange tools backed by the shared operation … |
| 16 | grep -rn "ToolSpec(" --include=*.py core/src/lamtools_core/tool/ | head -40 && echo "=== names i | core/src/lamtools_core/tool/default_toolbox.py:1087: return ToolSpec( … |
|  | grep -rn "plugin_install\|plugin.install\|PLUGIN_TOOL\|plugin_manage" --include=*.py core/src |  | core/src/lamtools_core/app/base_agent.py:2084: # 空/None 一律回退默认根集合（含用户级… |
| 17 | sed -n '1,80p' core/src/lamtools_core/plugin_system/manager_tools.py && echo "=== defs ===" && g | """模型可调插件管理工具（F2 共识：skill 引导插件安装的调用通道）。 照抄 durable_tools 骨架（operation … |
|  | grep -rn "SUB_AGENT_TOOL_NAME\s*=\|BROWSER_TOOL_NAME\s*=\|DESKTOP_OVERLAY_TOOL_NAME\s*=\|LIBRARY | core/src/lamtools_core/agent.py:15:SUB_AGENT_TOOL_NAME = "sub_agent" c… |
| 18 | grep -n "DEFAULT_TOOL_DEFINITIONS\|DEFAULT_TOOL_CATEGORIES\|durable_tool_specs\|plugin_manager_t | 33: durable_tool_specs, 284:DEFAULT_TOOL_CATEGORIES: dict[str, str] = … |
|  | sed -n '1060,1120p' core/src/lamtools_core/tool/default_toolbox.py && echo "=== 2860-3120 ===" & | # user:“让 Agent Loop 能直接调用：打开/切换标签、快照、点击、输入、等待、截图”+ # (工具名用 browser，动作… |
| 19 | sed -n '240,284p' core/src/lamtools_core/tool/default_toolbox.py && echo "=== 1520,1660 ===" &&  | # 由宿主拒绝未经审批的声明，与 computer_use 一样不逐条弹审批)。 BROWSER_TOOL_NAME: AUTO_ALLOW… |
|  | grep -n "DEFAULT_TOOL_ORDER" -A 40 core/src/lamtools_core/tool/default_toolbox.py | sed -n '1,60 | 251:DEFAULT_TOOL_ORDER: tuple[str, ...] = ( 252- "read_file", 253- "li… |
| 20 | find core/src -name "plugin.jsonc" | grep -v node_modules | sort && echo "=== git plugin? ===" & | === git plugin? === |
|  | head -40 core/src/lamtools_core/plugins/bundled/workflow/tools.jsonc && echo "=== plan tools === | { "tools": [ { "name": "workflow_graph", "permission": "auto_allow", "… |
| 21 | ls core/src/lamtools_core/plugins/bundled/study/ core/src/lamtools_core/plugins/bundled/websearc | core/src/lamtools_core/plugins/bundled/imagegen/: config plugin.json t… |
|  | cat core/src/lamtools_core/plugins/bundled/websearch/tools/tools.jsonc && echo "=== git refs === | { "tools": [ { "name": "web_search", "permission": "auto_allow", "hand… |
| 22 | find core/src core/desktop/src-tauri/src 2>/dev/null -maxdepth 6 -type d -name "git" | head; ech | === plugin.json git? === core/src/lamtools_core/plugin_system/dsh_comp… |
|  | python - <<'EOF' import json,glob,os for f in sorted(glob.glob('core/src/lamtools_core/plugins/b | --- core/src/lamtools_core/plugins/bundled\imagegen\plugin.json {"name… |
| 23 | ls .lam/ 2>/dev/null; echo "=== home ==="; ls ~/.lam 2>/dev/null | head; echo "=== find git plug | after_checkpoint.log after_cluster1.log after_cluster2.log after_mode.… |
|  | grep -rn "bundled_core_tool_specs\|_BUNDLED_PLUGIN_TOOL_NAMES" --include=*.py core/src | head -1 | core/src/lamtools_core/app/base_agent.py:2005: from lamtools_core.tool… |
| 24 | grep -rn "additional_context\|systemMessage\|system_context" --include=*.py core/src/lamtools_co | 61: if result.additional_context: 63: item for item in [decision.addit… |
|  | grep -rn "path\b.*plugins\|def bundled_plugins_dir\|def core_plugins_root" -A 8 core/src/lamtool | core/src/lamtools_core/plugin_system/paths.py:38:def bundled_plugins_d… |
| 25 | grep -n "DESKTOP_OVERLAY\|BROWSER_TOOL_NAME\|MEMORY_TOOL_NAME\|LIBRARY_TOOL_NAME\|SUB_AGENT_TOOL | 19: SUB_AGENT_TOOL_NAME, 41: DESKTOP_OVERLAY_TOOL_DESCRIPTION, 42: DES… |
|  | ls .lam/core/plugins 2>/dev/null; echo "---"; ls core/.lam 2>/dev/null; echo "=== dist-plugins = | --- arrange-scheduler.lock artifact backend.log backend.log.1 backend.… |
| 26 | sed -n '455,465p' core/src/lamtools_core/tool/default_toolbox.py && echo "=== spreads in tuple = | "properties": properties, "required": required or [], } DEFAULT_TOOL_D… |
|  | ls core/.lam/plugins 2>/dev/null | head -20; echo "=== git plugin in installed ==="; find core/. | easynet imagegen.jsonc imagegen.lock network-exploration === git plugi… |
| 27 | grep -rn "DEFAULT_TOOL_DEFINITIONS" --include=*.py core/src | head -20 && echo "=== agent.py spe | core/src/lamtools_core/tool/default_toolbox.py:460:DEFAULT_TOOL_DEFINI… |
|  | grep -rn "SUB_AGENT_TOOL_NAME\|SUB_AGENT_MESSAGE_TOOL_NAME" --include=*.py core/src/lamtools_cor | core/src/lamtools_core/tool/default_toolbox.py:17: SUB_AGENT_MESSAGE_T… |
| 28 | grep -n "SUB_AGENT_TOOL_SPEC\|SUB_AGENT_MESSAGE_TOOL_SPEC\|_EXTRA_TOOL\|_AGENT_TOOL" core/src/la | core/src/lamtools_core/tool/default_toolbox.py:18: SUB_AGENT_MESSAGE_T… |
| 29 | grep -n "_runtime_context_fields" -A 60 core/src/lamtools_core/app/base_agent.py | sed -n '1,90p | 1076: def _runtime_context_fields( 1077- self, 1078- state: RuntimeSta… |
|  | git log --oneline -3 -- '*bundled/git*' 2>/dev/null; echo "=== auxiliary instructions ==="; grep | === auxiliary instructions === 15:AUXILIARY_INSTRUCTIONS = ( 16- "You … |
| 30 | grep -rn "def mode_prompt_line" -A 30 --include=*.py core/src | head -40 && echo "=== dispatch_b | core/src/lamtools_core/tool/loadtools.py:138:def mode_prompt_line( cor… |
|  | grep -rn "def _capability_prompt_line" -A 25 core/src/lamtools_core/app/base_agent.py | head -35 | 624: def _capability_prompt_line(self, deferred_attachments: list[str]… |
| 31 | grep -n "name=PLUGIN_" core/src/lamtools_core/plugin_system/manager_tools.py; echo "=== study pl | 40: name=PLUGIN_INSTALL_TOOL, 84: name=PLUGIN_DEPS_TOOL, 100: name=PLU… |
| 32 | grep -n '"agent"\|"prompt"\|"ui"\|exclusiveTools\|"modes"' core/src/lamtools_core/plugins/bundle | 1953: "ui": { 1954: "modes": [ === easynet === === user plugins agents… |
|  | ls plugins/*/plugin.json* 2>/dev/null; echo "=== plugin files ==="; find plugins -maxdepth 2 -na | plugins/bili-scroll/plugin.json plugins/excalidraw/plugin.json plugins… |
| 33 | 输出正文 | — |
