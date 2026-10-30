<template>
  <Teleport to="body">
    <div class="studio-root" data-theme-studio>
      <!--
        user:“父子是父子，层级是层级，不要混为一谈”+
        (左侧拆成两个独立视图：「元素」=父子结构树，纯层级结构；
         「图层」=按 z 排序的 PS 式图层列表，显隐/锁定/重排只属于图层。)
      -->
      <aside
        ref="treeEl"
        class="studio-panel studio-tree optical-glass optical-glass--low-trans"
        :class="{ 'is-open': treeOpen }"
        :style="floatingStyle('tree')"
        data-studio-panel="tree"
        :inert="!treeOpen"
        aria-label="图层"
      >
        <!-- user:“左侧的元素卡和右侧的图层卡，以及底下的工具条，全部都可以被拖动”+(标题栏整条是拖拽手柄，按钮/页签不触发拖动) -->
        <header class="studio-head" data-studio-drag-handle @pointerdown="startFloatingDrag('tree', $event)">
          <span class="studio-grip" data-studio-drag-grip aria-hidden="true">
            <svg viewBox="0 0 10 16"><circle cx="3" cy="3" r="1.1" /><circle cx="7" cy="3" r="1.1" /><circle cx="3" cy="8" r="1.1" /><circle cx="7" cy="8" r="1.1" /><circle cx="3" cy="13" r="1.1" /><circle cx="7" cy="13" r="1.1" /></svg>
          </span>
          <strong>{{ layerView === 'layers' ? t('图层') : t('元素') }}</strong>
          <div class="studio-view-tabs" role="tablist" :aria-label="t('元素')">
            <button class="studio-view-tab" :class="{ 'is-active': layerView === 'elements' }" type="button" data-studio-view="elements" :aria-pressed="layerView === 'elements'" @click="layerView = 'elements'">{{ t('元素') }}</button>
            <button class="studio-view-tab" :class="{ 'is-active': layerView === 'layers' }" type="button" data-studio-view="layers" :aria-pressed="layerView === 'layers'" @click="layerView = 'layers'">{{ t('图层') }}</button>
          </div>
          <button class="studio-icon-btn" type="button" data-studio-close :aria-label="t('关闭并保留草稿')" @click="closeEditor">×</button>
        </header>
        <div class="studio-body">
          <input
            v-model="treeQuery"
            class="studio-tree-search"
            type="search"
            :placeholder="t('搜索图层')"
            data-studio-tree-search
            :aria-label="t('搜索图层')"
          />
          <div v-if="layerView === 'elements'" class="studio-steps">
            <p v-if="visibleEntries.length === 0" class="studio-hint">{{ t('没有匹配的图层') }}</p>
            <button
              v-for="entry in visibleEntries"
              :key="entry.id"
              type="button"
              class="studio-tree-item"
              :class="{ 'is-selected': selectedId === entry.id, 'is-protected': entry.protection === 'protected' }"
              :style="{ paddingLeft: `${12 + entry.depth * 14}px` }"
              :data-studio-node="entry.id"
              @click="select(entry.id, $event.ctrlKey || $event.metaKey)"
            >
              <span
                v-if="hasChildren(entry.id)"
                class="studio-tree-caret"
                :data-studio-tree-caret="entry.id"
                :aria-label="collapsedGroups.has(entry.id) ? t('展开') : t('折叠')"
                @click.stop="toggleCollapse(entry.id)"
              >{{ collapsedGroups.has(entry.id) ? '▸' : '▾' }}</span>
              <span class="studio-tree-label">{{ t(entry.label) }}</span>
              <span class="studio-tree-meta">{{ entry.id }}</span>
            </button>
          </div>
          <!--
            图层视图：按 z 层带从高到低排列，每带可折叠；
            user:“auto不要单开，挂在对应的图层内，层级写为 auto12345 层”+
            (auto 子层归入父层所在的层带，层级列直接写 auto+顺序号，不再单独成组)
          -->
          <div v-else class="studio-steps" data-studio-layers>
            <p v-if="layerRows.length === 0" class="studio-hint">{{ t('没有匹配的图层') }}</p>
            <template v-for="row in layerRows" :key="row.id">
              <button
                v-if="row.bandHeader"
                class="studio-layer-band"
                type="button"
                :data-studio-layer-band="row.band"
                :aria-expanded="!collapsedBands.has(row.band)"
                @click="toggleBand(row.band)"
              >{{ collapsedBands.has(row.band) ? '▸' : '▾' }} {{ t('第 {0} 层', { 0: row.band }) }}</button>
              <div
                v-if="!collapsedBands.has(row.band)"
                class="studio-tree-item studio-layer-item"
                :class="{ 'is-selected': selectedId === row.id, 'is-nested': row.depth > 0 }"
                :style="{ paddingLeft: `${8 + row.depth * 14}px` }"
                :data-studio-layer-row="row.id"
                :data-studio-layer-depth="row.depth"
                draggable="true"
                @dragstart="onLayerDragStart(row.id)"
                @dragover.prevent
                @drop.prevent="onLayerDrop(row.id)"
                @click="select(row.id, false)"
              >
                <span class="studio-tree-actions">
                  <!-- user:“那就再细分一层，把它挂在那个会话抽屉底下”+(父容器左边的箭头收起/展开它下面的自动子层) -->
                  <button
                    v-if="row.hasAutoChildren"
                    class="studio-layer-caret"
                    type="button"
                    :data-studio-auto-caret="row.id"
                    :aria-label="collapsedAuto.has(row.id) ? t('展开') : t('折叠')"
                    :aria-expanded="!collapsedAuto.has(row.id)"
                    @click.stop="toggleAutoGroup(row.id)"
                  >{{ collapsedAuto.has(row.id) ? '▸' : '▾' }}</button>
                  <span v-else class="studio-layer-caret is-empty" aria-hidden="true" />
                  <button class="studio-tree-action" type="button" :data-studio-eye="row.id" :aria-label="t('显示/隐藏图层')" :aria-pressed="!editorHidden.has(row.id)" @click.stop="toggleEditorHidden(row.id)">{{ editorHidden.has(row.id) ? '○' : '●' }}</button>
                  <button class="studio-tree-action" type="button" :data-studio-lock="row.id" :aria-label="t('锁定/解锁图层')" :aria-pressed="editorLocked.has(row.id)" @click.stop="toggleEditorLocked(row.id)">{{ editorLocked.has(row.id) ? '▣' : '□' }}</button>
                </span>
                <span class="studio-layer-copy">
                  <span class="studio-tree-label">{{ t(row.label) }}</span>
                  <span v-if="row.auto && autoLayerMeta(row)" class="studio-tree-meta">{{ autoLayerMeta(row) }}</span>
                </span>
                <input
                  class="studio-layer-input"
                  :class="{ 'is-auto': row.auto }"
                  type="text"
                  inputmode="numeric"
                  :value="layerValueText(row)"
                  :data-studio-layer-input="row.id"
                  :aria-label="t('层级')"
                  :title="row.auto ? t('自动（跟随页面）') : t('层级')"
                  @click.stop
                  @change="updateLayerValue(row.id, $event)"
                />
              </div>
            </template>
          </div>
        </div>
        <!--
          user:“工具条精简，按钮：开关键|图层卡 元素卡| 撤销 重做|磁铁 辅助线|取消 确认”+
          (导入/导出/恢复默认不再占底部工具条，收进元素卡底部的图标行；状态只在这里显示。)
        -->
        <footer class="studio-panel-footer" data-studio-secondary>
          <button class="studio-tool-icon" type="button" data-studio-import :aria-label="t('导入')" :title="t('导入')" @click="pickImport">
            <svg class="studio-icon-svg" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2v7.5" /><path d="m4.5 6 3.5 3.5L11.5 6" /><path d="M2.5 13.5h11" /></svg>
          </button>
          <button class="studio-tool-icon" type="button" data-studio-export :aria-label="t('导出')" :title="t('导出')" @click="exportDocument">
            <svg class="studio-icon-svg" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 12V4.5" /><path d="m4.5 8 3.5-3.5L11.5 8" /><path d="M2.5 13.5h11" /></svg>
          </button>
          <button class="studio-tool-icon" type="button" data-studio-reset :aria-label="t('恢复默认')" :title="t('恢复默认')" @click="resetConfirm = true">
            <svg class="studio-icon-svg" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 6.5a5 5 0 1 1 .6 4.6" /><path d="M3 2.8v3.7h3.7" /></svg>
          </button>
          <span class="studio-spacer" />
          <span class="studio-status">{{ store.dirty.value ? t('有未发布修改') : t('已同步') }}</span>
          <input ref="importEl" type="file" accept="application/json,.json" hidden @change="importDocument" />
        </footer>
      </aside>

      <!-- 编辑模式关闭时画布进入浏览态：选框、参考线、对齐条全部隐藏，界面照常可点。 -->
      <div
        class="studio-canvas"
        :class="{ 'is-browsing': !editMode, 'is-overlay-hidden': !overlaysVisible }"
        data-studio-canvas
        aria-hidden="true"
      >
        <div ref="outlineEl" class="studio-outline" :class="{ 'is-visible': Boolean(selectedId) }" />
        <div
          v-for="rect in extraRects"
          :key="`${rect.left}-${rect.top}-${rect.width}`"
          class="studio-outline studio-outline--extra is-visible"
          :style="{ top: `${rect.top}px`, left: `${rect.left}px`, width: `${rect.width}px`, height: `${rect.height}px` }"
        />
        <!-- 父容器青绿轮廓、父子中心虚线、悬停细框、模板紫框与实例虚线（方案 §3.3/§3.4/§9.4） -->
        <div v-if="parentBox" class="studio-parent-box" :style="rectStyle(parentBox)" />
        <svg class="studio-links" aria-hidden="true">
          <line v-if="parentLink" class="studio-parent-link" :x1="parentLink.x1" :y1="parentLink.y1" :x2="parentLink.x2" :y2="parentLink.y2" />
        </svg>
        <div v-if="hoverBox" class="studio-hover-box" :style="rectStyle(hoverBox)" />
        <div v-if="templateSampleBox" class="studio-template-sample" :style="rectStyle(templateSampleBox)" />
        <div
          v-for="(rect, index) in templateSiblingBoxes"
          :key="`sibling-${index}`"
          class="studio-template-sibling"
          :style="rectStyle(rect)"
        />
        <!-- user:“为什么没有拉伸拖拽功能……我想把它缩小一下”+(八个边界手柄，拖拽实时预览) -->
        <div v-if="resizeBox" class="studio-resize-frame" :style="rectStyle(resizeBox)">
          <span
            v-for="dir in RESIZE_DIRS"
            :key="dir"
            class="studio-resize-handle"
            :class="`studio-resize-handle--${dir}`"
            :data-studio-resize="dir"
            @pointerdown="onResizePointerDown(dir, $event)"
          />
        </div>
        <!-- user:“点任意同级项间的标记，实际编辑的是父级列表 gap”+(间距胶囊：滚轮 ±1/Shift ±8/双击输入) -->
        <div
          v-if="spacingTarget && gapPillPos"
          class="studio-gap-pill"
          data-studio-gap-pill
          :style="{ left: `${gapPillPos.left}px`, top: `${gapPillPos.top}px` }"
          :title="t('滚轮 ±1，Shift ±8，双击输入')"
          @wheel.prevent="onGapWheel"
          @dblclick="startGapEditing"
        >
          <template v-if="!gapEditing">{{ t('间距') }} {{ spacingTarget.gap }}</template>
          <input
            v-else
            ref="gapInputEl"
            type="number"
            min="0"
            :value="spacingTarget.gap"
            data-studio-gap-input
            :aria-label="t('间距')"
            @blur="commitGapInput"
            @keydown.enter="commitGapInput"
          />
        </div>
        <div ref="guideXEl" class="studio-guide studio-guide--x" />
        <div ref="guideYEl" class="studio-guide studio-guide--y" />
        <div v-if="dragHint" class="studio-drag-hint">{{ dragHint }}</div>
        <div v-if="selectedIds.length > 1" class="studio-align-bar optical-glass optical-glass--low-trans" role="toolbar" :aria-label="t('对齐与分布')">
          <button class="studio-btn" type="button" data-studio-align="left" @click="applyAlign('left')">{{ t('左对齐') }}</button>
          <button class="studio-btn" type="button" data-studio-align="centerX" @click="applyAlign('centerX')">{{ t('水平居中') }}</button>
          <button class="studio-btn" type="button" data-studio-align="right" @click="applyAlign('right')">{{ t('右对齐') }}</button>
          <button class="studio-btn" type="button" data-studio-align="top" @click="applyAlign('top')">{{ t('顶对齐') }}</button>
          <button class="studio-btn" type="button" data-studio-align="centerY" @click="applyAlign('centerY')">{{ t('垂直居中') }}</button>
          <button class="studio-btn" type="button" data-studio-align="bottom" @click="applyAlign('bottom')">{{ t('底对齐') }}</button>
          <button class="studio-btn" type="button" data-studio-align="distributeX" @click="applyAlign('distributeX')">{{ t('水平分布') }}</button>
          <button class="studio-btn" type="button" data-studio-align="distributeY" @click="applyAlign('distributeY')">{{ t('垂直分布') }}</button>
        </div>
      </div>

      <aside
        ref="miniEl"
        class="studio-panel studio-props optical-glass optical-glass--low-trans"
        :class="{ 'is-open': propsOpen || miniInspector, 'is-mini': miniInspector && !propsOpen }"
        :style="propsPanelStyle"
        data-studio-panel="props"
        :data-studio-mini-inspector="miniInspector && !propsOpen ? 'true' : undefined"
        :inert="!propsOpen && !miniInspector"
        aria-label="属性"
      >
        <header class="studio-head" data-studio-drag-handle @pointerdown="startFloatingDrag('props', $event)">
          <span class="studio-grip" data-studio-drag-grip aria-hidden="true">
            <svg viewBox="0 0 10 16"><circle cx="3" cy="3" r="1.1" /><circle cx="7" cy="3" r="1.1" /><circle cx="3" cy="8" r="1.1" /><circle cx="7" cy="8" r="1.1" /><circle cx="3" cy="13" r="1.1" /><circle cx="7" cy="13" r="1.1" /></svg>
          </span>
          <strong>{{ selectedEntry ? t(selectedEntry.label) : t('属性') }}</strong>
          <span v-if="selectedEntry" class="studio-badge">{{ protectionLabel(selectedEntry.protection) }}</span>
        </header>
        <p v-if="selectedEntry" class="studio-hint" data-studio-parent-hint>{{ t('父级') }}：{{ selectedEntry.parent || '—' }}</p>

        <div class="studio-body">
        <div class="studio-scope">
          <select :value="scope" class="studio-select" data-studio-scope @change="setScope">
            <option value="base">{{ selectedIsTemplate ? t('模板样式') : t('基础样式') }}</option>
            <option v-if="instanceKey" value="instance">{{ t('此实例') }} · {{ instanceKey }}</option>
            <option v-for="item in store.draft.value.breakpoints" :key="item.id" :value="item.id">
              {{ t('窄于') }} {{ item.maxWidth }}px
            </option>
          </select>
          <button class="studio-secondary" type="button" data-studio-add-breakpoint @click="addBreakpoint">{{ t('按当前宽度加断点') }}</button>
          <button v-if="scope !== 'base' && scope !== 'instance'" class="studio-secondary" type="button" data-studio-remove-breakpoint @click="removeBreakpoint">{{ t('删除这个断点') }}</button>
          <p v-if="scope !== 'base' && scope !== 'instance'" class="studio-hint">{{ t('正在编辑窄屏覆盖，只影响该宽度以下。') }}</p>
          <p v-if="scope === 'instance'" class="studio-hint" data-studio-instance-hint>{{ t('正在编辑这一条，只影响它自己。') }}</p>
        </div>

        <p v-if="!selectedEntry" class="studio-hint">{{ t('先选择一个组件。') }}</p>
        <template v-else>
          <p v-if="selectedEntry.protection === 'protected'" class="studio-hint">
            {{ t('这个组件是业务入口，只能调整外观，不能移动或隐藏。') }}
          </p>

          <label v-if="allows('color')" class="studio-field">
            <span>{{ t('文字颜色') }}</span>
            <input type="color" :value="styleOf('color', '#f2efeb')" :data-studio-field="'color'" @input="updateColor('color', $event)" />
          </label>

          <label v-if="allows('background')" class="studio-field">
            <span>{{ t('背景颜色') }}</span>
            <div class="studio-color-row">
              <input type="color" :value="backgroundColor" :disabled="backgroundToken !== ''" data-studio-field="background" @input="updateBackground($event)" />
              <!--
                user:“那个背景色除了可直接选色，也应该和主题 token 关联上”+
                (颜色来源：自定义色 / 透明 / 主题令牌；令牌跟随主题预设自动变化，选令牌时色盘停用。)
              -->
              <select class="studio-select" :value="backgroundToken" data-studio-color-token :aria-label="t('背景颜色')" @change="updateBackgroundToken">
                <option value="">{{ t('自定义颜色') }}</option>
                <option v-for="option in COLOR_TOKEN_OPTIONS" :key="option.value" :value="option.value">{{ t(option.label) }}</option>
              </select>
            </div>
          </label>

          <label v-if="allows('background')" class="studio-field">
            <span>{{ t('背景透明度') }} {{ percent(backgroundOpacity) }}</span>
            <input type="range" min="0" max="1" step="0.05" :value="backgroundOpacity" data-studio-field="background-opacity" :aria-label="t('背景透明度')" @input="updateBackgroundOpacity($event)" />
          </label>

          <div v-if="allows('background')" class="studio-field">
            <span>{{ t('背景素材') }}</span>
            <div class="studio-asset-row">
              <!--
                user:“添加图片应该是一个按钮。如果成功添加图片之后，该按钮应换成图片的小号预览，点击即可更换图片”+
                (无素材=「选择图片」按钮；有素材=同一按钮位置换成像素材缩略片，点它直接换图；清除仍然分开。)
              -->
              <button
                class="studio-secondary studio-asset-chip"
                :class="{ 'has-thumb': Boolean(assetPreviewUrl) }"
                type="button"
                data-studio-pick-asset
                :aria-label="hasAsset ? t('更换图片') : t('选择图片')"
                @click="pickAsset"
              >
                <img
                  v-if="assetPreviewUrl"
                  class="studio-asset-thumb"
                  data-studio-asset-preview
                  :src="assetPreviewUrl"
                  alt=""
                />
                <span v-else>{{ t('选择图片') }}</span>
              </button>
              <button v-if="hasAsset" class="studio-secondary" type="button" data-studio-clear-asset @click="clearAsset">{{ t('清除') }}</button>
            </div>
            <select :value="assetFit" class="studio-select" data-studio-asset-fit :disabled="!hasAsset" :aria-label="t('背景素材')" @change="updateFit">
              <option value="fixed">fixed</option>
              <option value="contain">contain</option>
              <option value="cover">cover</option>
              <option value="stretch">stretch</option>
              <option value="tile">tile</option>
              <option value="nineSlice">nineSlice</option>
            </select>
            <!-- user:“添加的图像应该可以裁切、位移、缩放等等”+(裁切=上面的适配方式；这里补位置与缩放) -->
            <div v-if="hasAsset" class="studio-field studio-field--pair">
              <span>{{ t('图片位置') }}</span>
              <input type="number" min="0" max="100" :value="activeBackground?.positionX ?? 50" data-studio-bg-pos="x" :aria-label="t('横向位置')" @input="updateBackgroundPosition('x', $event)" />
              <input type="number" min="0" max="100" :value="activeBackground?.positionY ?? 50" data-studio-bg-pos="y" :aria-label="t('纵向位置')" @input="updateBackgroundPosition('y', $event)" />
            </div>
            <label v-if="hasAsset" class="studio-field">
              <span>{{ t('图片缩放') }} {{ backgroundScale.toFixed(1) }}×</span>
              <input type="number" min="0.1" max="4" step="0.1" :value="backgroundScale" data-studio-bg-scale :aria-label="t('图片缩放')" @input="updateBackgroundScale($event)" />
            </label>
            <!--
              user:“把图片的编辑器给做成九宫格裁切，九宫格可拖动，九宫格就代表了这个图片实际显示进去的是什么部分”+
              (整图预览 + 三等分参考线；整块区域=组件实际显示范围，拖动它选择显示哪一段。
               拖动只改取景（位置百分比），松手才提交；缩放数值在上方联动。)
            -->
            <div
              v-if="hasAsset"
              ref="cropEl"
              class="studio-crop"
              data-studio-crop
              :style="[cropImageStyle, cropFrameStyle]"
              :aria-label="t('拖动九宫格选择图片显示的部分')"
              @pointerdown="onCropPointerDown"
            >
              <span class="studio-crop-grid" aria-hidden="true" />
            </div>
            <p v-if="hasAsset" class="studio-hint">{{ t('九宫格就是实际显示的部分，拖动可直接改取景。') }}</p>
            <div v-if="assetFit === 'nineSlice'" class="studio-slice">
              <input v-for="side in (['top', 'right', 'bottom', 'left'] as const)" :key="side" type="number" min="0" max="1000" :value="sliceOf(side)" :aria-label="t(side)" :data-studio-slice="side" @input="updateSlice(side, $event)" />
            </div>
            <label v-if="hasAsset" class="studio-field studio-field--row">
              <span>{{ t('允许溢出组件') }}</span>
              <input type="checkbox" :checked="assetOverflow === 'local-visible'" data-studio-asset-overflow @change="updateOverflow" />
            </label>
            <input ref="assetEl" type="file" accept="image/*" hidden @change="importAsset" />
          </div>

          <label v-if="allows('opacity')" class="studio-field">
            <span>{{ t('透明度') }} {{ percent(styleOf('opacity', 1)) }}</span>
            <input type="range" min="0" max="1" step="0.05" :value="styleOf('opacity', 1)" data-studio-field="opacity" @input="updateNumber('opacity', $event)" />
          </label>

          <div v-if="allows('position')" class="studio-field studio-field--pair">
            <span>{{ t('位置') }}</span>
            <input type="number" :value="offsetOf('x')" data-studio-field="offset-x" :aria-label="t('横向位置')" @input="updateOffset('x', $event)" />
            <input type="number" :value="offsetOf('y')" data-studio-field="offset-y" :aria-label="t('纵向位置')" @input="updateOffset('y', $event)" />
          </div>

          <!--
            user:“所有的布局实际上都是父子容器的关系，子容器应当是相对于父容器的某一个边或者某几个边设定距离，
            而兜底就是距离不得小于 0”+(方案 §4.4：锚点引用父容器的具体边，距离非负；相对数值随父容器响应式变化)
          -->
          <div v-if="allows('position')" class="studio-field" data-studio-anchors>
            <span>{{ t('锚点') }}</span>
            <div class="studio-size-row">
              <span class="studio-size-axis">{{ t('横向') }}</span>
              <select class="studio-select" :value="anchorOf('h')?.edge ?? ''" data-studio-anchor-edge="h" :aria-label="t('横向锚点')" @change="updateAnchorEdge('h', $event)">
                <option value="">{{ t('不锚定') }}</option>
                <option value="left">{{ t('左') }}</option>
                <option value="centerX">{{ t('水平居中') }}</option>
                <option value="right">{{ t('右') }}</option>
              </select>
              <input type="number" min="0" :value="anchorOf('h')?.offset ?? 0" data-studio-anchor-offset="h" :aria-label="t('横向距离')" :disabled="!anchorOf('h')" @input="updateAnchorOffset('h', $event)" />
            </div>
            <div class="studio-size-row">
              <span class="studio-size-axis">{{ t('纵向') }}</span>
              <select class="studio-select" :value="anchorOf('v')?.edge ?? ''" data-studio-anchor-edge="v" :aria-label="t('纵向锚点')" @change="updateAnchorEdge('v', $event)">
                <option value="">{{ t('不锚定') }}</option>
                <option value="top">{{ t('上') }}</option>
                <option value="centerY">{{ t('垂直居中') }}</option>
                <option value="bottom">{{ t('下') }}</option>
              </select>
              <input type="number" min="0" :value="anchorOf('v')?.offset ?? 0" data-studio-anchor-offset="v" :aria-label="t('纵向距离')" :disabled="!anchorOf('v')" @input="updateAnchorOffset('v', $event)" />
            </div>
            <p class="studio-hint">{{ t('锚点=到父容器某条边的距离，不会小于 0。') }}</p>
          </div>

          <label v-if="allows('radius')" class="studio-field">
            <span>{{ t('圆角') }}</span>
            <input type="number" min="0" max="64" :value="numberOf('radius', 0)" data-studio-field="radius" @input="updateNumber('radius', $event)" />
          </label>

          <label v-if="allows('spacing')" class="studio-field">
            <span>{{ t('间距') }}</span>
            <input type="number" min="0" max="64" :value="draftGap" data-studio-field="gap" @input="updateGap($event)" />
          </label>

          <!-- user:“按这个设计方案审…补齐”+(方案 §4.3：宽高各自有模式 fill/hug/固定，可配最小/最大) -->
          <div v-if="allows('size')" class="studio-field" data-studio-size>
            <span>{{ t('尺寸') }}</span>
            <div v-for="axis in (['width', 'height'] as const)" :key="axis" class="studio-size-row">
              <span class="studio-size-axis">{{ axis === 'width' ? t('宽度') : t('高度') }}</span>
              <select class="studio-select" :value="sizeModeOf(axis)" :data-studio-size-mode="axis" :aria-label="axis === 'width' ? t('宽度') : t('高度')" @change="updateSizeMode(axis, $event)">
                <option value="">{{ t('未设置') }}</option>
                <option value="fill">{{ t('填充') }}</option>
                <option value="hug">{{ t('内容适配') }}</option>
                <option value="fixed">{{ t('固定值') }}</option>
              </select>
              <input v-if="sizeModeOf(axis) === 'fixed'" type="number" :value="sizeValueOf(axis)" :data-studio-size-value="axis" :aria-label="t('固定值')" @input="updateSizeValue(axis, $event)" />
              <input type="number" min="0" :value="sizeBoundOf(axis, 'min')" :data-studio-size-min="axis" :aria-label="t('最小')" placeholder="min" @input="updateSizeBound(axis, 'min', $event)" />
              <input type="number" min="0" :value="sizeBoundOf(axis, 'max')" :data-studio-size-max="axis" :aria-label="t('最大')" placeholder="max" @input="updateSizeBound(axis, 'max', $event)" />
            </div>
          </div>

          <label v-if="allows('text')" class="studio-field">
            <span>{{ t('字号') }}</span>
            <input type="number" min="10" max="40" :value="draftFontSize" data-studio-field="text-size" @input="updateFontSize($event)" />
          </label>

          <label v-if="allows('layer')" class="studio-field">
            <span>{{ t('层级') }} z={{ draftLayer }} · {{ t('第 {0} 层', { 0: Math.max(1, Math.ceil(draftLayer / 100)) }) }}</span>
            <!-- user:“输入层级数值的时候 不要让它直接变，摁回车，或者点其他地方保存了再变”+(只在回车/失焦时提交，避免边输入边跳层) -->
            <input type="number" min="0" max="9999" :value="draftLayer" data-studio-field="layer" @change="updateLayer($event)" />
          </label>

          <label v-if="allows('visibility')" class="studio-field studio-field--row">
            <span>{{ t('显示') }}</span>
            <input type="checkbox" :checked="draftVisibility" data-studio-field="visibility" @change="updateVisibility($event)" />
          </label>

          <button class="studio-secondary" type="button" @click="clearSelected">{{ t('清除这个组件的修改') }}</button>
        </template>

        <p v-if="errors.length" class="studio-error" role="alert">{{ errors[0].message }}</p>
        </div>
      </aside>

      <div ref="toolbarEl" class="studio-toolbar-wrap" data-studio-toolbar-float :style="floatingStyle('bar')">
        <!-- user:“那个正在预览真实界面那个话，用一个小胶囊，下边不圆角，贴住控件 bar 的上沿，低透玻璃样式”+(提示胶囊跟着工具条走，下沿与 bar 上沿对接) -->
        <p class="studio-canvas-hint optical-glass optical-glass--low-trans">{{ editMode ? t('正在预览真实界面，修改会立即生效。') : t('编辑模式已关闭，界面可正常操作。') }}</p>
      <footer
        class="studio-toolbar optical-glass optical-glass--low-trans"
        data-studio-toolbar
        aria-label="编辑器操作"
        @pointerdown="startFloatingDrag('bar', $event)"
      >
        <!--
          user:“我希望左侧的元素卡和右侧的图层卡，以及底下的工具条，全部都可以被拖动，同时工具条精简，
          按钮：开关键|图层卡 元素卡| 撤销 重做|磁铁 辅助线|取消 确认，每一个都是单独的键，不写文字，
          用图标表示，确认带反馈动画，|表示需要竖线分割”+
          (工具条只剩图标键：编辑开关｜图层/元素卡｜撤销/重做｜吸附/辅助线｜取消/确认；拖动条整条可拖)
        -->
        <span class="studio-grip studio-grip--bar" data-studio-drag-grip aria-hidden="true">
          <svg viewBox="0 0 10 16"><circle cx="3" cy="3" r="1.1" /><circle cx="7" cy="3" r="1.1" /><circle cx="3" cy="8" r="1.1" /><circle cx="7" cy="8" r="1.1" /><circle cx="3" cy="13" r="1.1" /><circle cx="7" cy="13" r="1.1" /></svg>
        </span>
        <span class="studio-edit-mode" data-studio-edit-mode>
          <SundaySwitch v-model="editMode" :label="t('编辑模式')" size="sm" />
        </span>
        <span class="studio-toolbar-divider" aria-hidden="true" />
        <button
          class="studio-tool-icon"
          :class="{ 'is-active': treeOpen }"
          type="button"
          data-studio-open-layers
          :aria-label="t('图层')"
          :title="t('图层')"
          :aria-pressed="treeOpen"
          @click="toggleTree"
        >
          <svg class="studio-icon-svg" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.8 14.2 5 8 8.2 1.8 5 8 1.8Z" /><path d="M2.4 7.6 8 10.5l5.6-2.9" /><path d="M2.4 10.4 8 13.3l5.6-2.9" /></svg>
        </button>
        <button
          class="studio-tool-icon"
          :class="{ 'is-active': propsOpen }"
          type="button"
          data-studio-open-props
          :aria-label="t('属性')"
          :title="t('属性')"
          :aria-pressed="propsOpen"
          @click="toggleProps"
        >
          <svg class="studio-icon-svg" viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 4h11M2.5 8h11M2.5 12h11" /><circle cx="6" cy="4" r="1.6" fill="currentColor" stroke="none" /><circle cx="10.5" cy="8" r="1.6" fill="currentColor" stroke="none" /><circle cx="5" cy="12" r="1.6" fill="currentColor" stroke="none" /></svg>
        </button>
        <span class="studio-toolbar-divider" aria-hidden="true" />
        <button class="studio-tool-icon" type="button" data-studio-undo :aria-label="t('撤销')" :title="t('撤销')" :disabled="!store.canUndo.value" @click="store.undo()">
          <svg class="studio-icon-svg" viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3.5 2.5 7 6 10.5" /><path d="M2.5 7h6.3a4 4 0 0 1 0 8H6.5" /></svg>
        </button>
        <button class="studio-tool-icon" type="button" data-studio-redo :aria-label="t('重做')" :title="t('重做')" :disabled="!store.canRedo.value" @click="store.redo()">
          <svg class="studio-icon-svg" viewBox="0 0 16 16" aria-hidden="true"><path d="m10 3.5 3.5 3.5L10 10.5" /><path d="M13.5 7H7.2a4 4 0 0 0 0 8h2.3" /></svg>
        </button>
        <span class="studio-toolbar-divider" aria-hidden="true" />
        <button
          class="studio-tool-icon"
          :class="{ 'is-active': snapEnabled }"
          type="button"
          data-studio-snap-toggle
          :aria-label="t('吸附')"
          :title="t('吸附')"
          :aria-pressed="snapEnabled"
          @click="snapEnabled = !snapEnabled"
        >
          <svg class="studio-icon-svg" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 2.5v5a4.5 4.5 0 0 0 9 0v-5" /><path d="M3.5 5.8h3.1M9.4 5.8h3.1" /></svg>
        </button>
        <button
          class="studio-tool-icon"
          :class="{ 'is-active': overlaysVisible }"
          type="button"
          data-studio-overlay-toggle
          :aria-label="t('辅助线')"
          :title="t('辅助线')"
          :aria-pressed="overlaysVisible"
          @click="overlaysVisible = !overlaysVisible"
        >
          <svg class="studio-icon-svg" viewBox="0 0 16 16" aria-hidden="true"><path d="M2 5.5h12M2 10.5h12" opacity="0.55" /><path d="M5.5 2v12M10.5 2v12" /></svg>
        </button>
        <span class="studio-toolbar-divider" aria-hidden="true" />
        <button class="studio-tool-icon" type="button" data-studio-cancel :aria-label="t('不保存修改并退出')" :title="t('取消')" @click="cancelEdit">
          <svg class="studio-icon-svg" viewBox="0 0 16 16" aria-hidden="true"><path d="m4 4 8 8M12 4l-8 8" /></svg>
        </button>
        <!-- user:“确认带反馈动画”+(先落地发布，按钮打勾脉冲一下再关闭编辑器) -->
        <button
          class="studio-tool-icon studio-tool-icon--confirm"
          :class="{ 'is-confirmed': publishFeedback === 'confirmed' }"
          type="button"
          data-studio-publish
          :aria-label="t('发布')"
          :title="t('发布')"
          @click="confirmPublish"
        >
          <svg class="studio-icon-svg" viewBox="0 0 16 16" aria-hidden="true"><path d="m3.5 8.5 3 3 6-7" /></svg>
        </button>
      </footer>
      </div>

      <!-- 独立审查可用性项：恢复默认不可回退，加确认（统一走 CoreConfirmDialog 胶囊）。 -->
      <CoreConfirmDialog
        :open="resetConfirm"
        :title="t('恢复默认？')"
        :detail="t('将清除已发布的主题与当前草稿，无法撤销。')"
        @confirm="confirmReset"
        @cancel="resetConfirm = false"
      />
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { t } from '@/i18n/index.ts'
import { UI_REGISTRY, type UiProtectionLevel, type UiRegistryEntry } from '@/uiRegistry/index.ts'
import { createStudioStore, type StudioStorage } from '@/themeStudio/store.ts'
import { THEME_STUDIO_SCHEMA_VERSION, type StudioAnchorEdge, type StudioBackground, type StudioColorToken, type StudioDimension, type StudioDocument, type StudioNodeAnchor, type StudioNodeStyle, type StudioSize } from '@/themeStudio/schema.ts'
import { snapOffset, OFFSET_LIMIT, type Offset } from '@/themeStudio/drag.ts'
import { alignDeltas, distributeDeltas } from '@/themeStudio/align.ts'
import { THEME_STUDIO_DRAFT_STORAGE_KEY, THEME_STUDIO_STORAGE_KEY } from '@/themeStudio/constants.ts'
import { migrateStudioDocument } from '@/themeStudio/migrate.ts'
import { validateStudioDocument } from '@/themeStudio/validate.ts'
import { useThemeStudio } from '@/composables/useThemeStudio.ts'
import SundaySwitch from '@/components/SundaySwitch.vue'
import CoreConfirmDialog from '@/components/CoreConfirmDialog.vue'

/**
 * user:“可视化主题与布局编辑器”+
 * (三栏工作台：左侧图层、中间真实界面实时预览、右侧属性。
 *  编辑只写草稿并预览，发布会落盘；业务入口只能改外观。)
 */
const emit = defineEmits<{ close: [] }>()

const STORAGE_KEY = THEME_STUDIO_STORAGE_KEY

// user:“编辑器状态下两个左右栏不要常驻，用一个点击可打开收起的圆形图标”+
// user:“点图层按钮不要同时把图层和属性调出来，点属性按钮也一样”+
// (左右两张卡各自开关：图层=左侧图层/元素卡，属性=右侧属性卡，互不联动)
const treeOpen = ref(false)
const propsOpen = ref(false)
const editMode = ref(true)
// 打开状态是应用级单例；编辑器内任何关闭路径都同步回全局。
const { studioOpen } = useThemeStudio()
// user:“按这个设计方案审…补齐”+(方案 §3.1 吸附开关与 §9.4 辅助标注层开关，都是编辑会话状态，不进主题文档)
const snapEnabled = ref(true)
const overlaysVisible = ref(true)
const resetConfirm = ref(false)
// user:“不点击双栏键时，右键点击任何一个组件，会在它的旁边找一个位置展开小版右栏，就是不能遮挡那个组件”+
// (小版右栏=完整属性面板的紧凑浮层，定位在目标元素旁边；双栏展开或 Esc/点空白即收起。)
const miniInspector = ref(false)
const miniStyle = ref<Record<string, string> | undefined>(undefined)
const miniEl = ref<HTMLElement | null>(null)
// user:“我希望左侧的元素卡和右侧的图层卡，以及底下的工具条，全部都可以被拖动”+
// (三块浮层各自记住拖拽后的位置，只在本次编辑会话里有效，不写进主题文档。)
type FloatingCard = 'tree' | 'props' | 'bar'
interface FloatingPoint { x: number; y: number }
const treeEl = ref<HTMLElement | null>(null)
const toolbarEl = ref<HTMLElement | null>(null)
const floatingPositions = ref<Record<FloatingCard, FloatingPoint | null>>({ tree: null, props: null, bar: null })
// user:“确认带反馈动画”+(发布成功后按钮先打勾脉冲，再关闭编辑器)
const publishFeedback = ref<'idle' | 'confirmed'>('idle')
let publishCloseTimer = 0
// user:“这个图层应该像 PS 一样可单独编辑，显隐/锁定等”+
// (eye=只在编辑器里隐藏该层，不写主题；lock=禁止画布上的点选/拖动/改尺寸。)
const editorHidden = ref<Set<string>>(new Set())
const editorLocked = ref<Set<string>>(new Set())
let editorStateStyleEl: HTMLStyleElement | null = null

function toggleEditorHidden(id: string): void {
  const next = new Set(editorHidden.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  editorHidden.value = next
}

function toggleEditorLocked(id: string): void {
  const next = new Set(editorLocked.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  editorLocked.value = next
}

function syncEditorStateStyles(): void {
  if (!editorStateStyleEl) return
  const rules = [...editorHidden.value].map((id) => {
    const kind = UI_REGISTRY.find((entry) => entry.id === id)?.kind
    return kind === 'template'
      ? `[data-ui-template="${id}"] { visibility: hidden }`
      : `[data-ui-id="${id}"] { visibility: hidden }`
  })
  editorStateStyleEl.textContent = rules.join('\n')
}

watch(editorHidden, syncEditorStateStyles)

function isEditorLocked(id: string | null | undefined): boolean {
  return Boolean(id && editorLocked.value.has(id))
}

const storage: StudioStorage = {
  read: () => {
    try {
      const raw = globalThis.localStorage?.getItem(STORAGE_KEY)
      return raw ? JSON.parse(raw) : null
    } catch {
      return null
    }
  },
  write: (raw) => {
    try {
      globalThis.localStorage?.setItem(STORAGE_KEY, JSON.stringify(raw))
    } catch {
      /* 存不下时保持内存态，不打断编辑 */
    }
  },
}

const assetUrls = ref<Record<string, string>>({})
const assetEl = ref<HTMLInputElement | null>(null)
const store = createStudioStore({
  storage,
  themeId: 'studio',
  applyOptions: { assetUrl: (id) => assetUrls.value[id] || null },
})
const errors = store.errors

// user:“按这个设计方案审…补齐”+(方案 §10.1 自动保存草稿：编辑写 localStorage，重开接着改；
//  发布/取消/恢复默认清除。坏草稿直接丢弃，绝不影响已发布主题。)
// 防抖写入：滑块/数字微调时不逐次全量序列化；卸载时冲刷最后一次。
let suppressAutosave = false
let autosaveTimer: number | null = null

function writeDraftStorage(draft: StudioDocument): void {
  try {
    globalThis.localStorage?.setItem(THEME_STUDIO_DRAFT_STORAGE_KEY, JSON.stringify(draft))
  } catch {
    /* 存不下（多为配额）时草稿只在内存里，不打断编辑 */
  }
}

watch(store.draft, (draft) => {
  if (suppressAutosave) {
    suppressAutosave = false
    return
  }
  if (autosaveTimer !== null) clearTimeout(autosaveTimer)
  autosaveTimer = window.setTimeout(() => {
    autosaveTimer = null
    writeDraftStorage(draft)
  }, 250)
}, { deep: true })

function flushPendingAutosave(): void {
  if (autosaveTimer === null) return
  clearTimeout(autosaveTimer)
  autosaveTimer = null
  writeDraftStorage(store.draft.value)
}

function clearDraftStorage(): void {
  suppressAutosave = true
  if (autosaveTimer !== null) {
    clearTimeout(autosaveTimer)
    autosaveTimer = null
  }
  try {
    globalThis.localStorage?.removeItem(THEME_STUDIO_DRAFT_STORAGE_KEY)
  } catch {
    /* 忽略存储异常 */
  }
}

// 独立审查 P1：编辑模式/辅助开关切换时立即重算或清空覆盖层，不留旧位置的框。
// 编辑模式关掉时若有拖拽进行中，一并废弃。
watch([editMode, overlaysVisible], () => {
  hoverBox.value = null
  if (!editMode.value && dragState) abortDrag()
  void nextTick(() => syncOutline())
})

// user:“在聊天区，如果我想拖动东西，会直接变成选中文字。在编辑台应该禁用选中文字，专注组件的交互”+
// (编辑模式期间给 html 挂 studio-editing，全局禁用文本选择；关闭编辑模式或退出编辑器立即移除。)
watch(editMode, (locked) => {
  if (typeof document === 'undefined') return
  document.documentElement.classList.toggle('studio-editing', locked)
}, { immediate: true })

function restoreDraftFromStorage(): void {
  let raw: string | null = null
  try {
    raw = globalThis.localStorage?.getItem(THEME_STUDIO_DRAFT_STORAGE_KEY) ?? null
  } catch {
    return
  }
  if (!raw) return
  try {
    const migrated = migrateStudioDocument(JSON.parse(raw))
    if (migrated.ok && validateStudioDocument(migrated.document).ok) {
      store.replaceDraft(migrated.document)
      return
    }
  } catch {
    /* 坏草稿直接丢弃 */
  }
  clearDraftStorage()
}
const selectedId = ref<string | null>(null)
const extraIds = ref<string[]>([])
const extraRects = ref<Array<{ left: number; top: number; width: number; height: number }>>([])
const dragHint = ref('')
const instanceKey = ref<string | null>(null)
const instanceElement = ref<HTMLElement | null>(null)
const selectedIds = computed(() => [selectedId.value, ...extraIds.value].filter((id): id is string => Boolean(id)))
const outlineEl = ref<HTMLElement | null>(null)
const guideXEl = ref<HTMLElement | null>(null)
const guideYEl = ref<HTMLElement | null>(null)
const importEl = ref<HTMLInputElement | null>(null)

// user:“按这个设计方案审…补齐”+(方案 §3.3/§3.4：悬停细框、父容器青绿轮廓、父子中心虚线、模板紫框与实例虚线)
interface Rect { top: number; left: number; width: number; height: number }
const hoverBox = ref<Rect | null>(null)
const parentBox = ref<Rect | null>(null)
const parentLink = ref<{ x1: number; y1: number; x2: number; y2: number } | null>(null)
const templateSampleBox = ref<Rect | null>(null)
const templateSiblingBoxes = ref<Rect[]>([])
// user:“为什么没有拉伸拖拽功能……我想把它缩小一下”+
// (选中可调尺寸的元素时显示八个边界手柄；拖动实时预览，松手才写进当前作用域。)
const resizeBox = ref<Rect | null>(null)
// user:“点任意同级项间的标记，实际编辑的是父级列表 gap；滚轮 ±1、Shift ±8、双击输入”+
// (方案 §5.2 的间距胶囊：悬在选中元素旁边，改的是父级容器的行距，所有同级一起变)
const gapPillPos = ref<{ left: number; top: number } | null>(null)
const gapEditing = ref(false)
const gapInputEl = ref<HTMLInputElement | null>(null)
const spacingTarget = computed<{ parentId: string; gap: number } | null>(() => {
  if (!editMode.value || !overlaysVisible.value || !selectedId.value) return null
  const element = targetElement()
  const parentEl = element?.parentElement ?? null
  const parentId = registeredIdOf(parentEl)
  if (!parentId) return null
  const entry = UI_REGISTRY.find((item) => item.id === parentId)
  if (!entry?.properties.includes('spacing')) return null
  const parentStyle = styleAt(parentId)
  return { parentId, gap: Math.max(0, Math.round(parentStyle.spacing?.gap ?? 0)) }
})
const RESIZE_DIRS = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'] as const
type ResizeDir = typeof RESIZE_DIRS[number]

interface ResizeState {
  id: string
  el: HTMLElement
  dir: ResizeDir
  startX: number
  startY: number
  startW: number
  startH: number
  width: number
  height: number
}
let resizeState: ResizeState | null = null

function onResizePointerDown(dir: ResizeDir, event: PointerEvent): void {
  if (!editMode.value || !selectedId.value) return
  const el = targetElement()
  if (!el || !allowsId(selectedId.value, 'size')) return
  event.preventDefault()
  event.stopPropagation()
  const rect = el.getBoundingClientRect()
  resizeState = {
    id: selectedId.value,
    el,
    dir,
    startX: event.clientX,
    startY: event.clientY,
    startW: rect.width,
    startH: rect.height,
    width: rect.width,
    height: rect.height,
  }
  window.addEventListener('pointermove', onResizePointerMove)
  window.addEventListener('pointerup', onResizePointerUp, { once: true })
  window.addEventListener('pointercancel', abortResize, { once: true })
}

function onResizePointerMove(event: PointerEvent): void {
  const state = resizeState
  if (!state) return
  const dx = event.clientX - state.startX
  const dy = event.clientY - state.startY
  let width = state.startW
  let height = state.startH
  if (state.dir.includes('e')) width = state.startW + dx
  if (state.dir.includes('w')) width = state.startW - dx
  if (state.dir.includes('s')) height = state.startH + dy
  if (state.dir.includes('n')) height = state.startH - dy
  width = Math.max(8, width)
  height = Math.max(8, height)
  // user:“桌面壳作为底层容器 不应该有任何容器能够超出它”+(拉尺寸最远到外壳右/下边)
  const shell = shellRect()
  if (shell) {
    const rect = state.el.getBoundingClientRect()
    width = Math.min(width, Math.max(8, shell.right - rect.left))
    height = Math.min(height, Math.max(8, shell.bottom - rect.top))
  }
  state.width = width
  state.height = height
  state.el.style.width = `${Math.round(width)}px`
  state.el.style.height = `${Math.round(height)}px`
  void nextTick(() => syncOutline())
}

function onResizePointerUp(): void {
  window.removeEventListener('pointermove', onResizePointerMove)
  window.removeEventListener('pointercancel', abortResize)
  const state = resizeState
  resizeState = null
  if (!state) return
  state.el.style.width = ''
  state.el.style.height = ''
  const axisWidth = state.dir.includes('e') || state.dir.includes('w')
  const axisHeight = state.dir.includes('n') || state.dir.includes('s')
  // user:“把布局规则变量给统一”+
  // (外壳级容器改尺寸=改变量：会话抽屉宽度一变，主区域/输入栏的 left/right 自动跟随。)
  const mapping = LAYOUT_SIZE_VARIABLES[state.id]
  if (mapping) {
    if (mapping.axis === 'width' && axisWidth) store.setVariable(mapping.variable, `${Math.round(state.width)}px`)
    if (mapping.axis === 'height' && axisHeight) store.setVariable(mapping.variable, `${Math.round(state.height)}px`)
    const style = styleAt(state.id)
    if (style.size?.[mapping.axis]) {
      // 清掉元素级同轴尺寸，避免它压过布局变量。
      const size = { ...style.size }
      delete size[mapping.axis]
      writeStyle(state.id, { ...style, size })
    }
    if (scope.value !== 'base' && scope.value !== 'instance') refreshPreview()
    void nextTick(() => {
      syncOutline()
      growParentToFit()
      clampChildrenToParent()
    })
    return
  }
  const style = styleAt(state.id)
  const nextStyle: StudioNodeStyle = { ...style }
  if (axisWidth) {
    nextStyle.size = {
      ...(style.size || {}),
      // 流式内容容器：填满所在屏 + 上限（主区/分屏变窄时自动跟随）。
      width: isFlowWidth(state.id)
        ? { mode: 'fill', max: Math.round(state.width) }
        : { mode: 'fixed', value: Math.round(state.width) },
    }
  }
  if (axisHeight) {
    if (isFlowItem(state.id)) {
      // user:“它应该是相对原版做了什么调整……比如 X+1 Y-2”+
      // (变长列表的高度调整存增量：在每项实际高度后叠加 N，绝不写绝对高度)
      nextStyle.spacing = {
        ...(style.spacing || {}),
        blockExtra: Math.round((style.spacing?.blockExtra || 0) + (state.height - state.startH)),
      }
    } else {
      nextStyle.size = { ...(nextStyle.size || {}), height: { mode: 'fixed', value: Math.round(state.height) } }
    }
  }
  writeStyle(state.id, nextStyle)
  if (scope.value !== 'base' && scope.value !== 'instance') refreshPreview()
  void nextTick(() => {
    syncOutline()
    growParentToFit()
    clampChildrenToParent()
  })
}

function abortResize(): void {
  window.removeEventListener('pointermove', onResizePointerMove)
  const state = resizeState
  resizeState = null
  if (state) {
    state.el.style.width = ''
    state.el.style.height = ''
  }
  void nextTick(() => syncOutline())
}

function rectStyle(rect: Rect): Record<string, string> {
  return { top: `${rect.top}px`, left: `${rect.left}px`, width: `${rect.width}px`, height: `${rect.height}px` }
}

/**
 * user:“桌面壳作为底层容器 不应该有任何容器能够超出它”+
 * (shell.root 是最终边界：拖动、拉尺寸、父级撑大、锚点与位移输入都以它兜底。)
 */
function shellRect(): DOMRect | null {
  const shell = document.querySelector<HTMLElement>('[data-ui-id="shell.root"]')
  if (!shell) return null
  const rect = shell.getBoundingClientRect()
  return rect.width > 0 && rect.height > 0 ? rect : null
}

/** 拖动提交前把位移夹回外壳范围（rect 已包含本次拖动的 translate）。 */
function clampOffsetToShell(el: HTMLElement, offset: Offset): Offset {
  const shell = shellRect()
  if (!shell) return offset
  const rect = el.getBoundingClientRect()
  if (rect.width <= 0 || rect.height <= 0) return offset
  let x = offset.x
  let y = offset.y
  if (rect.left < shell.left) x += shell.left - rect.left
  else if (rect.right > shell.right) x -= rect.right - shell.right
  if (rect.top < shell.top) y += shell.top - rect.top
  else if (rect.bottom > shell.bottom) y -= rect.bottom - shell.bottom
  return { x: Math.round(x), y: Math.round(y) }
}

function onPointerHover(event: MouseEvent): void {
  if (!editMode.value || !overlaysVisible.value) {
    hoverBox.value = null
    return
  }
  const target = (event.target as Element | null)?.closest<HTMLElement>('[data-ui-id], [data-ui-template]')
  if (!target) {
    hoverBox.value = null
    return
  }
  const id = target.dataset.uiId || target.dataset.uiTemplate || ''
  if (!id || id === selectedId.value) {
    hoverBox.value = null
    return
  }
  if (isEditorLocked(id)) {
    hoverBox.value = null
    return
  }
  const rect = target.getBoundingClientRect()
  hoverBox.value = { top: rect.top, left: rect.left, width: rect.width, height: rect.height }
}

interface TreeEntry extends UiRegistryEntry {
  depth: number
}

const flatEntries = computed<TreeEntry[]>(() => {
  const byParent = new Map<string | undefined, UiRegistryEntry[]>()
  for (const entry of UI_REGISTRY) {
    const list = byParent.get(entry.parent) || []
    list.push(entry)
    byParent.set(entry.parent, list)
  }
  const rows: TreeEntry[] = []
  const walk = (parent: string | undefined, depth: number) => {
    for (const entry of byParent.get(parent) || []) {
      rows.push({ ...entry, depth })
      walk(entry.id, depth + 1)
    }
  }
  walk(undefined, 0)
  return rows
})

// user:“按这个设计方案审…补齐”+(方案 §3.1：图层树搜索过滤 + 分组折叠；搜索时忽略折叠状态)
const treeQuery = ref('')
const collapsedGroups = ref<Set<string>>(new Set())
// user:“父子是父子，层级是层级”+(左侧两个视图：元素=父子结构树；图层=按 z 排序的层列表)
const layerView = ref<'elements' | 'layers'>('elements')
let draggingLayerId: string | null = null

// user:“怎么可能有一个东西它是没有层级的呢”+
// (每个元素都有层：显式 z 是绝对分层；z:auto 是相对分层——在其层叠上下文里按文档顺序绘制。
//  面板把两者分开表达：显式层显示数字，auto 层显示文档顺序序号。)
const domVersion = ref(0)

function elementForEntry(id: string): HTMLElement | null {
  const kind = UI_REGISTRY.find((entry) => entry.id === id)?.kind
  const attribute = kind === 'template' ? 'data-ui-template' : 'data-ui-id'
  return document.querySelector<HTMLElement>(`[${attribute}="${id}"]`)
}

function documentOrderOf(id: string, element: HTMLElement | null): number {
  if (!element) return 0
  const all = [...document.querySelectorAll<HTMLElement>('[data-ui-id], [data-ui-template]')]
  const index = all.indexOf(element)
  return index >= 0 ? index + 1 : 0
}

function effectiveLayer(id: string): { z: number | null; auto: boolean; order: number; band: number; containerId: string | null; containerLabel: string | null; parentZ: number | null; parentAuto: boolean } {
  const override = styleAt(id).layer
  if (override !== undefined && Number.isFinite(override)) {
    const z = Math.round(override)
    return { z, auto: false, order: 0, band: Math.max(1, Math.ceil(z / 100)), containerId: null, containerLabel: null, parentZ: null, parentAuto: false }
  }
  const element = elementForEntry(id)
  if (!element) return { z: null, auto: true, order: 0, band: 1, containerId: null, containerLabel: null, parentZ: null, parentAuto: false }
  const computed = Number.parseInt(getComputedStyle(element).zIndex, 10)
  if (Number.isFinite(computed)) {
    return { z: computed, auto: false, order: 0, band: Math.max(1, Math.ceil(computed / 100)), containerId: null, containerLabel: null, parentZ: null, parentAuto: false }
  }
  // user:“auto不要单开，挂在对应的图层内，层级写为 auto12345 层”+
  // (z:auto=父层块里的自动子层：归到父层所在的层带，不再单独成组)
  const context = autoContextOf(element)
  const band = context.z !== null ? Math.max(1, Math.ceil(context.z / 100)) : 1
  return {
    z: null,
    auto: true,
    order: documentOrderOf(id, element),
    band,
    containerId: context.id,
    containerLabel: context.label,
    parentZ: context.z,
    parentAuto: context.z === null,
  }
}

/**
 * user:“有没有可能它的父层级是固定的？”+
 * (父容器若已有固定 z / 形成层叠上下文，auto 子元素永远被约束在父层这一块里；
 *  自动层的“块”= 最近的已登记父容器，连同父层自身的 z 一起展示。)
 */
function autoContextOf(element: HTMLElement): { id: string | null; label: string | null; z: number | null } {
  const parent = element.parentElement?.closest<HTMLElement>('[data-ui-id], [data-ui-template]')
  if (!parent) return { id: null, label: null, z: null }
  const parentId = parent.dataset.uiId || parent.dataset.uiTemplate || ''
  if (!parentId) return { id: null, label: null, z: null }
  const entry = UI_REGISTRY.find((item) => item.id === parentId)
  const label = entry ? entry.label : parentId
  const override = styleAt(parentId).layer
  if (override !== undefined && Number.isFinite(override)) return { id: parentId, label, z: Math.round(override) }
  const computed = Number.parseInt(getComputedStyle(parent).zIndex, 10)
  return { id: parentId, label, z: Number.isFinite(computed) ? computed : null }
}

function autoLayerMeta(row: { containerLabel: string | null; parentZ: number | null; parentAuto: boolean }): string {
  if (!row.containerLabel) return ''
  const container = t('在「{0}」内', { 0: t(row.containerLabel) })
  const parent = row.parentAuto ? t('父层自动') : t('父层 z={0}', { 0: row.parentZ })
  return `${container} · ${parent}`
}

function layerValueText(row: { z: number | null; auto: boolean; order: number }): string {
  if (!row.auto) return row.z === null ? '' : String(row.z)
  // user:“层级写为 auto12345 层”+(auto 子层的层级列直接写 auto+顺序号)
  return row.order > 0 ? `auto${row.order}` : 'auto'
}

function updateLayerValue(id: string, event: Event): void {
  const input = event.target as HTMLInputElement
  const raw = input.value.trim()
  // user:“auto不要单开，挂在对应的图层内”+(输入 auto 或清空=撤销覆盖，回到相对分层)
  if (raw === '' || /^auto/i.test(raw)) {
    const style = styleAt(id)
    if (style.layer !== undefined) {
      const next = { ...style }
      delete next.layer
      writeStyle(id, next)
    }
    // 没有写入时也让输入框回到真实的相对层级，不留半截文本。
    input.value = layerValueText(effectiveLayer(id))
    return
  }
  const value = Number.parseInt(raw, 10)
  if (!Number.isFinite(value)) {
    input.value = layerValueText(effectiveLayer(id))
    return
  }
  writeStyle(id, { ...styleAt(id), layer: Math.min(9999, Math.max(0, Math.round(value))) })
  if (scope.value !== 'base' && scope.value !== 'instance') refreshPreview()
}

function onLayerDragStart(id: string): void {
  draggingLayerId = id
}

function onLayerDrop(targetId: string): void {
  const dragged = draggingLayerId
  draggingLayerId = null
  if (!dragged || dragged === targetId) return
  // 放到目标之上：z = 目标 z + 1（层内留位，跨层也能落到上一段起点）。
  // 目标是 auto 子层时没有自己的 z，落在它所属层带的父层之上，避免跳回第 1 层。
  const target = effectiveLayer(targetId)
  const baseZ = target.z ?? target.parentZ ?? (target.band - 1) * 100 + 1
  updateLayerValue(dragged, { target: { value: String(Math.min(9999, baseZ + 1)) } } as unknown as Event)
}

const layerRows = computed(() => {
  void domVersion.value
  const query = treeQuery.value.trim().toLowerCase()
  const rows = UI_REGISTRY
    .filter((entry) => !query || entry.label.toLowerCase().includes(query) || entry.id.toLowerCase().includes(query))
    .map((entry) => ({
      id: entry.id,
      label: entry.label,
      ...effectiveLayer(entry.id),
    }))
    .sort((left, right) => {
      // user:“auto不要单开，挂在对应的图层内”+
      // (先按层带从高到低；同一带内显式层在前、auto 子层随后，各自按 z / 文档顺序从后往前)
      if (left.band !== right.band) return right.band - left.band
      if (left.auto !== right.auto) return left.auto ? 1 : -1
      if (left.z !== null && right.z !== null) return right.z - left.z || left.id.localeCompare(right.id)
      return right.order - left.order || left.id.localeCompare(right.id)
    })

  // user:“比如说会话行和消息行……它是 auto 在哪儿的？……那就再细分一层，把它挂在那个会话抽屉底下”+
  // (同一层带里，auto 行挂到它最近的已登记父容器行下面，形成真实的嵌套；
  //  父容器自己也在同一层带时才嵌套，跨层带或找不到父容器时留在带内顶层。)
  type BaseRow = (typeof rows)[number]
  const byId = new Map(rows.map((row) => [row.id, row]))
  const childrenOf = new Map<string, BaseRow[]>()
  const roots: BaseRow[] = []
  for (const row of rows) {
    const parent = row.auto && row.containerId ? byId.get(row.containerId) : undefined
    if (parent && parent.id !== row.id && parent.band === row.band) {
      const list = childrenOf.get(parent.id) || []
      list.push(row)
      childrenOf.set(parent.id, list)
    } else {
      roots.push(row)
    }
  }
  const placed = new Set(roots.map((row) => row.id))
  for (const list of childrenOf.values()) for (const row of list) placed.add(row.id)

  const flat: Array<BaseRow & { depth: number; bandHeader: boolean; hasAutoChildren: boolean }> = []
  const emitted = new Set<string>()
  let previousBand: number | null = null
  const pushRow = (row: BaseRow, depth: number): void => {
    if (emitted.has(row.id)) return
    emitted.add(row.id)
    const bandHeader = row.band !== previousBand
    previousBand = row.band
    const children = childrenOf.get(row.id)
    flat.push({ ...row, depth, bandHeader, hasAutoChildren: Boolean(children?.length) })
    // user:“图层可折叠”+(每块自动子层也能单独收起)
    if (children && !collapsedAuto.value.has(row.id)) {
      for (const child of children) pushRow(child, depth + 1)
    }
  }
  for (const root of roots) pushRow(root, 0)
  // 搜索把父容器过滤掉、或异常数据没有落点时，剩余行仍要显示出来。
  for (const row of rows) if (!placed.has(row.id)) pushRow(row, 0)

  // user:“图层可折叠”+(收起后只留层带标题，展开恢复该层的全部行)
  return flat.filter((row) => row.bandHeader || !collapsedBands.value.has(row.band))
})

watch(layerView, (view) => {
  if (view === 'layers') void nextTick(() => { domVersion.value += 1 })
})

function hasChildren(id: string): boolean {
  return UI_REGISTRY.some((entry) => entry.parent === id)
}

function toggleCollapse(id: string): void {
  const next = new Set(collapsedGroups.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  collapsedGroups.value = next
}

// user:“图层可折叠”+(每个 z 层带可单独收起/展开，状态在本次编辑内保持)
const collapsedBands = ref<Set<number>>(new Set())
// user:“那就再细分一层，把它挂在那个会话抽屉底下”+(父容器下的自动子层也能整体收起)
const collapsedAuto = ref<Set<string>>(new Set())

function toggleAutoGroup(id: string): void {
  const next = new Set(collapsedAuto.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  collapsedAuto.value = next
}

function toggleBand(band: number): void {
  const next = new Set(collapsedBands.value)
  if (next.has(band)) next.delete(band)
  else next.add(band)
  collapsedBands.value = next
}

const visibleEntries = computed<TreeEntry[]>(() => {
  const query = treeQuery.value.trim().toLowerCase()
  if (query) {
    return flatEntries.value.filter((entry) =>
      entry.label.toLowerCase().includes(query) || entry.id.toLowerCase().includes(query))
  }
  return flatEntries.value.filter((entry) => {
    let parent = entry.parent
    while (parent) {
      if (collapsedGroups.value.has(parent)) return false
      parent = UI_REGISTRY.find((item) => item.id === parent)?.parent
    }
    return true
  })
})

const selectedEntry = computed(() => UI_REGISTRY.find((entry) => entry.id === selectedId.value) || null)
const scope = ref<'base' | string>('base')
const selectedIsTemplate = computed(() => selectedEntry.value?.kind === 'template')

const draftNode = computed<StudioNodeStyle>(() => {
  if (!selectedId.value) return {}
  if (scope.value === 'instance' && instanceKey.value) {
    // 这一条还没单独改过时，面板显示它从模板继承来的值；第一次改动才落到这一条上。
    return store.draft.value.instances?.[instanceKey.value]?.style
      || store.draft.value.templates?.[selectedId.value]
      || {}
  }
  if (scope.value !== 'base') {
    const breakpoint = store.draft.value.breakpoints.find((item) => item.id === scope.value)
    return breakpoint?.nodes[selectedId.value] || {}
  }
  if (selectedIsTemplate.value) return store.draft.value.templates?.[selectedId.value] || {}
  return store.draft.value.nodes[selectedId.value] || {}
})

const activeBackground = computed(() => draftNode.value.background)
// 素材层是否存在只看引用本身：底色和图片是两层，各自独立，互不覆盖。
const hasAsset = computed(() => Boolean(activeBackground.value?.assetRef))
// user:“如果成功添加图片之后，该按钮应换成图片的小号预览”+(缩略图取已导入素材的 data URL)
const assetPreviewUrl = computed(() => {
  const assetRef = hasAsset.value ? activeBackground.value?.assetRef : undefined
  return assetRef ? assetUrls.value[assetRef] || null : null
})
const assetFit = computed(() => activeBackground.value?.fit ?? 'cover')
const assetOverflow = computed(() => activeBackground.value?.overflow ?? 'clipped')
const backgroundColor = computed(() => {
  // 底色在任何背景类型下都保留（图片背景时它铺在图片下面）。
  return draftNode.value.background?.color || '#242424'
})
// 背景颜色来源：'' = 自定义色盘，其余为白名单令牌（透明/主区域/侧栏/输入区/控件）。
const COLOR_TOKEN_OPTIONS: Array<{ value: StudioColorToken; label: string }> = [
  { value: 'transparent', label: '透明' },
  { value: 'main-background', label: '主区域底色' },
  { value: 'main-soft-background', label: '主区域柔和底色' },
  { value: 'backdrop-background', label: '应用底色' },
  { value: 'composer-background', label: '输入区底色' },
  { value: 'control-background', label: '控件底色' },
]
const backgroundToken = computed(() => draftNode.value.background?.colorToken ?? '')

function updateBackgroundToken(event: Event): void {
  const token = (event.target as HTMLSelectElement).value
  const current: StudioBackground = draftNode.value.background ?? { type: 'solid' }
  // 令牌优先于自定义色（编译层保证），所以切换令牌不动多余字段：
  // 切回“自定义颜色”时之前选的色还在，不会丢。
  const next = { ...current, colorToken: token ? (token as StudioColorToken) : undefined }
  patch({ background: { ...next, type: current.assetRef ? 'asset' : 'solid' } })
}
const draftGap = computed(() => draftNode.value.spacing?.gap ?? 0)
const draftFontSize = computed(() => draftNode.value.text?.size ?? 13)
const draftLayer = computed(() => draftNode.value.layer ?? 0)
const draftVisibility = computed(() => draftNode.value.visibility !== false)

interface DragState {
  id: string
  el: HTMLElement
  startX: number
  startY: number
  base: Offset
  box: { left: number; top: number; width: number; height: number }
  moved: boolean
}

let dragState: DragState | null = null
let dragOffset: Offset | null = null

function offsetOf(axis: 'x' | 'y'): number {
  return draftNode.value.offset?.[axis] ?? 0
}

function allowsId(id: string, property: string): boolean {
  const entry = UI_REGISTRY.find((item) => item.id === id)
  return Boolean(entry?.properties.includes(property as never))
}

function protectionLabel(level: UiProtectionLevel): string {
  if (level === 'protected') return t('受保护')
  if (level === 'appearance-only') return t('仅外观')
  return t('可编辑')
}

function allows(property: string): boolean {
  return Boolean(selectedEntry.value?.properties.includes(property as never))
}

function styleOf<K extends keyof StudioNodeStyle>(key: K, fallback: string | number): string | number {
  const value = draftNode.value[key]
  return (value as string | number | undefined) ?? fallback
}

function numberOf(key: keyof StudioNodeStyle, fallback: number): number {
  const value = draftNode.value[key]
  return typeof value === 'number' ? value : fallback
}

function percent(value: string | number): string {
  return `${Math.round(Number(value) * 100)}%`
}

// —— 边锚点（方案 §4.4）：相对父容器某条边的距离，兜底距离非负 ——
const ANCHOR_AXIS_EDGES = {
  h: ['left', 'right', 'centerX'],
  v: ['top', 'bottom', 'centerY'],
} as const

function anchorOf(axis: 'h' | 'v'): StudioNodeAnchor | undefined {
  const anchors = draftNode.value.anchors || []
  return anchors.find((anchor) => (ANCHOR_AXIS_EDGES[axis] as readonly string[]).includes(anchor.edge))
}

function updateAnchorEdge(axis: 'h' | 'v', event: Event): void {
  const edge = (event.target as HTMLSelectElement).value as StudioAnchorEdge | ''
  const existing = anchorOf(axis)
  const rest = (draftNode.value.anchors || []).filter((anchor) => !(ANCHOR_AXIS_EDGES[axis] as readonly string[]).includes(anchor.edge))
  const anchors = edge
    ? [...rest, { target: 'parent' as const, edge: edge as StudioAnchorEdge, offset: existing?.offset ?? 0 }]
    : rest
  patch({ anchors: anchors.length > 0 ? anchors : undefined })
  pullSelectedInsideShell()
}

function updateAnchorOffset(axis: 'h' | 'v', event: Event): void {
  const raw = Number((event.target as HTMLInputElement).value)
  if (!Number.isFinite(raw)) return
  const value = Math.max(0, Math.round(raw))
  const existing = anchorOf(axis)
  if (!existing) return
  patch({ anchors: (draftNode.value.anchors || []).map((anchor) => (anchor === existing ? { ...anchor, offset: value } : anchor)) })
  pullSelectedInsideShell()
}

// —— 画布间距胶囊（方案 §5.2）：编辑父级行距，滚轮 ±1、Shift ±8、双击输入 ——
function parentGapMode(parentEl: HTMLElement | null): 'gap' | 'margin' {
  const display = parentEl ? getComputedStyle(parentEl).display : ''
  return display === 'flex' || display === 'inline-flex' || display === 'grid' || display === 'inline-grid'
    ? 'gap'
    : 'margin'
}

function writeParentGap(value: number): void {
  const target = spacingTarget.value
  if (!target) return
  const style = styleAt(target.parentId)
  const parentEl = targetElement()?.parentElement ?? null
  writeStyle(target.parentId, {
    ...style,
    spacing: {
      ...(style.spacing || {}),
      gap: Math.max(0, Math.round(value)),
      mode: style.spacing?.mode ?? parentGapMode(parentEl),
    },
  })
  if (scope.value !== 'base' && scope.value !== 'instance') refreshPreview()
}

function onGapWheel(event: WheelEvent): void {
  const step = event.shiftKey ? 8 : 1
  writeParentGap((spacingTarget.value?.gap ?? 0) + (event.deltaY < 0 ? step : -step))
}

function startGapEditing(): void {
  gapEditing.value = true
  void nextTick(() => {
    gapInputEl.value?.focus()
    gapInputEl.value?.select()
  })
}

function commitGapInput(event: Event): void {
  const value = Number((event.target as HTMLInputElement).value)
  gapEditing.value = false
  if (Number.isFinite(value)) writeParentGap(value)
}

function select(id: string, additive = false): void {
  if (!additive) {
    extraIds.value = []
    // user:“写好清单，逐项打勾”+(退回基础样式，别让作用域停在一个已经没有目标的实例上)
    if (scope.value === 'instance') scope.value = 'base'
    instanceKey.value = null
    instanceElement.value = null
    selectedId.value = id
  } else if (selectedId.value === id) {
    const next = extraIds.value.shift()
    if (next) selectedId.value = next
  } else if (extraIds.value.includes(id)) {
    extraIds.value = extraIds.value.filter((item) => item !== id)
  } else {
    extraIds.value.push(id)
  }
  void nextTick(() => syncOutline())
}

function selectInstance(host: HTMLElement): boolean {
  const key = host.dataset.uiInstance || ''
  const templateId = host.dataset.uiTemplate || ''
  if (!key || !templateId) return false
  // user:“我编辑了一个会话行，所有的会话行都会被应用成一样的东西”+
  // (默认作用域是样式类型/模板：点任意一条改的是全部同类；要改单条再从下拉显式切“此实例”。)
  extraIds.value = []
  instanceKey.value = key
  instanceElement.value = host
  selectedId.value = templateId
  scope.value = 'base'
  return true
}

function allowPosition(id: string): boolean {
  return allowsId(id, 'position')
}

function elementOf(id: string): HTMLElement | null {
  const template = UI_REGISTRY.find((entry) => entry.id === id)?.kind === 'template'
  const attribute = template ? 'data-ui-template' : 'data-ui-id'
  return document.querySelector<HTMLElement>(`[${attribute}="${id}"]`)
}

function applyAlign(mode: 'left' | 'centerX' | 'right' | 'top' | 'centerY' | 'bottom' | 'distributeX' | 'distributeY'): void {
  // user:“写好清单，逐项打勾”+(实例一次只有一个目标，没有对齐基准，这里直接不写，避免误改基础样式)
  if (scope.value === 'instance') return
  const ids = selectedIds.value.filter(allowPosition)
  if (ids.length < 2) return
  const boxes = ids.map((id) => {
    const element = elementOf(id)
    const rect = element?.getBoundingClientRect()
    return rect ? { left: rect.left, top: rect.top, width: rect.width, height: rect.height } : null
  })
  if (boxes.some((box) => !box)) return
  const deltas = mode === 'distributeX' || mode === 'distributeY'
    ? distributeDeltas(boxes as never, mode === 'distributeX' ? 'x' : 'y')
    : alignDeltas(boxes as never, mode)
  ids.forEach((id, index) => {
    const delta = deltas[index]
    if (!delta || (delta.x === 0 && delta.y === 0)) return
    const style = styleAt(id)
    const current = style.offset || { x: 0, y: 0 }
    writeStyle(id, { ...style, offset: { x: current.x + delta.x, y: current.y + delta.y } })
  })
  if (scope.value !== 'base') refreshPreview()
  void nextTick(() => syncOutline())
}

/** 按当前作用域取目标样式：基础写节点或模板，窄屏写断点，实例只取这一条。 */
function styleAt(id: string): StudioNodeStyle {
  if (scope.value === 'instance') {
    const entry = instanceKey.value ? store.draft.value.instances?.[instanceKey.value] : undefined
    if (entry) return entry.style
    return store.draft.value.templates?.[id] || {}
  }
  if (scope.value !== 'base') {
    const breakpoint = store.draft.value.breakpoints.find((item) => item.id === scope.value)
    return breakpoint?.nodes[id] || {}
  }
  const template = UI_REGISTRY.find((entry) => entry.id === id)?.kind === 'template'
  return template ? store.draft.value.templates?.[id] || {} : store.draft.value.nodes[id] || {}
}

/** 按当前作用域写目标样式；实例作用域只写这一条，模板保持原样。 */
function writeStyle(id: string, style: StudioNodeStyle): void {
  const template = UI_REGISTRY.find((entry) => entry.id === id)?.kind === 'template'
  if (scope.value === 'instance') {
    // user:“模板之上允许单个实例覆盖”+(实例只写这一条，模板保持原样)
    if (instanceKey.value && template) store.setInstanceNode(instanceKey.value, id, style)
    return
  }
  if (scope.value !== 'base') {
    store.setBreakpointNode(scope.value, id, style)
    return
  }
  if (template) store.setTemplateNode(id, style)
  else store.setNode(id, style)
}

function patch(patchValue: StudioNodeStyle): void {
  if (!selectedId.value) return
  writeStyle(selectedId.value, { ...draftNode.value, ...patchValue })
  if (scope.value !== 'base') refreshPreview()
  // 尺寸/间距等改动会移动元素，选框与父容器轮廓跟着刷新。
  void nextTick(() => {
    syncOutline()
    domVersion.value += 1
  })
}

/** 断点编辑时把该断点的覆盖合进基础样式，能立刻看到窄屏效果。 */
function refreshPreview(): void {
  if (scope.value === 'base' || scope.value === 'instance') {
    store.preview()
    return
  }
  const breakpoint = store.draft.value.breakpoints.find((item) => item.id === scope.value)
  if (!breakpoint) {
    store.preview()
    return
  }
  store.previewDocument({
    ...store.draft.value,
    nodes: { ...store.draft.value.nodes, ...breakpoint.nodes },
    breakpoints: [],
  })
}

function setScope(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  if (value === 'instance' && !instanceKey.value) return
  scope.value = value === 'instance' ? 'instance' : value
  // user:“写好清单，逐项打勾”+(离开实例作用域就把实例标识一起清掉，别让下拉停在空目标上)
  if (scope.value !== 'instance') {
    instanceKey.value = null
    instanceElement.value = null
  }
  refreshPreview()
}

function addBreakpoint(): void {
  const width = Math.max(360, Math.round(window.innerWidth))
  const id = `bp-${width}`
  store.addBreakpoint(id, width)
  scope.value = id
  refreshPreview()
}

function removeBreakpoint(): void {
  if (scope.value === 'base') return
  store.removeBreakpoint(scope.value)
  scope.value = 'base'
  refreshPreview()
}

function updateColor(key: 'color', event: Event): void {
  patch({ [key]: (event.target as HTMLInputElement).value } as StudioNodeStyle)
}

function updateBackground(event: Event): void {
  const value = (event.target as HTMLInputElement).value
  const current = draftNode.value.background
  // user:“图片和颜色应该有优先级……”+(颜色是图片下面的底：有图时换色只换底，不把图片弄丢；
  //  显式选色同时清掉渐变与令牌——这是“单独设置”的意思。)
  const next = { ...(current || {}), color: value, colorToken: undefined, stops: undefined, angle: undefined }
  patch({ background: { ...next, type: current?.assetRef ? 'asset' : 'solid' } })
}

// user:“按这个设计方案审…补齐”+(方案 §8.1：背景自身透明度，与组件整体透明度分开)
const backgroundOpacity = computed(() => draftNode.value.background?.opacity ?? 1)

function updateBackgroundOpacity(event: Event): void {
  const current = draftNode.value.background || { type: 'solid' as const, color: backgroundColor.value }
  patch({ background: { ...current, opacity: Number((event.target as HTMLInputElement).value) } })
}

function updateNumber(key: 'opacity' | 'radius' | 'layer', event: Event): void {
  patch({ [key]: Number((event.target as HTMLInputElement).value) } as StudioNodeStyle)
}

function updateGap(event: Event): void {
  const value = Number((event.target as HTMLInputElement).value)
  // user:“那个间距是干啥的？为什么我调了半天也没有反应呢？”+
  // (gap 只对 flex/grid 生效；块级容器改走子项外边距，保证调了就有变化。)
  const element = targetElement()
  const display = element ? getComputedStyle(element).display : ''
  const mode: 'gap' | 'margin' = display === 'flex' || display === 'inline-flex'
    || display === 'grid' || display === 'inline-grid'
    ? 'gap'
    : 'margin'
  patch({ spacing: { ...(draftNode.value.spacing || {}), gap: value, mode } })
}

// —— 尺寸模式编辑（方案 §4.3）：宽/高各自 fill/hug/固定 + 最小/最大 ——
// user:“把布局规则变量给统一……不要再有写死的值和无法被改变的值”+
// (外壳级尺寸全部落成布局变量：改抽屉宽度=改变量，主区域等派生位置自动跟随。)
const LAYOUT_SIZE_VARIABLES: Record<string, { variable: string; axis: 'width' | 'height' }> = {
  'shell.app-rail': { variable: '--layout-rail-width', axis: 'width' },
  'shell.left-drawer': { variable: '--layout-sidebar-width', axis: 'width' },
  'shell.right-drawer': { variable: '--layout-right-drawer-width', axis: 'width' },
  'shell.titlebar': { variable: '--layout-titlebar-height', axis: 'height' },
  // user:“我认为主区和分屏本质是一个容器”+(分屏主面板宽度写内容区变量，主区/输入栏一起跟随)
  'shell.split': { variable: '--layout-split-primary-width', axis: 'width' },
}

function layoutVariableFor(axis: 'width' | 'height'): string | null {
  if (!selectedId.value) return null
  const mapping = LAYOUT_SIZE_VARIABLES[selectedId.value]
  return mapping && mapping.axis === axis ? mapping.variable : null
}

// user:“在那些长度不等的容器里面，用绝对数值相加，而不是统一数值，比如说会话消息流”+
// (消息流/会话流的子项高度各不相同：高度调整写成“最小高度”，
//  每项保留自己的实际高度，间距在各自高度上叠加，绝不把所有项压成同一个固定高度。)
const FLOW_ITEM_TEMPLATES = new Set(['template.message', 'template.conversation', 'shell.sidebar-items'])
// user:“我开分屏的时候是不是会导致界面缩小？缩小之后，如果消息流写了一个绝对数值，那肯定就超出了”+
// (消息流宽度=填满所在屏 + 上限，屏幕变窄自动跟随，绝不写死绝对宽度)
const FLOW_WIDTH_IDS = new Set([...FLOW_ITEM_TEMPLATES, 'chat.thread'])

function isFlowItem(id: string | null): boolean {
  return Boolean(id && FLOW_ITEM_TEMPLATES.has(id))
}

function isFlowWidth(id: string | null): boolean {
  return Boolean(id && FLOW_WIDTH_IDS.has(id))
}

// user:“子节点的形状体积改变应该同步。如果它超出了父节点的位置，那要把父节点也自动撑大，
//  同理，在父节点缩小的时候，也要把子节点自动缩回去”+(编辑提交后用真实测量做一次父子尺寸同步)
function registeredIdOf(element: Element | null): string | null {
  const el = element as HTMLElement | null
  const id = el?.dataset.uiId || el?.dataset.uiTemplate
  return id && UI_REGISTRY.some((entry) => entry.id === id) ? id : null
}

/**
 * user:“桌面壳作为底层容器 不应该有任何容器能够超出它”+
 * (元素已经越出 shell.root 时，按它当前使用的定位方式往回拉：
 *  有锚点的轴改锚点距离，没有锚点的轴改位移；外壳本身永远不动。)
 */
function pullInsideShell(id: string, el: HTMLElement): void {
  const shell = shellRect()
  if (!shell) return
  const rect = el.getBoundingClientRect()
  if (rect.width <= 0 || rect.height <= 0) return
  // 收起/隐藏中的面板（抽屉滑出屏幕、display:none）属于临时状态，不能按它写回主题。
  const view = getComputedStyle(el)
  if (view.visibility === 'hidden' || view.display === 'none') return
  const intersects = rect.right > shell.left && rect.left < shell.right && rect.bottom > shell.top && rect.top < shell.bottom
  if (!intersects) return
  const overLeft = Math.max(0, Math.ceil(shell.left - rect.left))
  const overRight = Math.max(0, Math.ceil(rect.right - shell.right))
  const overTop = Math.max(0, Math.ceil(shell.top - rect.top))
  const overBottom = Math.max(0, Math.ceil(rect.bottom - shell.bottom))
  if (overLeft === 0 && overRight === 0 && overTop === 0 && overBottom === 0) return

  const style = styleAt(id)
  const anchors = style.anchors || []
  const hAnchor = anchors.find((anchor) => (ANCHOR_AXIS_EDGES.h as readonly string[]).includes(anchor.edge))
  const vAnchor = anchors.find((anchor) => (ANCHOR_AXIS_EDGES.v as readonly string[]).includes(anchor.edge))
  let nextAnchors = anchors
  let nextOffset = { x: style.offset?.x ?? 0, y: style.offset?.y ?? 0 }
  let anchorsChanged = false
  let offsetChanged = false

  const move = (axis: 'h' | 'v', anchor: StudioNodeAnchor | undefined, delta: number): void => {
    if (!anchor) {
      if (axis === 'h') nextOffset.x += delta
      else nextOffset.y += delta
      offsetChanged = true
      return
    }
    // 不同边的锚点，增加距离的方向不同。
    const signed = anchor.edge === 'right' || anchor.edge === 'bottom' ? -delta : delta
    const value = Math.max(0, Math.round(anchor.offset + signed))
    if (value === anchor.offset) return
    nextAnchors = nextAnchors.map((item) => (item === anchor ? { ...item, offset: value } : item))
    anchorsChanged = true
  }

  // 正数=往右/往下推；负数=往左/往上推。
  const dx = overLeft - overRight
  const dy = overTop - overBottom
  if (dx !== 0) move('h', hAnchor, dx)
  if (dy !== 0) move('v', vAnchor, dy)
  if (!anchorsChanged && !offsetChanged) return
  writeStyle(id, {
    ...style,
    anchors: anchorsChanged ? nextAnchors : style.anchors,
    offset: offsetChanged ? { x: Math.round(nextOffset.x), y: Math.round(nextOffset.y) } : style.offset,
  })
}

function pullSelectedInsideShell(): void {
  void nextTick(() => {
    const id = selectedId.value
    const el = targetElement()
    if (id && el) pullInsideShell(id, el)
  })
}

/**
 * 子级超出父级范围时按“相对父边距离不小于 0”兜底：
 * - 右/下越界：把父级撑大（父级仍由父级自己的尺寸决定，子级贴边距离保持 ≥ 0）；
 * - 左/上越界：父级无法向左上生长，改为回夹子级位移，保证与父边距离 ≥ 0。
 * 只有编辑提交会走到这里并写文档；运行期响应式收缩不写任何值。
 */
function growParentToFit(): void {
  if (scope.value !== 'base') return
  const element = targetElement()
  const parentEl = element?.parentElement ?? null
  const parentId = registeredIdOf(parentEl)
  if (!element || !parentEl || !parentId || parentId === 'shell.root') {
    // 直接挂在桌面壳下：父级不可变，只能把元素自己拉回外壳内。
    if (element && selectedId.value) pullInsideShell(selectedId.value, element)
    return
  }
  const childRect = element.getBoundingClientRect()
  const parentRect = parentEl.getBoundingClientRect()
  if (parentRect.width <= 0 || parentRect.height <= 0) return
  const shell = shellRect()
  const overflowRight = Math.max(0, Math.ceil(childRect.right - parentRect.right))
  const overflowBottom = Math.max(0, Math.ceil(childRect.bottom - parentRect.bottom))
  const overflowLeft = Math.max(0, Math.ceil(parentRect.left - childRect.left))
  const overflowTop = Math.max(0, Math.ceil(parentRect.top - childRect.top))
  if (overflowRight === 0 && overflowBottom === 0 && overflowLeft === 0 && overflowTop === 0) return

  // user:“桌面壳作为底层容器 不应该有任何容器能够超出它”+
  // (父级最多长到外壳边缘；再超出就只能把子级拉回来。)
  const growRight = shell
    ? Math.min(overflowRight, Math.max(0, Math.floor(shell.right - parentRect.right)))
    : overflowRight
  const growBottom = shell
    ? Math.min(overflowBottom, Math.max(0, Math.floor(shell.bottom - parentRect.bottom)))
    : overflowBottom

  // 左/上越界：父级不向左上生长，回夹子级，保证距离 ≥ 0（编辑期决定，写入文档）。
  if ((overflowLeft > 0 || overflowTop > 0) && selectedId.value) {
    const style = styleAt(selectedId.value)
    const offset = style.offset || { x: 0, y: 0 }
    const x = offset.x + overflowLeft
    const y = offset.y + overflowTop
    if (x !== offset.x || y !== offset.y) {
      writeStyle(selectedId.value, { ...style, offset: { x: Math.round(x), y: Math.round(y) } })
    }
  }

  // 右/下越界：撑大父级（变量驱动的父级改变量，其余加最小尺寸）。
  if (growRight === 0 && growBottom === 0) {
    if (selectedId.value) pullInsideShell(selectedId.value, element)
    return
  }
  const mapping = LAYOUT_SIZE_VARIABLES[parentId]
  if (mapping?.axis === 'width' && growRight > 0) {
    store.setVariable(mapping.variable, `${Math.ceil(parentRect.width + growRight)}px`)
  }
  if (mapping?.axis === 'height' && growBottom > 0) {
    store.setVariable(mapping.variable, `${Math.ceil(parentRect.height + growBottom)}px`)
  }
  const parentStyle = styleAt(parentId)
  const size = { ...(parentStyle.size || {}) }
  let changed = false
  if (growRight > 0 && mapping?.axis !== 'width') {
    const base = size.width?.min ?? Math.round(parentRect.width)
    size.width = { ...(size.width || { mode: 'hug' as const }), min: base + growRight }
    changed = true
  }
  if (growBottom > 0 && mapping?.axis !== 'height') {
    const base = size.height?.min ?? Math.round(parentRect.height)
    size.height = { ...(size.height || { mode: 'hug' as const }), min: base + growBottom }
    changed = true
  }
  if (changed) writeStyle(parentId, { ...parentStyle, size })
  // 父级已经顶到外壳边缘时，剩余越界量只能回夹到子级自己。
  if ((overflowRight > growRight || overflowBottom > growBottom) && selectedId.value) {
    void nextTick(() => {
      const target = targetElement()
      if (target) pullInsideShell(selectedId.value as string, target)
    })
  }
}

/** 父级缩小后，直接子级的位移与固定尺寸回缩进父级范围。 */function clampChildrenToParent(): void {
  if (scope.value !== 'base' || !selectedId.value) return
  const parentEl = targetElement()
  if (!parentEl) return
  const parentRect = parentEl.getBoundingClientRect()
  if (parentRect.width <= 0 || parentRect.height <= 0) return
  for (const child of Array.from(parentEl.children) as HTMLElement[]) {
    const childId = registeredIdOf(child)
    if (!childId) continue
    const style = styleAt(childId)
    const rect = child.getBoundingClientRect()
    if (style.offset && (style.offset.x !== 0 || style.offset.y !== 0)) {
      const naturalLeft = rect.left - style.offset.x
      const naturalTop = rect.top - style.offset.y
      const minX = parentRect.left - naturalLeft
      const maxX = parentRect.right - (naturalLeft + rect.width)
      const minY = parentRect.top - naturalTop
      const maxY = parentRect.bottom - (naturalTop + rect.height)
      const clamp = (value: number, low: number, high: number) => Math.min(Math.max(value, Math.min(low, high)), Math.max(low, high))
      const x = clamp(style.offset.x, minX, maxX)
      const y = clamp(style.offset.y, minY, maxY)
      if (x !== style.offset.x || y !== style.offset.y) {
        writeStyle(childId, { ...style, offset: { x: Math.round(x), y: Math.round(y) } })
      }
    }
    const fixedWidth = style.size?.width
    if (fixedWidth?.mode === 'fixed' && fixedWidth.value !== undefined && fixedWidth.value > parentRect.width) {
      writeStyle(childId, { ...style, size: { ...(style.size || {}), width: { ...fixedWidth, value: Math.floor(parentRect.width) } } })
    }
    const fixedHeight = style.size?.height
    if (fixedHeight?.mode === 'fixed' && fixedHeight.value !== undefined && fixedHeight.value > parentRect.height) {
      writeStyle(childId, { ...style, size: { ...(style.size || {}), height: { ...fixedHeight, value: Math.floor(parentRect.height) } } })
    }
  }
}

function layoutVariablePx(variable: string): number | null {
  const raw = (store.draft.value.variables as Record<string, string> | undefined)?.[variable]
  if (!raw) return null
  const value = Number.parseFloat(raw)
  return Number.isFinite(value) ? value : null
}

// user:“桌面壳作为底层容器 不应该有任何容器能够超出它”+(布局变量同样不能写出超过外壳的宽/高)
function clampLayoutSize(axis: 'width' | 'height', value: number): number {
  const shell = shellRect()
  if (!shell) return Math.round(value)
  const limit = axis === 'width' ? shell.width : shell.height
  return Math.round(Math.min(value, limit))
}

function sizeDimensionOf(axis: 'width' | 'height'): StudioDimension | undefined {
  return draftNode.value.size?.[axis]
}

function sizeModeOf(axis: 'width' | 'height'): string {
  const variable = layoutVariableFor(axis)
  if (variable && layoutVariablePx(variable) !== null) return 'fixed'
  const dimension = sizeDimensionOf(axis)
  // 流式内容容器的宽度是“填满 + 上限”，面板仍用“固定值”档编辑这个上限。
  if (axis === 'width' && isFlowWidth(selectedId.value) && dimension?.mode === 'fill' && dimension.max !== undefined) {
    return 'fixed'
  }
  if (!dimension) return ''
  return dimension.mode === 'fill' || dimension.mode === 'hug' ? dimension.mode : 'fixed'
}

function sizeValueOf(axis: 'width' | 'height'): number {
  const variable = layoutVariableFor(axis)
  if (variable) {
    const px = layoutVariablePx(variable)
    if (px !== null) return px
  }
  const dimension = sizeDimensionOf(axis)
  if (axis === 'width' && isFlowWidth(selectedId.value) && dimension?.mode === 'fill') {
    return dimension.max ?? 100
  }
  return dimension?.value ?? 100
}

function sizeBoundOf(axis: 'width' | 'height', bound: 'min' | 'max'): number | undefined {
  return sizeDimensionOf(axis)?.[bound]
}

function writeSizeDimension(axis: 'width' | 'height', dimension: StudioDimension | undefined): void {
  // user:“桌面壳作为底层容器 不应该有任何容器能够超出它”+
  // (固定尺寸最多到外壳的宽/高；超出的部分由位置回夹兜底)
  const shell = shellRect()
  if (dimension?.mode === 'fixed' && dimension.value !== undefined && shell) {
    const limit = axis === 'width' ? shell.width : shell.height
    dimension = { ...dimension, value: Math.min(dimension.value, Math.floor(limit)) }
  }
  const size: { width?: StudioDimension; height?: StudioDimension } = { ...(draftNode.value.size || {}) }
  if (dimension) size[axis] = dimension
  else delete size[axis]
  patch({ size: size as StudioSize })
  pullSelectedInsideShell()
}

function updateSizeMode(axis: 'width' | 'height', event: Event): void {
  const mode = (event.target as HTMLSelectElement).value
  const variable = layoutVariableFor(axis)
  if (variable) {
    // 布局变量驱动的轴：清空=删变量；固定值=写变量；其余模式退回元素尺寸。
    if (!mode) {
      store.removeVariable(variable)
      return
    }
    if (mode === 'fixed') {
      store.setVariable(variable, `${clampLayoutSize(axis, sizeValueOf(axis) || 100)}px`)
      return
    }
    store.removeVariable(variable)
    writeSizeDimension(axis, { mode: mode as 'fill' | 'hug' })
    return
  }
  const previous = sizeDimensionOf(axis)
  if (!mode) {
    writeSizeDimension(axis, undefined)
    return
  }
  if (mode === 'fixed') {
    writeSizeDimension(axis, { ...previous, mode: 'fixed', value: previous?.value ?? 100 })
    return
  }
  writeSizeDimension(axis, { ...previous, mode: mode as 'fill' | 'hug' })
}

function updateSizeValue(axis: 'width' | 'height', event: Event): void {
  const value = Number((event.target as HTMLInputElement).value)
  if (!Number.isFinite(value)) return
  const variable = layoutVariableFor(axis)
  if (variable) {
    store.setVariable(variable, `${clampLayoutSize(axis, value)}px`)
    if (sizeDimensionOf(axis)) writeSizeDimension(axis, undefined)
    return
  }
  // 流式内容容器：宽度是“填满 + 上限”，不是绝对宽度。
  if (axis === 'width' && isFlowWidth(selectedId.value)) {
    writeSizeDimension(axis, { ...sizeDimensionOf(axis), mode: 'fill', max: Math.round(value) })
    return
  }
  writeSizeDimension(axis, { ...sizeDimensionOf(axis), mode: 'fixed', value })
}

function updateSizeBound(axis: 'width' | 'height', bound: 'min' | 'max', event: Event): void {
  const raw = (event.target as HTMLInputElement).value
  const base: StudioDimension = sizeDimensionOf(axis) ?? { mode: 'hug' }
  writeSizeDimension(axis, { ...base, [bound]: raw === '' ? undefined : Number(raw) })
}

function updateFontSize(event: Event): void {
  patch({ text: { ...(draftNode.value.text || {}), size: Number((event.target as HTMLInputElement).value) } })
}

function updateLayer(event: Event): void {
  patch({ layer: Number((event.target as HTMLInputElement).value) })
}

function updateVisibility(event: Event): void {
  patch({ visibility: (event.target as HTMLInputElement).checked })
}

function pickAsset(): void {
  assetEl.value?.click()
}

async function sha256Hex(buffer: ArrayBuffer): Promise<string> {
  if (!globalThis.crypto?.subtle) return Math.random().toString(16).slice(2).padEnd(64, '0')
  const digest = await globalThis.crypto.subtle.digest('SHA-256', buffer)
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('')
}

function imageSize(dataUrl: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve) => {
    const image = new Image()
    image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight })
    image.onerror = () => resolve({ width: 32, height: 32 })
    image.src = dataUrl
  })
}

function toDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(new Error('读取图片失败'))
    reader.readAsDataURL(file)
  })
}

// user:“按这个设计方案审…补齐”+(方案 §8.5 内容嗅探：按文件头识别格式，不信任后缀；
//  SVG 额外拒绝脚本，且只作为 CSS image 渲染，从不注入 DOM。)
function sniffImageMime(buffer: ArrayBuffer): 'image/png' | 'image/jpeg' | 'image/gif' | 'image/webp' | 'image/svg+xml' | null {
  const bytes = new Uint8Array(buffer.slice(0, 16))
  if (bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47) return 'image/png'
  if (bytes[0] === 0xff && bytes[1] === 0xd8) return 'image/jpeg'
  if (bytes[0] === 0x47 && bytes[1] === 0x49 && bytes[2] === 0x46) return 'image/gif'
  if (bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46 && bytes[8] === 0x57 && bytes[9] === 0x45) return 'image/webp'
  const head = new TextDecoder().decode(buffer.slice(0, 512)).trim().toLowerCase()
  if (head.startsWith('<?xml') || head.startsWith('<svg')) return 'image/svg+xml'
  return null
}

async function importAsset(event: Event): Promise<void> {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  if (file.size > 1_500_000) {
    errors.value = [{ path: 'assets', message: t('图片过大，单张不能超过 1.5MB') }]
    return
  }
  try {
    const [dataUrl, buffer] = await Promise.all([toDataUrl(file), file.arrayBuffer()])
    const mime = sniffImageMime(buffer)
    if (!mime) {
      errors.value = [{ path: 'assets', message: t('图片格式无法识别') }]
      return
    }
    if (mime === 'image/svg+xml' && new TextDecoder().decode(buffer).toLowerCase().includes('<script')) {
      errors.value = [{ path: 'assets', message: t('SVG 不允许包含脚本') }]
      return
    }
    const [hash, size] = await Promise.all([sha256Hex(buffer), imageSize(dataUrl)])
    const id = `asset-${hash.slice(0, 12)}`
    const existing = store.draft.value.assets.find((item) => item.sha256 === hash)
    if (!existing) {
      store.draft.value.assets.push({ id, sha256: hash, mime, width: size.width, height: size.height, url: dataUrl })
    }
    const assetId = existing?.id || id
    assetUrls.value[assetId] = dataUrl
    // 上图只加“图片层”：已有底色/渐变/令牌原样留在文档里，撤图时才能原样恢复。
    patch({ background: { ...(draftNode.value.background || {}), type: 'asset', assetRef: assetId, fit: 'cover', overflow: 'clipped' } })
  } catch (error) {
    errors.value = [{ path: 'assets', message: error instanceof Error ? error.message : t('图片读取失败') }]
  }
}

function clearAsset(): void {
  // user:“一个样式最开始是什么颜色……上完图再把图撤了，就会发生突变”+
  // (撤图只摘掉图片层：设过的底色/令牌/渐变原样恢复；什么都没设过就整条背景覆盖移除，
  //  组件自己的原生样式原样显示，绝不留 background-image:none 这类伪造规则。)
  const current = draftNode.value.background
  if (!current?.assetRef) return
  const rest: Record<string, unknown> = { ...current }
  delete rest.assetRef
  delete rest.fit
  delete rest.overflow
  delete rest.overflowHost
  delete rest.slice
  const hasBase = Boolean(rest.color || rest.colorToken)
  const hasGradient = Array.isArray(rest.stops) && rest.stops.length > 0
  if (!hasBase && !hasGradient) {
    patch({ background: undefined })
    return
  }
  patch({ background: { ...(rest as unknown as StudioBackground), type: hasBase ? 'solid' : 'gradient' } })
}

function updateFit(event: Event): void {
  patch({ background: { ...(activeBackground.value || { type: 'asset' }), type: 'asset', fit: (event.target as HTMLSelectElement).value as never } })
}

// user:“添加的图像应该可以裁切、位移、缩放等等”+(位置=焦点百分比，缩放=相对原始尺寸的倍数)
const backgroundScale = computed(() => activeBackground.value?.scale ?? 1)

// user:“把图片的编辑器给做成九宫格裁切，九宫格可拖动，九宫格就代表了这个图片实际显示进去的是什么部分”+
// (整块九宫格=组件实际显示范围；拖动它平移取景，实时映射到位置百分比，松手提交一次。)
const cropEl = ref<HTMLElement | null>(null)
const cropLivePosition = ref<{ x: number; y: number } | null>(null)
// user:“九宫格应该跟图像实际显示范围挂钩”+
// (取景框的宽高比 = 目标元素实际渲染的宽高比，九宫格里看到的就是组件里真正显示的画面。)
const cropAspect = ref<number | null>(null)
const cropFrameStyle = computed<Record<string, string>>(() => {
  const aspect = Math.min(4, Math.max(0.35, cropAspect.value ?? 16 / 9))
  return {
    aspectRatio: `${aspect}`,
    width: `min(100%, ${Math.round(240 * aspect)}px)`,
  }
})
let cropDrag: { startX: number; startY: number; baseX: number; baseY: number; overflowX: number; overflowY: number } | null = null

function cropMetrics(): { imageW: number; imageH: number; overflowX: number; overflowY: number } | null {
  // jsdom/离屏测不到尺寸时退回固定帧，保证取景计算始终可用（与面板尺寸无关的近似）。
  const frameW = cropEl.value?.clientWidth || 220
  const frameH = cropEl.value?.clientHeight || 150
  const background = activeBackground.value
  const asset = store.draft.value.assets.find((item) => item.id === background?.assetRef)
  if (!asset || asset.width <= 0 || asset.height <= 0) return null
  const fit = background?.fit ?? 'cover'
  const base = fit === 'contain'
    ? Math.min(frameW / asset.width, frameH / asset.height)
    : fit === 'fixed'
      ? 1
      : fit === 'stretch'
        ? 0
        : Math.max(frameW / asset.width, frameH / asset.height)
  const scale = base * (background?.scale ?? 1)
  const imageW = asset.width * scale
  const imageH = asset.height * scale
  return { imageW, imageH, overflowX: Math.max(0, imageW - frameW), overflowY: Math.max(0, imageH - frameH) }
}

const cropImageStyle = computed<Record<string, string>>(() => {
  // 渲染期只使用纯数据，不读取 DOM 尺寸（测量只在拖拽计算里做，避免渲染依赖自激）。
  const background = activeBackground.value
  const assetRef = background?.assetRef
  const url = assetRef ? assetUrls.value[assetRef] || store.draft.value.assets.find((item) => item.id === assetRef)?.url || '' : ''
  const live = cropLivePosition.value
  const x = live?.x ?? background?.positionX ?? 50
  const y = live?.y ?? background?.positionY ?? 50
  const scale = background?.scale ?? 1
  const fit = background?.fit ?? 'cover'
  const size = scale !== 1
    ? `${Math.round(scale * 100)}% ${Math.round(scale * 100)}%`
    : fit === 'contain'
      ? 'contain'
      : fit === 'tile'
        ? 'auto'
        : fit === 'stretch'
          ? '100% 100%'
          : 'cover'
  const style: Record<string, string> = { backgroundPosition: `${x}% ${y}%` }
  if (!url) return style
  style.backgroundImage = `url("${url}")`
  style.backgroundSize = size
  style.backgroundRepeat = 'no-repeat'
  return style
})

function onCropPointerDown(event: PointerEvent): void {
  const metrics = cropMetrics()
  if (!metrics) return
  event.preventDefault()
  cropDrag = {
    startX: event.clientX,
    startY: event.clientY,
    baseX: activeBackground.value?.positionX ?? 50,
    baseY: activeBackground.value?.positionY ?? 50,
    overflowX: metrics.overflowX,
    overflowY: metrics.overflowY,
  }
  cropLivePosition.value = { x: cropDrag.baseX, y: cropDrag.baseY }
  window.addEventListener('pointermove', onCropPointerMove)
  window.addEventListener('pointerup', onCropPointerUp, { once: true })
}

function onCropPointerMove(event: PointerEvent): void {
  const drag = cropDrag
  if (!drag) return
  const dx = event.clientX - drag.startX
  const dy = event.clientY - drag.startY
  const clamp = (value: number) => Math.min(100, Math.max(0, Math.round(value)))
  const x = drag.overflowX > 0 ? clamp(drag.baseX - (dx / drag.overflowX) * 100) : drag.baseX
  const y = drag.overflowY > 0 ? clamp(drag.baseY - (dy / drag.overflowY) * 100) : drag.baseY
  cropLivePosition.value = { x, y }
}

function onCropPointerUp(): void {
  window.removeEventListener('pointermove', onCropPointerMove)
  const drag = cropDrag
  const live = cropLivePosition.value
  cropDrag = null
  cropLivePosition.value = null
  if (!drag || !live) return
  if (live.x !== drag.baseX || live.y !== drag.baseY) {
    patch({
      background: {
        ...(activeBackground.value || { type: 'asset' }),
        type: 'asset',
        positionX: live.x,
        positionY: live.y,
      },
    })
  }
}

function updateBackgroundPosition(axis: 'x' | 'y', event: Event): void {
  const value = Number((event.target as HTMLInputElement).value)
  if (!Number.isFinite(value)) return
  const clamped = Math.min(100, Math.max(0, value))
  patch({
    background: {
      ...(activeBackground.value || { type: 'asset' }),
      type: 'asset',
      ...(axis === 'x' ? { positionX: clamped } : { positionY: clamped }),
    },
  })
}

function updateBackgroundScale(event: Event): void {
  const value = Number((event.target as HTMLInputElement).value)
  if (!Number.isFinite(value)) return
  const clamped = Math.min(4, Math.max(0.1, value))
  patch({ background: { ...(activeBackground.value || { type: 'asset' }), type: 'asset', scale: clamped } })
}

function sliceOf(side: 'top' | 'right' | 'bottom' | 'left'): number {
  return activeBackground.value?.slice?.[side] ?? 12
}

function updateSlice(side: 'top' | 'right' | 'bottom' | 'left', event: Event): void {
  const value = Number((event.target as HTMLInputElement).value)
  const current = activeBackground.value
  if (!current) return
  patch({
    background: {
      ...current,
      type: 'asset',
      fit: 'nineSlice',
      slice: { top: sliceOf('top'), right: sliceOf('right'), bottom: sliceOf('bottom'), left: sliceOf('left'), [side]: value },
    },
  })
}

function updateOverflow(event: Event): void {
  const checked = (event.target as HTMLInputElement).checked
  const element = targetElement()
  // user:“我不是说过图像不被容器裁切吗”+(外绘需要定位宿主：只在元素原本是 static 时补 relative，
  //  已有定位的元素绝不覆盖，否则会打乱 fixed/absolute 布局。)
  const needsHost = checked && element ? getComputedStyle(element).position === 'static' : false
  patch({
    background: {
      ...(activeBackground.value || { type: 'asset' }),
      type: 'asset',
      overflow: checked ? 'local-visible' : 'clipped',
      overflowHost: needsHost ? 'relative' : undefined,
    },
  })
}

function clearSelected(): void {
  // user:“写好清单，逐项打勾”+(在哪个作用域清除就只清哪个作用域，实例不能顺手删掉模板那一条)
  if (scope.value === 'instance') {
    if (instanceKey.value) store.removeInstanceNode(instanceKey.value)
    refreshPreview()
    return
  }
  if (!selectedId.value) return
  if (scope.value !== 'base') {
    store.removeBreakpointNode(scope.value, selectedId.value)
    refreshPreview()
    return
  }
  store.removeNode(selectedId.value)
}

function targetElement(): HTMLElement | null {
  // 点中的是某一条时，选框跟着这一条走（即使编辑的是共享模板），所见即所改。
  if (instanceElement.value) return instanceElement.value
  if (!selectedId.value) return null
  const attribute = selectedIsTemplate.value ? 'data-ui-template' : 'data-ui-id'
  return document.querySelector<HTMLElement>(`[${attribute}="${selectedId.value}"]`)
}

function syncOutline(): void {
  const outline = outlineEl.value
  const element = targetElement()
  // 九宫格取景框跟随目标元素真实宽高比（测不到时回退 16:9）。
  if (element) {
    const elementRect = element.getBoundingClientRect()
    if (elementRect.width > 0 && elementRect.height > 0) {
      cropAspect.value = elementRect.width / elementRect.height
    }
  }
  if (!outline) return
  if (!element) {
    outline.classList.remove('is-visible')
  } else {
    const rect = element.getBoundingClientRect()
    outline.style.top = `${rect.top}px`
    outline.style.left = `${rect.left}px`
    outline.style.width = `${rect.width}px`
    outline.style.height = `${rect.height}px`
    outline.classList.add('is-visible')
  }
  extraRects.value = extraIds.value.flatMap((id) => {
    const node = elementOf(id)
    if (!node) return []
    const rect = node.getBoundingClientRect()
    return [{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }]
  })
  // 缩放手柄只给有尺寸权限的元素，避免假手柄（方案 §3.3）。
  resizeBox.value = element && editMode.value && overlaysVisible.value && selectedId.value
    && allowsId(selectedId.value, 'size')
    ? (() => {
        const rect = element.getBoundingClientRect()
        return { top: rect.top, left: rect.left, width: rect.width, height: rect.height }
      })()
    : null
  // 间距胶囊跟着选中元素走（贴右上角外侧，随滚动/窗口变化同步）。
  if (element && editMode.value && overlaysVisible.value) {
    const rect = element.getBoundingClientRect()
    gapPillPos.value = {
      left: Math.round(Math.min(rect.right + 8, window.innerWidth - 72)),
      top: Math.round(Math.max(8, rect.top - 24)),
    }
  } else {
    gapPillPos.value = null
  }
  syncAuxiliaryOverlays()
}

/** 父容器轮廓、父子中心虚线与模板/实例标注；中心几乎重合时不画线，父级信息在属性面板有文字。 */
function syncAuxiliaryOverlays(): void {
  // 浏览态或辅助层关闭时不画任何标注（方案 §5.4）。
  const element = editMode.value && overlaysVisible.value ? targetElement() : null
  const parent = element?.parentElement ?? null
  if (element && parent) {
    const outer = parent.getBoundingClientRect()
    parentBox.value = { top: outer.top, left: outer.left, width: outer.width, height: outer.height }
    const inner = element.getBoundingClientRect()
    const x1 = inner.left + inner.width / 2
    const y1 = inner.top + inner.height / 2
    const x2 = outer.left + outer.width / 2
    const y2 = outer.top + outer.height / 2
    parentLink.value = Math.hypot(x2 - x1, y2 - y1) < 24 ? null : { x1, y1, x2, y2 }
  } else {
    parentBox.value = null
    parentLink.value = null
  }
  if (overlaysVisible.value && editMode.value && selectedIsTemplate.value && selectedId.value) {
    const nodes = [...document.querySelectorAll<HTMLElement>(`[data-ui-template="${selectedId.value}"]`)]
    const sample = instanceElement.value && nodes.includes(instanceElement.value) ? instanceElement.value : nodes[0]
    const first = sample?.getBoundingClientRect()
    templateSampleBox.value = first
      ? { top: first.top, left: first.left, width: first.width, height: first.height }
      : null
    templateSiblingBoxes.value = nodes
      .filter((node) => node !== sample)
      .map((node) => node.getBoundingClientRect())
      .map((rect) => ({ top: rect.top, left: rect.left, width: rect.width, height: rect.height }))
  } else {
    templateSampleBox.value = null
    templateSiblingBoxes.value = []
  }
}

function onDocumentPointer(event: MouseEvent): void {
  // user:“不点击双栏键时，右键点击任何一个组件……展开小版右栏”+(点面板外的空白处就收起小版右栏)
  if (miniInspector.value) {
    const target = event.target as Element | null
    if (!target?.closest('[data-studio-mini-inspector]')) miniInspector.value = false
  }
  // user:“编辑器状态下，若编辑模式未打开则保持正常交互”+
  // (编辑模式关闭时不拦截任何点击，界面元素照常响应业务动作。)
  if (!editMode.value) return
  const target = event.target as Element | null
  const host = target?.closest<HTMLElement>('[data-ui-id], [data-ui-template]')
  if (!host) return
  // user:“锁定”+(锁定的图层在画布上不响应点选)
  if (isEditorLocked(host.dataset.uiId || host.dataset.uiTemplate)) {
    event.preventDefault()
    event.stopPropagation()
    return
  }
  // 编辑态先选中，不触发展开、跳转等业务动作。
  event.preventDefault()
  event.stopPropagation()
  if (selectInstance(host)) return
  select(host.dataset.uiId || host.dataset.uiTemplate || '', event.ctrlKey || event.metaKey)
}

function closeEditor(): void {
  studioOpen.value = false
  emit('close')
}

// user:“确认带反馈动画”+(先落地发布，给确认键一个打勾脉冲反馈，再关闭编辑器)
function confirmPublish(): void {
  if (publishFeedback.value === 'confirmed') return
  const result = store.publish()
  if (!result.ok) return
  clearDraftStorage()
  publishFeedback.value = 'confirmed'
  publishCloseTimer = window.setTimeout(() => {
    publishCloseTimer = 0
    publishFeedback.value = 'idle'
    closeEditor()
  }, 420)
}

// user:“按这个设计方案审…补齐”+(方案 §10.1 恢复默认同时清掉自动保存的草稿)
// CoreConfirmDialog 是受控组件：确认后要自己收起对话框。
function confirmReset(): void {
  resetConfirm.value = false
  onResetDefault()
}

function onResetDefault(): void {
  store.reset()
  clearDraftStorage()
}

// user:“并加一个编辑模式的开关和一个取消（不保存退出）”+
// (取消=不保存退出：丢弃未发布草稿并关闭编辑器，不写任何存储。)
function cancelEdit(): void {
  store.discard()
  clearDraftStorage()
  closeEditor()
}

// user:“点图层按钮不要同时把图层和属性调出来，点属性按钮也一样”+
// (图层键只开左侧图层卡并切到图层视图；属性键只开右侧属性卡，两张卡各管各的。)
function toggleTree(): void {
  treeOpen.value = !treeOpen.value
  if (treeOpen.value) layerView.value = 'layers'
}

function toggleProps(): void {
  propsOpen.value = !propsOpen.value
  if (propsOpen.value) miniInspector.value = false
}

/** 小版右栏定位：优先放在目标元素右侧，其次左侧，再下方/上方，保证不遮挡目标本体。 */
function placeMiniInspector(target: HTMLElement): void {
  const rect = target.getBoundingClientRect()
  const width = 280
  const measured = miniEl.value?.getBoundingClientRect().height || 0
  const height = Math.min(measured > 0 ? measured : 420, window.innerHeight - 16)
  const gap = 12
  const viewportW = window.innerWidth
  const viewportH = window.innerHeight
  let left = rect.right + gap
  let top = rect.top
  if (left + width > viewportW - 8) {
    left = rect.left - gap - width >= 8 ? rect.left - gap - width : Math.max(8, viewportW - width - 8)
  }
  top = Math.min(Math.max(8, top), Math.max(8, viewportH - height - 8))
  const overlaps = left < rect.right && left + width > rect.left && top < rect.bottom && top + height > rect.top
  if (overlaps) {
    if (rect.bottom + gap + height <= viewportH - 8) {
      top = rect.bottom + gap
      left = Math.min(Math.max(8, rect.left), viewportW - width - 8)
    } else if (rect.top - gap - height >= 8) {
      top = rect.top - gap - height
      left = Math.min(Math.max(8, rect.left), viewportW - width - 8)
    }
  }
  miniStyle.value = { left: `${Math.round(left)}px`, top: `${Math.round(top)}px` }
}

/**
 * user:“我希望左侧的元素卡和右侧的图层卡，以及底下的工具条，全部都可以被拖动”+
 * (拖拽手柄=面板标题栏/工具条空白处；按钮、输入框、页签照常点击，不触发整卡拖动。)
 */
function floatingElement(card: FloatingCard): HTMLElement | null {
  if (card === 'tree') return treeEl.value
  if (card === 'props') return miniEl.value
  return toolbarEl.value
}

function floatingStyle(card: FloatingCard): Record<string, string> | undefined {
  const point = floatingPositions.value[card]
  if (!point) return undefined
  if (card === 'bar') {
    return { left: `${point.x}px`, top: `${point.y}px`, bottom: 'auto', transform: 'none' }
  }
  return {
    left: `${point.x}px`,
    top: `${point.y}px`,
    right: 'auto',
    bottom: 'auto',
    maxHeight: `calc(100vh - ${point.y + 8}px)`,
  }
}

// 小版属性浮层仍然由选中位置决定坐标；不处于小版模式时才用拖拽位置。
const propsPanelStyle = computed(() => {
  if (miniInspector.value && !propsOpen.value) return miniStyle.value
  return floatingStyle('props')
})

interface FloatingDrag {
  card: FloatingCard
  pointerId: number | undefined
  startX: number
  startY: number
  originX: number
  originY: number
  width: number
  height: number
  el: HTMLElement
}

let floatingDrag: FloatingDrag | null = null

function startFloatingDrag(card: FloatingCard, event: PointerEvent): void {
  if (event.button !== undefined && event.button !== 0) return
  const target = event.target as Element | null
  // 图标键、页签、输入框和滚动条不参与整卡拖动，避免点按钮变成拖卡。
  if (target?.closest('button, input, select, textarea, a, [data-studio-no-drag]')) return
  const el = floatingElement(card)
  if (!el) return
  const rect = el.getBoundingClientRect()
  floatingDrag = {
    card,
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    originX: rect.left,
    originY: rect.top,
    width: rect.width,
    height: rect.height,
    el,
  }
  el.classList.add('is-dragging')
  event.preventDefault()
  window.addEventListener('pointermove', onFloatingPointerMove)
  window.addEventListener('pointerup', endFloatingDrag)
  window.addEventListener('pointercancel', endFloatingDrag)
}

function onFloatingPointerMove(event: PointerEvent): void {
  const drag = floatingDrag
  if (!drag) return
  if (drag.pointerId !== undefined && event.pointerId !== undefined && event.pointerId !== drag.pointerId) return
  const maxX = Math.max(0, window.innerWidth - drag.width)
  const maxY = Math.max(0, window.innerHeight - drag.height)
  const x = Math.min(maxX, Math.max(0, drag.originX + (event.clientX - drag.startX)))
  const y = Math.min(maxY, Math.max(0, drag.originY + (event.clientY - drag.startY)))
  floatingPositions.value = { ...floatingPositions.value, [drag.card]: { x: Math.round(x), y: Math.round(y) } }
  event.preventDefault()
}

function endFloatingDrag(): void {
  const drag = floatingDrag
  if (!drag) return
  floatingDrag = null
  drag.el.classList.remove('is-dragging')
  window.removeEventListener('pointermove', onFloatingPointerMove)
  window.removeEventListener('pointerup', endFloatingDrag)
  window.removeEventListener('pointercancel', endFloatingDrag)
}

function onDocumentContextMenu(event: MouseEvent): void {
  if (!editMode.value) return
  const target = (event.target as Element | null)?.closest<HTMLElement>('[data-ui-id], [data-ui-template]')
  if (!target) return
  // 编辑态一律接管右键，业务自己的右键菜单不再弹出。
  event.preventDefault()
  event.stopPropagation()
  // 属性卡已展开时直接用完整面板；只有它收起时才弹小版属性浮层。
  if (propsOpen.value) return
  const contextId = target.dataset.uiId || target.dataset.uiTemplate || ''
  if (isEditorLocked(contextId)) return
  if (selectInstance(target)) {
    // 实例默认进模板作用域（见 selectInstance）。
  } else {
    select(target.dataset.uiId || target.dataset.uiTemplate || '')
  }
  miniInspector.value = true
  void nextTick(() => placeMiniInspector(target))
}

// user:“在编辑状态下，应该禁用掉原有的交互，比如说拖动会话栏排序”+
// (mousedown / dragstart 在捕获层拦掉：组件自己的拖拽排序等不再启动。)
function onBusinessInputCapture(event: Event): void {
  if (!editMode.value) return
  const target = event.target as Element | null
  if (!target?.closest('[data-ui-id], [data-ui-template]')) return
  event.preventDefault()
  event.stopPropagation()
}

function exportDocument(): void {
  const blob = new Blob([JSON.stringify(store.draft.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `sunday-theme-v${THEME_STUDIO_SCHEMA_VERSION}.json`
  anchor.click()
  URL.revokeObjectURL(url)
}

function pickImport(): void {
  importEl.value?.click()
}

async function importDocument(event: Event): Promise<void> {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  if (file.size > 4_000_000) {
    errors.value = [{ path: '', message: t('主题文件过大，请检查是否误选了其他文件') }]
    return
  }
  try {
    // user:“按这个设计方案审…补齐”+(独立审查 P1：导入失败必须给提示，非法文档不进草稿、不静默)
    const migrated = migrateStudioDocument(JSON.parse(await file.text()))
    if (!migrated.ok) {
      errors.value = [{ path: '', message: migrated.error }]
      return
    }
    const validation = validateStudioDocument(migrated.document)
    if (!validation.ok) {
      errors.value = validation.errors
      return
    }
    store.replaceDraft(migrated.document)
  } catch {
    errors.value = [{ path: '', message: t('文件不是有效的主题 JSON') }]
  }
}

function snapTargetsFor(element: HTMLElement): { x: number[]; y: number[] } {
  const targets = {
    x: [0, window.innerWidth / 2, window.innerWidth],
    y: [0, window.innerHeight / 2, window.innerHeight],
  }
  const parent = element.parentElement
  if (parent) {
    const rect = parent.getBoundingClientRect()
    targets.x.push(rect.left, rect.left + rect.width / 2, rect.left + rect.width)
    targets.y.push(rect.top, rect.top + rect.height / 2, rect.top + rect.height)
  }
  return targets
}

function showGuides(x: number | null, y: number | null): void {
  if (guideXEl.value) {
    guideXEl.value.style.opacity = x === null ? '0' : '1'
    if (x !== null) guideXEl.value.style.left = `${x}px`
  }
  if (guideYEl.value) {
    guideYEl.value.style.opacity = y === null ? '0' : '1'
    if (y !== null) guideYEl.value.style.top = `${y}px`
  }
}

function onPointerDown(event: PointerEvent): void {
  // 浏览态不进入拖拽：编辑模式关闭时按住元素就是普通按压。
  if (!editMode.value) return
  // user:“装文字它本身就是一个容器，它是可以被拖动拉伸的”+(样式类型/模板同样可拖)
  const target = (event.target as Element | null)?.closest<HTMLElement>('[data-ui-id], [data-ui-template]')
  if (!target) return
  const id = target.dataset.uiId || target.dataset.uiTemplate || ''
  if (!id) return
  // user:“锁定”+(锁定的图层不参与点选与拖动)
  if (isEditorLocked(id)) {
    event.preventDefault()
    event.stopPropagation()
    return
  }
  if (!selectInstance(target)) select(id, event.ctrlKey || event.metaKey)
  if (!allowsId(id, 'position')) return
  event.preventDefault()
  event.stopPropagation()
  const rect = target.getBoundingClientRect()
  const base = offsetOf('x') || offsetOf('y')
    ? { x: offsetOf('x'), y: offsetOf('y') }
    : { x: 0, y: 0 }
  dragState = {
    id,
    el: target,
    startX: event.clientX,
    startY: event.clientY,
    base,
    box: { left: rect.left - base.x, top: rect.top - base.y, width: rect.width, height: rect.height },
    moved: false,
  }
  dragOffset = null
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp, { once: true })
  window.addEventListener('pointercancel', onPointerCancel, { once: true })
}

/** 废弃进行中的拖拽：清预览位移与提示，不提交任何样式（独立审查 P2）。 */
function abortDrag(): void {
  const state = dragState
  dragState = null
  dragOffset = null
  dragHint.value = ''
  showGuides(null, null)
  window.removeEventListener('pointermove', onPointerMove)
  if (state) state.el.style.translate = ''
}

function onPointerCancel(): void {
  abortDrag()
  void nextTick(() => syncOutline())
}

function onPointerMove(event: PointerEvent): void {
  const state = dragState
  if (!state) return
  const dx = event.clientX - state.startX
  const dy = event.clientY - state.startY
  if (!state.moved && Math.hypot(dx, dy) < 3) return
  state.moved = true
  const next: Offset = { x: state.base.x + dx, y: state.base.y + dy }
  // user:“按这个设计方案审…补齐”+(方案 §3.1 吸附开关：关闭时只做限幅，不吸附、不画参考线)
  const outcome = snapEnabled.value
    ? snapOffset(state.box, next, snapTargetsFor(state.el))
    : {
        x: Math.max(-OFFSET_LIMIT, Math.min(OFFSET_LIMIT, next.x)),
        y: Math.max(-OFFSET_LIMIT, Math.min(OFFSET_LIMIT, next.y)),
        guideX: null,
        guideY: null,
      }
  dragOffset = { x: outcome.x, y: outcome.y }
  state.el.style.translate = `${outcome.x}px ${outcome.y}px`
  const parent = state.el.parentElement
  if (parent) {
    const rect = state.el.getBoundingClientRect()
    const outer = parent.getBoundingClientRect()
    const round = (value: number) => Math.round(value)
    dragHint.value = `${t('左')} ${round(rect.left - outer.left)} · ${t('上')} ${round(rect.top - outer.top)} · ${t('右')} ${round(outer.right - rect.right)} · ${t('下')} ${round(outer.bottom - rect.bottom)}`
  }
  showGuides(outcome.guideX, outcome.guideY)
  syncOutline()
}

function onPointerUp(): void {
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointercancel', onPointerCancel)
  const state = dragState
  dragState = null
  dragHint.value = ''
  showGuides(null, null)
  if (!state) return
  if (state.moved && dragOffset) {
    // user:“桌面壳作为底层容器 不应该有任何容器能够超出它”+
    // (先把本次位移夹回外壳，再按贴边推断锚点，避免存出到壳外的位置)
    dragOffset = clampOffsetToShell(state.el, dragOffset)
    state.el.style.translate = `${dragOffset.x}px ${dragOffset.y}px`
    // user:“写好清单，逐项打勾”+(拖动也按当前作用域写，别在窄屏或实例里改到基础样式)
    // user:“贴近父级边界 → 预览边界锚点；释放后保留该边距”+(方案 §4.5 拖拽推断)
    const inferred = snapEnabled.value ? inferParentAnchors(state.el) : null
    if (inferred) {
      const style = styleAt(state.id)
      const axes = inferred.map((anchor) => anchorAxis(anchor.edge))
      const isSameAxis = (edge: StudioAnchorEdge) => axes.includes(anchorAxis(edge))
      const anchors = [
        ...(style.anchors || []).filter((anchor) => !isSameAxis(anchor.edge)),
        ...inferred,
      ]
      // 被锚定的轴由锚点接管位置，未锚定的轴保留位移增量。
      const offset = style.offset || { x: 0, y: 0 }
      const nextOffset = { x: axes.includes('x') ? 0 : offset.x, y: axes.includes('y') ? 0 : offset.y }
      writeStyle(state.id, {
        ...style,
        anchors,
        offset: nextOffset.x !== 0 || nextOffset.y !== 0 ? nextOffset : undefined,
      })
    } else {
      writeStyle(state.id, { ...styleAt(state.id), offset: dragOffset })
    }
    if (scope.value !== 'base') refreshPreview()
  }
  state.el.style.translate = ''
  dragOffset = null
  void nextTick(() => {
    syncOutline()
    // user:“如果它超出了父节点的位置，那要把父节点也自动撑大”+(拖动越界同样撑大父级)
    growParentToFit()
  })
}

function anchorAxis(edge: StudioAnchorEdge): 'x' | 'y' {
  return edge === 'left' || edge === 'right' || edge === 'centerX' ? 'x' : 'y'
}

/**
 * user:“贴近父级边界 → 预览边界锚点；释放后保留该边距”+
 * (方案 §4.5：松手时若贴住父容器的边/中心线，就把这次关系存成边锚点；
 *  只经过不松手、禁用吸附、或父级未登记时不保存关系。)
 */
function inferParentAnchors(element: HTMLElement): StudioNodeAnchor[] | null {
  const parentEl = element.parentElement
  if (!parentEl) return null
  // 父级未登记时无法保证它成为定位宿主，退回普通位移。
  if (!registeredIdOf(parentEl)) return null
  const rect = element.getBoundingClientRect()
  const outer = parentEl.getBoundingClientRect()
  if (outer.width <= 0 || outer.height <= 0) return null
  const threshold = 6
  const leftDist = rect.left - outer.left
  const rightDist = outer.right - rect.right
  const topDist = rect.top - outer.top
  const bottomDist = outer.bottom - rect.bottom
  const centerXDist = Math.abs(rect.left + rect.width / 2 - (outer.left + outer.width / 2))
  const centerYDist = Math.abs(rect.top + rect.height / 2 - (outer.top + outer.height / 2))
  const anchors: StudioNodeAnchor[] = []
  if (centerXDist <= threshold && Math.abs(leftDist) > threshold && Math.abs(rightDist) > threshold) {
    anchors.push({ target: 'parent', edge: 'centerX', offset: 0 })
  } else if (Math.abs(leftDist) <= threshold) {
    anchors.push({ target: 'parent', edge: 'left', offset: Math.max(0, Math.round(leftDist)) })
  } else if (Math.abs(rightDist) <= threshold) {
    anchors.push({ target: 'parent', edge: 'right', offset: Math.max(0, Math.round(rightDist)) })
  }
  if (centerYDist <= threshold && Math.abs(topDist) > threshold && Math.abs(bottomDist) > threshold) {
    anchors.push({ target: 'parent', edge: 'centerY', offset: 0 })
  } else if (Math.abs(topDist) <= threshold) {
    anchors.push({ target: 'parent', edge: 'top', offset: Math.max(0, Math.round(topDist)) })
  } else if (Math.abs(bottomDist) <= threshold) {
    anchors.push({ target: 'parent', edge: 'bottom', offset: Math.max(0, Math.round(bottomDist)) })
  }
  return anchors.length > 0 ? anchors : null
}

function updateOffset(axis: 'x' | 'y', event: Event): void {
  const value = Number((event.target as HTMLInputElement).value)
  patch({ offset: { x: offsetOf('x'), y: offsetOf('y'), [axis]: value } })
  pullSelectedInsideShell()
}

function onKeydown(event: KeyboardEvent): void {
  // 浏览态方向键还给界面（滚动、光标移动等），不做元素微调。
  if (!editMode.value) return
  // user:“按这个设计方案审…补齐”+(方案 §3.3：Esc 先退出多选，再取消选中)
  if (event.key === 'Escape') {
    if (miniInspector.value) {
      miniInspector.value = false
      return
    }
    if (dragState) {
      // 拖拽中 Esc：废弃本次拖拽，不提交位移。
      abortDrag()
      void nextTick(() => syncOutline())
      return
    }
    if (extraIds.value.length > 0) {
      extraIds.value = []
    } else if (selectedId.value) {
      selectedId.value = null
      instanceKey.value = null
      instanceElement.value = null
      if (scope.value === 'instance') scope.value = 'base'
      hoverBox.value = null
    } else {
      return
    }
    void nextTick(() => syncOutline())
    return
  }
  if (!selectedId.value || !allowsId(selectedId.value, 'position')) return
  const target = event.target as HTMLElement | null
  if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return
  const step = event.shiftKey ? 10 : 1
  const delta = { x: 0, y: 0 }
  if (event.key === 'ArrowLeft') delta.x = -step
  else if (event.key === 'ArrowRight') delta.x = step
  else if (event.key === 'ArrowUp') delta.y = -step
  else if (event.key === 'ArrowDown') delta.y = step
  else return
  event.preventDefault()
  patch({ offset: { x: offsetOf('x') + delta.x, y: offsetOf('y') + delta.y } })
}

let frame = 0
function onViewport(): void {
  hoverBox.value = null
  if (frame) return
  frame = requestAnimationFrame(() => {
    frame = 0
    syncOutline()
  })
}

onMounted(() => {
  restoreDraftFromStorage()
  // 图层显隐是编辑器会话状态：独立样式节点，退出编辑器即移除，发布不受影响。
  editorStateStyleEl = document.createElement('style')
  editorStateStyleEl.dataset.studioEditorState = ''
  document.head.appendChild(editorStateStyleEl)
  syncEditorStateStyles()
  document.addEventListener('click', onDocumentPointer, true)
  document.addEventListener('pointerdown', onPointerDown, true)
  document.addEventListener('mousemove', onPointerHover)
  document.addEventListener('mousedown', onBusinessInputCapture, true)
  document.addEventListener('dragstart', onBusinessInputCapture, true)
  document.addEventListener('contextmenu', onDocumentContextMenu, true)
  document.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', onViewport)
  window.addEventListener('scroll', onViewport, true)
  for (const asset of store.draft.value.assets) {
    if (!asset.url) continue
    assetUrls.value[asset.id] = asset.url
    // 异步预解码，避免切换组件时现解码造成闪动；失败不影响基础背景。
    const image = new Image()
    image.src = asset.url
    void image.decode?.().catch(() => {})
  }
  store.preview()
  void nextTick(() => { domVersion.value += 1 })
  // 独立审查可用性项：打开不再自动全选主区域（避免开屏整屏暗化、无引导的观感），
  // 属性面板给出「先选择一个组件」，用户点选或从图层树选择。
})

onBeforeUnmount(() => {
  flushPendingAutosave()
  if (publishCloseTimer) {
    window.clearTimeout(publishCloseTimer)
    publishCloseTimer = 0
  }
  endFloatingDrag()
  if (typeof document !== 'undefined') document.documentElement.classList.remove('studio-editing')
  editorStateStyleEl?.remove()
  editorStateStyleEl = null
  document.removeEventListener('click', onDocumentPointer, true)
  document.removeEventListener('pointerdown', onPointerDown, true)
  document.removeEventListener('mousemove', onPointerHover)
  document.removeEventListener('mousedown', onBusinessInputCapture, true)
  document.removeEventListener('dragstart', onBusinessInputCapture, true)
  document.removeEventListener('contextmenu', onDocumentContextMenu, true)
  document.removeEventListener('keydown', onKeydown)
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointercancel', onPointerCancel)
  window.removeEventListener('resize', onViewport)
  window.removeEventListener('scroll', onViewport, true)
  if (frame) cancelAnimationFrame(frame)
  store.clearPreview()
  store.dispose()
})
</script>

<style scoped>
.studio-root {
  position: fixed;
  inset: 0;
  z-index: var(--z-fullscreen, 900);
  pointer-events: none;
  /* 编辑器挂在 body 下，主区域主题变量够不到；玻璃着色取主区域面色，别退到默认象牙色。 */
  --optical-glass-surface: var(--theme-main-background, #1b1d22);
  --text: var(--theme-main-text, #f2efeb);
}
.studio-panel {
  position: absolute;
  top: var(--space-4, 16px);
  bottom: 64px;
  width: 280px;
  display: flex;
  flex-direction: column;
  gap: var(--space-2, 8px);
  padding: var(--space-3, 12px);
  border-radius: var(--radius-lg, 18px);
  color: var(--theme-main-text, #f2efeb);
  pointer-events: auto;
  visibility: visible;
  transform: translateX(0);
  opacity: 1;
  transition:
    transform var(--dur-slow, 280ms) var(--ease-out, ease),
    opacity var(--dur-slow, 280ms) var(--ease-out, ease),
    visibility 0s linear 0s;
}
.studio-tree { left: var(--space-4, 16px); }
.studio-props { right: var(--space-4, 16px); width: 300px; }
/* 收起时整体滑出屏幕，让真实界面成为画布；过渡结束后才隐藏，动画期间仍可点关闭。 */
.studio-panel:not(.is-open) {
  pointer-events: none;
  visibility: hidden;
  opacity: 0;
  transition:
    transform var(--dur-slow, 280ms) var(--ease-out, ease),
    opacity var(--dur-slow, 280ms) var(--ease-out, ease),
    visibility 0s linear var(--dur-slow, 280ms);
}
.studio-tree:not(.is-open) { transform: translateX(calc(-100% - 24px)); }
.studio-props:not(.is-open) { transform: translateX(calc(100% + 24px)); }
/* 小版右栏：双栏未展开时右键组件出现的紧凑属性浮层，定位在目标旁边不遮挡它。 */
.studio-props.is-mini {
  position: fixed;
  top: auto;
  right: auto;
  bottom: auto;
  width: 280px;
  max-height: min(72vh, 520px);
  transform: none;
}
/* 玻璃底座自带 overflow:hidden，滚动交给内层 body。 */
.studio-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2, 8px);
  overflow: auto;
}
@media (prefers-reduced-motion: reduce) {
  .studio-panel,
  .studio-panel:not(.is-open) {
    transition: none;
    transform: none;
  }
}
.studio-head {
  display: flex;
  align-items: center;
  gap: var(--space-2, 8px);
}
.studio-head .studio-view-tabs,
.studio-head .studio-badge { margin-left: auto; }
.studio-head strong { font-size: var(--type-md, 13px); }
.studio-view-tabs {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--theme-main-text, #f2efeb) 8%, transparent);
}
.studio-view-tab {
  min-height: 20px;
  padding: 0 8px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--muted, #a7a29b);
  font-size: var(--type-2xs, 10px);
  cursor: pointer;
}
.studio-view-tab.is-active { background: var(--theme-main-background, #1b1d22); color: var(--theme-main-text, #f2efeb); }
.studio-layer-band {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
  margin: 6px 0 2px;
  padding: 2px 4px;
  border: 0;
  border-radius: var(--radius-sm, 6px);
  background: transparent;
  color: var(--muted, #a7a29b);
  font-size: var(--type-2xs, 10px);
  text-align: left;
  cursor: pointer;
}
.studio-layer-band:hover { background: color-mix(in srgb, var(--theme-main-text, #f2efeb) var(--alpha-hover, 8%), transparent); color: var(--theme-main-text, #f2efeb); }
.studio-layer-item {
  grid-template-columns: auto minmax(0, 1fr) 64px;
  cursor: grab;
}
.studio-layer-item:active { cursor: grabbing; }
/* user:“那就再细分一层，把它挂在那个会话抽屉底下”+(缩进行前的小箭头=自动子层开关) */
.studio-layer-caret {
  width: 14px;
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm, 6px);
  background: transparent;
  color: var(--muted, #a7a29b);
  font-size: 10px;
  cursor: pointer;
}
.studio-layer-caret:hover { background: color-mix(in srgb, var(--theme-main-text, #f2efeb) var(--alpha-hover, 8%), transparent); }
.studio-layer-caret.is-empty { pointer-events: none; }
.studio-layer-item.is-nested .studio-tree-label { color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 78%, transparent); }
.studio-layer-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.studio-layer-copy .studio-tree-label,
.studio-layer-copy .studio-tree-meta {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.studio-layer-input {
  width: 64px;
  height: 20px;
  padding: 0 4px;
  border: 1px solid color-mix(in srgb, var(--theme-composer-text) 16%, transparent);
  border-radius: var(--radius-sm, 6px);
  background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent);
  color: var(--theme-composer-text);
  font-size: var(--type-2xs, 10px);
}
.studio-layer-input.is-auto {
  color: var(--muted, #a7a29b);
  font-variant-numeric: tabular-nums;
}
.studio-icon-btn {
  width: 24px;
  height: 24px;
  border: 0;
  border-radius: var(--radius-sm, 6px);
  background: transparent;
  color: inherit;
  cursor: pointer;
}
.studio-hint { margin: 0; color: var(--muted, #a7a29b); font-size: var(--type-xs, 11px); }
.studio-steps { display: flex; flex-direction: column; gap: 2px; }
.studio-tree-search {
  height: 28px;
  padding: 0 8px;
  border: 1px solid color-mix(in srgb, var(--theme-composer-text) 16%, transparent);
  border-radius: var(--radius-sm, 6px);
  background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent);
  color: var(--theme-composer-text);
  font-size: var(--type-sm, 12px);
}
.studio-tree-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  gap: var(--space-2, 8px);
  align-items: center;
  padding: 6px 8px;
  border: 0;
  border-radius: var(--radius-sm, 6px);
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.studio-tree-actions {
  display: inline-flex;
  gap: 2px;
}
.studio-tree-action {
  width: 18px;
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm, 6px);
  background: transparent;
  color: var(--muted, #a7a29b);
  font-size: 10px;
  cursor: pointer;
}
.studio-tree-action:hover { background: color-mix(in srgb, var(--theme-main-text, #f2efeb) var(--alpha-hover, 8%), transparent); }
.studio-tree-caret {
  width: 16px;
  height: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm, 6px);
  color: var(--muted, #a7a29b);
  font-size: 10px;
}
.studio-tree-caret:hover { background: color-mix(in srgb, var(--theme-main-text, #f2efeb) var(--alpha-hover, 8%), transparent); }
.studio-tree-item:hover { background: color-mix(in srgb, var(--theme-main-text, #f2efeb) var(--alpha-hover, 8%), transparent); }
.studio-tree-item.is-selected { background: color-mix(in srgb, var(--theme-main-text, #f2efeb) var(--alpha-active, 12%), transparent); }
.studio-tree-item.is-protected .studio-tree-label { color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 55%, transparent); }
.studio-tree-label { font-size: var(--type-sm, 12px); }
.studio-tree-meta { color: var(--muted, #a7a29b); font-size: var(--type-2xs, 10px); }
.studio-canvas { position: absolute; inset: 0; pointer-events: none; }
.studio-outline {
  position: fixed;
  border: 2px solid var(--blue, #79bcff);
  border-radius: var(--radius-sm, 6px);
  box-shadow: 0 0 0 9999px color-mix(in srgb, var(--bg, #111) 28%, transparent);
  opacity: 0;
  transition: opacity var(--dur-fast, 120ms) var(--ease-out, ease);
  pointer-events: none;
}
.studio-outline.is-visible { opacity: 1; }
.studio-slice { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 4px; }
.studio-slice input { min-width: 0; }
.studio-drag-hint {
  position: fixed;
  left: 50%;
  top: 108px;
  transform: translateX(-50%);
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--theme-main-background, #1b1d22);
  color: var(--theme-main-text, #f2efeb);
  font-size: var(--type-2xs, 10px);
  pointer-events: none;
}
.studio-outline--extra { border-color: color-mix(in srgb, var(--blue, #79bcff) 55%, transparent); }
.studio-align-bar {
  position: absolute;
  left: 50%;
  top: 72px;
  transform: translateX(-50%);
  display: flex;
  gap: 4px;
  padding: 6px 8px;
  border-radius: 999px;
  color: var(--theme-main-text, #f2efeb);
  pointer-events: auto;
}
/* 浏览态：编辑模式关闭时选框、参考线、提示与对齐条全部退场。 */
/* 浏览态（方案 §5.4：预览态全部消失）与辅助层总开关（§9.4）：全部画布标注退场。 */
.studio-canvas.is-browsing .studio-outline,
.studio-canvas.is-browsing .studio-guide,
.studio-canvas.is-browsing .studio-links,
.studio-canvas.is-browsing .studio-hover-box,
.studio-canvas.is-browsing .studio-parent-box,
.studio-canvas.is-browsing .studio-template-sample,
.studio-canvas.is-browsing .studio-template-sibling,
.studio-canvas.is-browsing .studio-drag-hint { display: none; }
.studio-canvas.is-browsing .studio-align-bar { display: none; }
/* 辅助标注层总开关（方案 §9.4）：隐藏全部画布标注，只留业务界面。 */
.studio-canvas.is-overlay-hidden .studio-outline,
.studio-canvas.is-overlay-hidden .studio-guide,
.studio-canvas.is-overlay-hidden .studio-links,
.studio-canvas.is-overlay-hidden .studio-hover-box,
.studio-canvas.is-overlay-hidden .studio-parent-box,
.studio-canvas.is-overlay-hidden .studio-template-sample,
.studio-canvas.is-overlay-hidden .studio-template-sibling,
.studio-canvas.is-overlay-hidden .studio-drag-hint { display: none; }
.studio-hover-box {
  position: fixed;
  border: 1px dashed var(--blue, #79bcff);
  border-radius: var(--radius-sm, 6px);
  pointer-events: none;
}
.studio-parent-box {
  position: fixed;
  border: 2px solid var(--green, #32d17d);
  border-radius: var(--radius, 12px);
  opacity: 0.75;
  pointer-events: none;
}
.studio-links {
  position: fixed;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
.studio-parent-link {
  stroke: var(--green, #32d17d);
  stroke-width: 1;
  stroke-dasharray: 4 4;
  opacity: 0.85;
}
.studio-template-sample {
  position: fixed;
  border: 2px solid var(--purple, #bd8cff);
  border-radius: var(--radius-sm, 6px);
  pointer-events: none;
}
.studio-template-sibling {
  position: fixed;
  border: 1px dashed var(--purple, #bd8cff);
  border-radius: var(--radius-sm, 6px);
  opacity: 0.7;
  pointer-events: none;
}
/* 间距胶囊：滚轮微调父级行距，双击转入输入。 */
.studio-gap-pill {
  position: fixed;
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 8px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #f2efeb) 22%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--theme-main-background, #1b1d22) 88%, transparent);
  color: var(--theme-main-text, #f2efeb);
  font-size: var(--type-2xs, 10px);
  cursor: ns-resize;
  pointer-events: auto;
}
.studio-gap-pill input {
  width: 48px;
  height: 18px;
  padding: 0 4px;
  border: 0;
  border-radius: var(--radius-sm, 6px);
  background: transparent;
  color: inherit;
  font-size: inherit;
}
.studio-canvas.is-browsing .studio-gap-pill,
.studio-canvas.is-overlay-hidden .studio-gap-pill { display: none; }

/* 尺寸手柄：边框不挡交互，只有小方块接收指针。 */
.studio-resize-frame {
  position: fixed;
  pointer-events: none;
}
.studio-resize-handle {
  position: absolute;
  width: 8px;
  height: 8px;
  border: 1px solid var(--blue, #79bcff);
  border-radius: 2px;
  background: var(--theme-main-background, #1b1d22);
  pointer-events: auto;
}
.studio-resize-handle--n { top: -4px; left: 50%; margin-left: -4px; cursor: ns-resize; }
.studio-resize-handle--s { bottom: -4px; left: 50%; margin-left: -4px; cursor: ns-resize; }
.studio-resize-handle--e { right: -4px; top: 50%; margin-top: -4px; cursor: ew-resize; }
.studio-resize-handle--w { left: -4px; top: 50%; margin-top: -4px; cursor: ew-resize; }
.studio-resize-handle--ne { right: -4px; top: -4px; cursor: nesw-resize; }
.studio-resize-handle--nw { left: -4px; top: -4px; cursor: nwse-resize; }
.studio-resize-handle--se { right: -4px; bottom: -4px; cursor: nwse-resize; }
.studio-resize-handle--sw { left: -4px; bottom: -4px; cursor: nesw-resize; }
.studio-guide {
  position: fixed;
  background: var(--blue, #79bcff);
  opacity: 0;
  pointer-events: none;
  transition: opacity var(--dur-fast, 120ms) var(--ease-out, ease);
}
.studio-guide--x { top: 0; bottom: 0; width: 1px; }
.studio-guide--y { left: 0; right: 0; height: 1px; }
.studio-instance-tag { color: var(--blue, #79bcff); }
.studio-scope { display: flex; flex-direction: column; gap: 6px; margin-bottom: var(--space-2, 8px); }
.studio-asset-row { display: flex; gap: var(--space-2, 8px); }
/* 素材按钮：有图时整颗按钮变成小号缩略图，点击即换图。 */
.studio-asset-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 64px;
  height: 30px;
  padding: 0 var(--space-2, 8px);
  overflow: hidden;
}
.studio-asset-chip.has-thumb {
  width: 52px;
  min-width: 52px;
  padding: 0;
}
.studio-asset-thumb {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.studio-select { height: 28px; border: 1px solid color-mix(in srgb, var(--theme-composer-text) 16%, transparent); border-radius: var(--radius-sm, 6px); background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent); color: var(--theme-composer-text); }
.studio-field--pair { display: grid; grid-template-columns: auto minmax(0, 1fr) minmax(0, 1fr); align-items: center; gap: 6px; }
.studio-color-row { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 6px; }
.studio-color-row input[type='color'] { width: 44px; }
/* 九宫格裁切器：整块区域就是组件实际显示的画面，拖动平移取景。 */
.studio-crop {
  position: relative;
  min-height: 48px;
  max-width: 100%;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #f2efeb) 22%, transparent);
  border-radius: var(--radius-sm, 6px);
  background-color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 6%, transparent);
  overflow: hidden;
  cursor: grab;
  touch-action: none;
  user-select: none;
}
.studio-crop:active { cursor: grabbing; }
.studio-crop-grid {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background-image:
    linear-gradient(to right, color-mix(in srgb, #fff 42%, transparent) 1px, transparent 1px),
    linear-gradient(to bottom, color-mix(in srgb, #fff 42%, transparent) 1px, transparent 1px);
  background-size: 33.333% 33.333%;
  box-shadow: inset 0 0 0 1px color-mix(in srgb, #fff 42%, transparent);
}
/* user:“那个正在预览真实界面那个话，用一个小胶囊，下边不圆角，贴住控件 bar 的上沿，低透玻璃样式”+
   (胶囊挂在工具条外层的正上方，跟着工具条一起拖动；下沿直角并压住 bar 上边 2px，看起来是同一个控件。) */
.studio-canvas-hint {
  position: relative;
  margin: 0 0 -2px;
  padding: 3px 12px 4px;
  border-radius: 10px 10px 0 0;
  border-bottom: 0;
  color: var(--muted, #a7a29b);
  font-size: var(--type-2xs, 10px);
  line-height: 1.4;
  white-space: nowrap;
  pointer-events: none;
}
.studio-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--type-sm, 12px);
}
.studio-field--row { flex-direction: row; align-items: center; justify-content: space-between; }
/* user:“使用统一的组件与样式体系”+(编辑器里的输入框同样走输入区令牌，不自成一套) */
.studio-field input[type='color'] { height: 28px; padding: 0; border: 1px solid color-mix(in srgb, var(--theme-composer-text) 16%, transparent); border-radius: var(--radius-sm, 6px); background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent); }
.studio-field input[type='number'] { height: 28px; padding: 0 8px; border: 1px solid color-mix(in srgb, var(--theme-composer-text) 16%, transparent); border-radius: var(--radius-sm, 6px); background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent); color: var(--theme-composer-text); caret-color: var(--theme-composer-text); }
.studio-secondary {
  margin-top: var(--space-2, 8px);
  min-height: 30px;
  border: 1px solid var(--line, #3b3a38);
  border-radius: var(--radius-sm, 6px);
  background: transparent;
  color: inherit;
  cursor: pointer;
}
.studio-error { margin: 0; color: var(--red, #f5555d); font-size: var(--type-xs, 11px); }
/* 工具条外层：提示胶囊 + 玻璃条一起定位/拖动；默认水平居中贴底。 */
.studio-toolbar-wrap {
  position: absolute;
  left: 50%;
  bottom: var(--space-4, 16px);
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  pointer-events: none;
}
.studio-toolbar {
  position: relative;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  border-radius: 999px;
  color: var(--theme-main-text, #f2efeb);
  pointer-events: auto;
}
/* —— 工具条图标键：每个动作一个独立圆键，不写文字 —— */
.studio-tool-icon {
  width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: inherit;
  cursor: pointer;
}
.studio-tool-icon:hover:not(:disabled) { background: color-mix(in srgb, var(--theme-main-text, #f2efeb) var(--alpha-hover, 8%), transparent); }
.studio-tool-icon:disabled { opacity: 0.35; cursor: default; }
/* 开着的开关用控制反色对填充（设计规范：控制区域唯一填充对）。 */
.studio-tool-icon.is-active {
  background: var(--theme-control-background, #fbf7f0);
  color: var(--theme-control-text, #2e3138);
}
.studio-icon-svg {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.4;
  stroke-linecap: round;
  stroke-linejoin: round;
}
/* user:“确认带反馈动画”+(发布成功打勾后脉冲一次，再把编辑器收起) */
.studio-tool-icon--confirm {
  background: var(--theme-control-background, #fbf7f0);
  color: var(--theme-control-text, #2e3138);
}
.studio-tool-icon--confirm.is-confirmed { animation: studio-confirm-pop 420ms var(--ease-out, ease); }
.studio-tool-icon--confirm .studio-icon-svg { stroke-width: 1.8; }
@keyframes studio-confirm-pop {
  0% { transform: scale(1); }
  38% { transform: scale(1.16); }
  100% { transform: scale(1); }
}
@media (prefers-reduced-motion: reduce) {
  .studio-tool-icon--confirm.is-confirmed { animation: none; }
}
/* 拖动抓手：六点图标，提示整块浮层可拖。 */
.studio-grip {
  width: 14px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  color: var(--muted, #a7a29b);
  cursor: grab;
  touch-action: none;
}
.studio-grip svg { width: 10px; height: 16px; fill: currentColor; }
.studio-grip--bar { height: 18px; }
.studio-head { cursor: grab; touch-action: none; }
.studio-toolbar { touch-action: none; }
.studio-panel.is-dragging,
.studio-toolbar.is-dragging { cursor: grabbing; }
.studio-panel.is-dragging { opacity: 0.94; }
.studio-toolbar-divider {
  width: 1px;
  height: 18px;
  background: color-mix(in srgb, var(--theme-main-text, #f2efeb) 14%, transparent);
}
.studio-edit-mode {
  display: inline-flex;
  align-items: center;
  font-size: var(--type-sm, 12px);
}
.studio-panel-footer {
  display: flex;
  align-items: center;
  gap: 2px;
  padding-top: var(--space-2, 8px);
  border-top: 1px solid color-mix(in srgb, var(--theme-main-text, #f2efeb) 10%, transparent);
}
.studio-size-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr);
  gap: 4px;
  align-items: center;
}
.studio-size-axis { color: var(--muted, #a7a29b); font-size: var(--type-xs, 11px); }
.studio-btn {
  min-height: 28px;
  padding: 0 10px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: inherit;
  font-size: var(--type-sm, 12px);
  cursor: pointer;
}
.studio-btn:hover:not(:disabled) { background: color-mix(in srgb, var(--theme-main-text, #f2efeb) var(--alpha-hover, 8%), transparent); }
.studio-btn:disabled { opacity: 0.4; cursor: default; }
.studio-btn--primary { background: var(--theme-control-background, #fbf7f0); color: var(--theme-control-text, #2e3138); }
.studio-spacer { width: 8px; }
.studio-status { color: var(--muted, #a7a29b); font-size: var(--type-2xs, 10px); }
</style>

