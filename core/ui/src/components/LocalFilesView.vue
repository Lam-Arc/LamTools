<template>
  <div class="library-local-files" data-ui-id="library.local-files" @keydown.esc="onEscape">
    <!-- 引擎状态是产品状态，不是技术日志：故障时明确说、可重试，浏览与资产照常可用。 -->
    <div v-if="status && status.state !== 'ready'" class="lf-banner" role="status">
      <span class="lf-banner-dot" aria-hidden="true" />
      <div class="lf-banner-copy">
        <strong>{{ status.message }}</strong>
        <span v-if="status.hint">{{ status.hint }}</span>
      </div>
      <button
        v-if="status.state === 'missing_cli' && status.can_install"
        type="button"
        class="lf-btn"
        :disabled="engineBusy"
        @click="installEngine"
      >{{ engineBusy ? '下载中…' : '下载查询工具' }}</button>
      <button type="button" class="lf-btn lf-btn-quiet" :disabled="engineBusy" @click="loadStatus(true)">重试</button>
    </div>

    <div class="lf-top">
      <label class="lf-search">
        <span class="lf-search-icon" aria-hidden="true">
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6">
            <circle cx="8.5" cy="8.5" r="5.5" />
            <path d="m13 13 3.5 3.5" stroke-linecap="round" />
          </svg>
        </span>
        <input
          v-model="query"
          type="search"
          placeholder="搜索整台电脑，输入即搜；也可用 size:&gt;1gb、dm:7days"
          aria-label="搜索本机文件"
          @input="onQueryInput"
          @keydown.enter="runSearch(true)"
        >
        <button v-if="query" type="button" class="lf-clear" aria-label="清除搜索" @click="clearQuery">×</button>
      </label>

      <div class="lf-scope" role="group" aria-label="搜索范围">
        <button
          type="button"
          class="lf-scope-btn"
          :class="{ active: !scopeCurrent }"
          @click="setScope(false)"
        >全电脑</button>
        <button
          type="button"
          class="lf-scope-btn"
          :class="{ active: scopeCurrent }"
          :disabled="!browsePath"
          :title="browsePath ? `只在 ${browsePath} 内搜索` : '先进入一个文件夹'"
          @click="setScope(true)"
        >当前目录</button>
      </div>

      <div class="lf-view-switch" role="group" aria-label="展示方式">
        <button type="button" :class="{ active: view === 'list' }" title="紧凑列表" @click="setView('list')">列表</button>
        <button type="button" :class="{ active: view === 'grid' }" title="网格" @click="setView('grid')">网格</button>
        <button type="button" :class="{ active: view === 'waterfall' }" title="瀑布流" @click="setView('waterfall')">瀑布</button>
      </div>
    </div>

    <div class="lf-filter-row">
      <div class="lf-chips" role="group" aria-label="文件类型">
        <button
          v-for="item in KINDS"
          :key="item.value"
          type="button"
          class="lf-chip"
          :class="{ active: kind === item.value }"
          @click="setKind(item.value)"
        >{{ item.label }}</button>
      </div>
      <div class="lf-filter-spacer" />
      <select v-model="sort" class="lf-sort" aria-label="排序" @change="runSearch(true)">
        <option value="relevance">相关度</option>
        <option value="name">名称</option>
        <option value="date_modified">修改时间</option>
        <option value="date_created">创建时间</option>
        <option value="size">大小</option>
      </select>
    </div>

    <div class="lf-shell" :class="{ 'has-preview': previewOpen }">
      <aside class="lf-rail" :class="{ open: railOpen }" aria-label="位置与资产">
        <section class="lf-rail-section">
          <h3>位置</h3>
          <button
            v-for="root in roots"
            :key="root.path"
            type="button"
            class="lf-rail-item"
            :class="{ active: mode === 'browse' && browsePath === root.path }"
            :title="root.path"
            @click="openLocation(root.path)"
          >
            <span class="lf-rail-icon" aria-hidden="true">{{ root.kind === 'drive' ? '▣' : '▸' }}</span>
            <span class="lf-rail-label">{{ root.name }}</span>
          </button>
          <button
            type="button"
            class="lf-rail-item"
            :class="{ active: mode === 'browse' && browsePath === '' }"
            @click="openLocation('')"
          ><span class="lf-rail-icon" aria-hidden="true">⌂</span><span class="lf-rail-label">全部磁盘</span></button>
        </section>

        <section class="lf-rail-section">
          <h3>我的资产</h3>
          <button
            type="button"
            class="lf-rail-item"
            :class="{ active: assetFilter === 'all' }"
            @click="openAssetFilter('all')"
          ><span class="lf-rail-icon" aria-hidden="true">◇</span><span class="lf-rail-label">全部资产</span></button>
          <button
            type="button"
            class="lf-rail-item"
            :class="{ active: assetFilter === 'favorite' }"
            @click="openAssetFilter('favorite')"
          ><span class="lf-rail-icon" aria-hidden="true">★</span><span class="lf-rail-label">收藏</span></button>
          <button
            type="button"
            class="lf-rail-item"
            :class="{ active: assetFilter === 'five' }"
            @click="openAssetFilter('five')"
          ><span class="lf-rail-icon" aria-hidden="true">✦</span><span class="lf-rail-label">四星以上</span></button>
        </section>

        <section class="lf-rail-section">
          <h3 class="lf-rail-heading">
            集合
            <button type="button" class="lf-rail-add" title="新建集合" @click="openDialog('newCollection')">+</button>
          </h3>
          <button
            v-for="collection in collections"
            :key="collection.collection_id"
            type="button"
            class="lf-rail-item"
            :class="{ active: activeCollection?.collection_id === collection.collection_id }"
            :title="collection.kind === 'smart' ? '智能集合：条件自动匹配' : '普通集合'"
            @click="openCollection(collection)"
          >
            <span class="lf-rail-icon" aria-hidden="true">{{ collection.kind === 'smart' ? '⚡' : '▤' }}</span>
            <span class="lf-rail-label">{{ collection.name }}</span>
            <span class="lf-rail-count">{{ collection.count }}</span>
          </button>
          <p v-if="!collections.length" class="lf-rail-empty">把搜到的文件收藏起来，或保存一次搜索。</p>
        </section>
      </aside>

      <section class="lf-main">
        <div v-if="browsePath" class="lf-browse-bar">
          <div class="lf-nav">
            <button type="button" class="lf-icon-btn" title="后退" aria-label="后退" :disabled="!canBack" @click="goBack">
              <svg viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12.5 5 7 10l5.5 5" stroke-linecap="round" stroke-linejoin="round" /></svg>
            </button>
            <button type="button" class="lf-icon-btn" title="前进" aria-label="前进" :disabled="!canForward" @click="goForward">
              <svg viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7"><path d="m7.5 5 5.5 5-5.5 5" stroke-linecap="round" stroke-linejoin="round" /></svg>
            </button>
            <button type="button" class="lf-icon-btn" title="上一级" aria-label="上一级" :disabled="!browsePath" @click="goUp">
              <svg viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7"><path d="m5 12.5 5-5.5 5 5.5" stroke-linecap="round" stroke-linejoin="round" /></svg>
            </button>
          </div>
          <nav class="lf-crumbs" aria-label="路径">
            <button type="button" class="lf-crumb" @click="openLocation('')">本机</button>
            <template v-for="(crumb, index) in crumbs" :key="crumb.path">
              <span class="lf-crumb-sep" aria-hidden="true">›</span>
              <button
                type="button"
                class="lf-crumb"
                :class="{ current: index === crumbs.length - 1 }"
                @click="openLocation(crumb.path)"
              >{{ crumb.label }}</button>
            </template>
          </nav>
        </div>

        <div class="lf-toolbar">
          <button type="button" class="lf-icon-btn lf-rail-toggle" title="位置、资产与集合" @click="railOpen = !railOpen">位置</button>
          <span class="lf-result-summary">
            <template v-if="mode === 'browse'">{{ items.length }} 个项目</template>
            <template v-else-if="total !== null">{{ total.toLocaleString() }} 个结果</template>
            <template v-else>结果数暂不可用</template>
            <template v-if="elapsed"> · {{ elapsed }} ms</template>
          </span>
          <input
            v-if="pathEditing"
            v-model="pathInput"
            class="lf-path-input"
            type="text"
            placeholder="输入路径后回车"
            aria-label="直接输入路径"
            @keydown.enter="submitPath"
            @keydown.esc="pathEditing = false"
          >
          <button v-else type="button" class="lf-btn lf-btn-quiet" title="直接输入路径" @click="pathEditing = true">路径</button>
          <div class="lf-actions">
            <button type="button" class="lf-btn lf-btn-quiet" @click="openDialog('newFile')">新建文件</button>
            <button type="button" class="lf-btn lf-btn-quiet" @click="openDialog('mkdir')">新建文件夹</button>
            <button type="button" class="lf-btn lf-btn-quiet" :disabled="loading" @click="refreshCurrent">
              {{ loading ? '加载中…' : '刷新' }}
            </button>
            <button type="button" class="lf-btn lf-btn-quiet" :disabled="!query && !kindFiltered" @click="saveSmartCollection">保存为集合</button>
          </div>
        </div>

        <!-- 选中后才出现的一条动作；不选中时不占版面、不挤压结果。 -->
        <div v-if="selected.length" class="lf-batchbar" aria-label="批量操作">
          <span class="lf-selection">{{ selected.length }} 已选</span>
          <button type="button" class="lf-btn lf-btn-quiet" @click="batchFavorite">收藏</button>
          <button type="button" class="lf-btn lf-btn-quiet" @click="openDialog('tagBatch')">标签</button>
          <button type="button" class="lf-btn lf-btn-quiet" @click="openCollectionPicker">加入集合</button>
          <button type="button" class="lf-btn lf-btn-quiet" @click="copySelection('copy')">复制</button>
          <button type="button" class="lf-btn lf-btn-quiet" @click="copySelection('cut')">剪切</button>
          <button v-if="selected.length === 1" type="button" class="lf-btn lf-btn-quiet" @click="openDialog('rename')">重命名</button>
          <button type="button" class="lf-btn lf-btn-quiet" @click="openDialog('trash')">删除</button>
          <button
            v-if="clipboard.paths.length"
            type="button"
            class="lf-btn lf-btn-quiet"
            :disabled="!browsePath"
            :title="browsePath ? '粘贴到当前目录' : '先进入目标文件夹'"
            @click="pasteIntoBrowse"
          >粘贴 ({{ clipboard.paths.length }})</button>
          <button type="button" class="lf-btn lf-btn-quiet" @click="selected = []">取消选择</button>
        </div>

        <div v-if="error" class="lf-error" role="alert">
          <span>{{ error }}</span>
          <button type="button" class="lf-btn lf-btn-quiet" @click="refreshCurrent">重试</button>
        </div>

        <div ref="resultsEl" class="lf-results" :class="`lf-results-${view}`" @scroll="onResultsScroll">
          <div v-if="loading && !items.length" class="lf-loading" role="status">
            <span class="lf-spinner" aria-hidden="true" />正在搜索…
          </div>
          <div v-else-if="!items.length" class="lf-empty">
            <p v-if="mode === 'browse'">这个文件夹是空的。</p>
            <p v-else-if="query">没有找到匹配的文件。</p>
            <p v-else>输入关键词开始搜索，或从左侧进入一个磁盘。</p>
          </div>

          <template v-else>
            <div
              v-for="item in items"
              :key="item.path"
              class="lf-item"
              :class="{
                selected: selected.includes(item.path),
                active: activePath === item.path,
                missing: item.missing,
              }"
              :data-path="item.path"
              role="button"
              tabindex="0"
              @click="onItemClick(item, $event)"
              @dblclick="activateItem(item)"
              @keydown.enter="openPreview(item)"
              @keydown.space.prevent="toggleSelect(item.path)"
            >
              <div class="lf-thumb" :data-kind="item.kind">
                <img
                  v-if="thumbs.get(item.path)"
                  :src="thumbs.get(item.path)"
                  :alt="item.name"
                  loading="lazy"
                >
                <span v-else class="lf-thumb-ext">{{ (item.extension || (item.is_dir ? 'DIR' : 'FILE')).toUpperCase().slice(0, 4) }}</span>
              </div>
              <div class="lf-item-main">
                <span class="lf-item-name" :title="item.name">{{ item.asset?.display_name || item.name }}</span>
                <span class="lf-item-dir" :title="item.directory">{{ item.directory }}</span>
              </div>
              <div class="lf-item-meta">
                <span class="lf-size">{{ item.is_dir ? '—' : formatSize(item.size) }}</span>
                <span class="lf-date">{{ formatDate(item.modified_at) }}</span>
              </div>
              <div class="lf-item-marks">
                <span v-if="item.asset?.favorite" class="lf-mark favorite" title="已收藏">★</span>
                <span v-if="item.asset?.rating" class="lf-mark rating">{{ item.asset.rating }}</span>
                <span v-for="tag in (item.asset?.tags || []).slice(0, 2)" :key="tag" class="lf-mark tag">{{ tag }}</span>
                <span v-if="item.missing" class="lf-mark offline">离线</span>
              </div>
            </div>
          </template>

          <div v-if="loading && items.length" class="lf-loading lf-loading-inline" role="status">
            <span class="lf-spinner" aria-hidden="true" />加载更多…
          </div>
          <div v-else-if="items.length && !hasMore && mode !== 'browse'" class="lf-end">已到末尾</div>
        </div>
      </section>

      <aside v-if="previewOpen" class="lf-preview" aria-label="文件预览">
        <header class="lf-preview-head">
          <div class="lf-preview-title" :title="preview?.path || activePath">
            <strong>{{ preview?.name || baseName(activePath) }}</strong>
            <span>{{ preview ? `${formatSize(preview.size)} · ${formatDate(preview.modified_at)}` : '' }}</span>
          </div>
          <div class="lf-preview-actions">
            <button type="button" class="lf-icon-btn" title="用系统程序打开" @click="openActive">打开</button>
            <button type="button" class="lf-icon-btn" title="在资源管理器中定位" @click="revealActive">定位</button>
            <button type="button" class="lf-icon-btn" title="关闭预览" @click="closePreview">×</button>
          </div>
        </header>

        <div class="lf-preview-body">
          <div v-if="previewLoading" class="lf-loading"><span class="lf-spinner" aria-hidden="true" />读取中…</div>
          <div v-else-if="preview?.error" class="lf-empty">{{ preview.error }}</div>
          <template v-else-if="preview">
            <div v-if="preview.kind === 'image' && fullImage" class="lf-image-stage">
              <img :src="fullImage" :alt="preview.name" :style="{ transform: `scale(${zoom})` }" @dblclick="fullscreen = true">
              <div class="lf-image-tools">
                <button type="button" class="lf-icon-btn" @click="zoom = Math.max(0.25, zoom - 0.25)">−</button>
                <span>{{ Math.round(zoom * 100) }}%</span>
                <button type="button" class="lf-icon-btn" @click="zoom = Math.min(4, zoom + 0.25)">+</button>
                <button type="button" class="lf-icon-btn" @click="zoom = 1">适屏</button>
                <button type="button" class="lf-icon-btn" @click="fullscreen = true">全屏</button>
              </div>
            </div>
            <div v-else-if="preview.kind === 'video'" class="lf-media">
              <video v-if="mediaUrl" :src="mediaUrl" controls playsinline />
              <p v-else class="lf-empty">{{ mediaError || '准备播放…' }}</p>
            </div>
            <div v-else-if="preview.kind === 'audio'" class="lf-media lf-audio">
              <audio v-if="mediaUrl" :src="mediaUrl" controls />
              <p v-else class="lf-empty">{{ mediaError || '准备播放…' }}</p>
            </div>
            <iframe
              v-else-if="preview.extension === 'pdf' && mediaUrl"
              class="lf-pdf"
              :src="mediaUrl"
              title="PDF 预览"
            />
            <pre v-else-if="preview.text" class="lf-text">{{ preview.text }}</pre>
            <div v-else-if="preview.is_dir" class="lf-folder-info">
              <p>文件夹 · {{ preview.entry_count ?? 0 }} 个项目</p>
              <button type="button" class="lf-btn" @click="openLocation(preview.path)">进入文件夹</button>
            </div>
            <div v-else class="lf-empty">
              这个格式暂不支持内嵌预览，但仍可打开或定位。
              <p v-if="mediaError" class="lf-hint">{{ mediaError }}</p>
            </div>
          </template>
        </div>

        <footer v-if="preview && !preview.is_dir" class="lf-asset">
          <div class="lf-asset-row">
            <button
              type="button"
              class="lf-star"
              :class="{ on: preview.asset?.favorite }"
              :aria-pressed="Boolean(preview.asset?.favorite)"
              title="收藏"
              @click="toggleFavorite"
            >★</button>
            <div class="lf-stars" role="group" aria-label="评分">
              <button
                v-for="star in 5"
                :key="star"
                type="button"
                class="lf-star"
                :class="{ on: (preview.asset?.rating || 0) >= star }"
                :title="`${star} 星`"
                @click="setRating(star)"
              >★</button>
            </div>
            <span class="lf-asset-hint">{{ preview.asset ? '已纳入资产' : '收藏或评分后成为资产' }}</span>
          </div>
          <label class="lf-field">
            <span>显示名</span>
            <input
              :value="preview.asset?.display_name || ''"
              :placeholder="preview.name"
              @change="patchAsset({ display_name: ($event.target as HTMLInputElement).value })"
            >
          </label>
          <div class="lf-tags">
            <span
              v-for="tag in preview.asset?.tags || []"
              :key="tag"
              class="lf-tag"
            >
              {{ tag }}
              <button type="button" title="移除标签" @click="removeTag(tag)">×</button>
            </span>
            <input
              v-model="tagDraft"
              class="lf-tag-input"
              placeholder="加标签后回车"
              @keydown.enter.prevent="addTag"
            >
          </div>
          <label class="lf-field">
            <span>备注</span>
            <textarea
              rows="2"
              :value="preview.asset?.note || ''"
              @change="patchAsset({ note: ($event.target as HTMLTextAreaElement).value })"
            />
          </label>
          <div v-if="preview.asset?.missing" class="lf-relink">
            <p>文件当前离线或已移动，资产信息仍在。确认原文件后可以重新关联：</p>
            <div class="lf-relink-row">
              <input v-model="relinkPath" type="text" placeholder="原文件的新路径">
              <button type="button" class="lf-btn" :disabled="!relinkPath.trim()" @click="relinkActive">重新关联</button>
            </div>
          </div>
          <div class="lf-asset-footer">
            <span v-if="preview.asset" class="lf-asset-id">{{ preview.asset.identity_kind === 'fileid' ? '身份稳定' : '按路径识别' }}</span>
            <button v-if="preview.asset" type="button" class="lf-link-danger" @click="forgetActive">从资产管理中移除（不删文件）</button>
          </div>
        </footer>
      </aside>
    </div>

    <footer class="lf-statusbar">
      <span class="lf-engine" :data-state="status?.state || 'unknown'">
        <span class="lf-engine-dot" aria-hidden="true" />
        {{ engineLabel }}
      </span>
      <span v-if="status?.indexed_items" class="lf-engine-detail">
        · 索引 {{ Number(status.indexed_items).toLocaleString() }} 项
      </span>
      <span class="lf-status-spacer" />
      <span v-if="message" class="lf-message">{{ message }}</span>
      <span v-if="clipboard.paths.length" class="lf-clipboard">{{ clipboard.op === 'cut' ? '剪切' : '复制' }} {{ clipboard.paths.length }} 项</span>
    </footer>

    <!-- 全屏图片：一次只做一件事，Esc 或点击空白处退出。 -->
    <div v-if="fullscreen && fullImage" class="lf-fullscreen" role="dialog" aria-label="图片全屏" @click.self="fullscreen = false">
      <img :src="fullImage" :alt="preview?.name || ''">
      <button type="button" class="lf-fullscreen-close" @click="fullscreen = false">×</button>
      <button v-if="siblings.length > 1" type="button" class="lf-fullscreen-nav prev" @click="stepSibling(-1)">‹</button>
      <button v-if="siblings.length > 1" type="button" class="lf-fullscreen-nav next" @click="stepSibling(1)">›</button>
    </div>

    <!-- 集合选择：只列名字，不打断当前结果。 -->
    <div v-if="collectionPickerOpen" class="lf-popover" @click.self="collectionPickerOpen = false">
      <div class="lf-popover-card">
        <h3>加入集合</h3>
        <button
          v-for="collection in collections"
          :key="collection.collection_id"
          type="button"
          class="lf-popover-item"
          @click="addSelectionToCollection(collection.collection_id)"
        >{{ collection.name }} <span>{{ collection.count }}</span></button>
        <p v-if="!collections.length" class="lf-rail-empty">还没有集合，先新建一个。</p>
        <button type="button" class="lf-btn lf-btn-quiet" @click="openDialog('newCollectionForSelection')">新建集合并加入</button>
        <button type="button" class="lf-btn lf-btn-quiet" @click="collectionPickerOpen = false">取消</button>
      </div>
    </div>

    <!-- 一次只开一个轻量对话框：重命名、新建、删除、批量标签。 -->
    <div v-if="dialog" class="lf-dialog-backdrop" @click.self="closeDialog">
      <div class="lf-dialog" role="dialog" aria-modal="true">
        <h3>{{ dialogTitle }}</h3>
        <p v-if="dialog === 'trash'" class="lf-dialog-copy">删除到回收站，之后可以从 Windows 回收站还原。</p>
        <p v-if="dialog === 'delete'" class="lf-dialog-copy lf-danger">永久删除后无法从回收站恢复，只对选中的文件生效。</p>
        <p v-if="dialog === 'tagBatch'" class="lf-dialog-copy">给 {{ selected.length }} 个文件加标签，用逗号分隔。</p>
        <input
          v-if="dialog !== 'trash' && dialog !== 'delete'"
          v-model="dialogValue"
          class="lf-dialog-input"
          :placeholder="dialogPlaceholder"
          @keydown.enter="confirmDialog"
        >
        <div class="lf-dialog-actions">
          <button type="button" class="lf-btn lf-btn-quiet" @click="closeDialog">取消</button>
          <button
            type="button"
            class="lf-btn"
            :class="{ 'lf-btn-danger': dialog === 'delete' || dialog === 'trash' }"
            @click="confirmDialog"
          >{{ dialog === 'delete' ? '永久删除' : dialog === 'trash' ? '移到回收站' : '确定' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 本机文件：全盘搜索 + 目录浏览 + 预览 + 资产编辑。
 *
 * 搜索走 Everything（后端 libraryfs.*），浏览走文件系统；两条链路共用
 * 同一个文件身份与资产账本。这里不复制文件、不重建索引，也不把搜索结果
 * 预先写进资产库。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import type { LamToolsTransport, TransportHttpResponse } from '@/transport/index.ts'

type ViewMode = 'list' | 'grid' | 'waterfall'
type Mode = 'search' | 'browse' | 'assets' | 'collection'
type AssetFilter = 'all' | 'favorite' | 'five'
type DialogKind = 'rename' | 'mkdir' | 'newFile' | 'newCollection' | 'newCollectionForSelection' | 'tagBatch' | 'trash' | 'delete'

interface AssetSummary {
  asset_id: string
  display_name: string
  favorite: boolean
  rating: number
  tags: string[]
  note: string
  missing: boolean
  identity_kind?: string
}

interface FileItem {
  path: string
  name: string
  directory: string
  extension: string
  size: number
  modified_at: string
  created_at?: string
  is_dir: boolean
  kind: string
  missing?: boolean
  asset?: AssetSummary | null
}

interface PreviewAsset {
  asset_id?: string
  display_name?: string
  favorite?: boolean
  rating?: number
  tags?: string[]
  note?: string
  missing?: boolean
  identity_kind?: string
}

interface PreviewPayload {
  path: string
  name: string
  kind: string
  extension: string
  mime: string
  size: number
  modified_at: string
  is_dir: boolean
  text?: string
  entry_count?: number
  error?: string
  asset?: PreviewAsset | null
  siblings?: Array<{ path: string; name: string }>
}

interface RootEntry { path: string; name: string; kind: string }
interface CollectionEntry {
  collection_id: string
  name: string
  kind: string
  count: number
  query?: Record<string, unknown>
}

const props = defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
  transport?: LamToolsTransport
}>()

const KINDS = [
  { value: 'all', get label() { return '全部' } },
  { value: 'image', get label() { return '图片' } },
  { value: 'video', get label() { return '视频' } },
  { value: 'audio', get label() { return '音频' } },
  { value: 'document', get label() { return '文档' } },
  { value: 'archive', get label() { return '压缩包' } },
  { value: 'folder', get label() { return '文件夹' } },
]

const status = ref<Record<string, any> | null>(null)
const engineBusy = ref(false)
const roots = ref<RootEntry[]>([])
const collections = ref<CollectionEntry[]>([])
const items = ref<FileItem[]>([])
const total = ref<number | null>(0)
const elapsed = ref(0)
const loading = ref(false)
const error = ref('')
const message = ref('')
const query = ref('')
const kind = ref('all')
const sort = ref('relevance')
const view = ref<ViewMode>('list')
const mode = ref<Mode>('search')
const assetFilter = ref<AssetFilter>('all')
const browsePath = ref('')
const browseParent = ref('')
const pathInput = ref('')
const pathEditing = ref(false)
const railOpen = ref(false)
const scopeCurrent = ref(false)
const activeCollection = ref<CollectionEntry | null>(null)

const selected = ref<string[]>([])
const lastSelectedIndex = ref(-1)
const activePath = ref('')
const preview = ref<PreviewPayload | null>(null)
const previewOpen = ref(false)
const previewLoading = ref(false)
const zoom = ref(1)
const fullscreen = ref(false)
const fullImage = ref('')
const mediaUrl = ref('')
const mediaError = ref('')
let mediaObjectUrl = ''

const tagDraft = ref('')
const relinkPath = ref('')
const clipboard = reactive<{ op: 'copy' | 'cut'; paths: string[] }>({ op: 'copy', paths: [] })
const collectionPickerOpen = ref(false)
const dialog = ref<DialogKind | null>(null)
const dialogValue = ref('')
const smartSave = ref(false)
const thumbs = reactive(new Map<string, string>())
const siblings = ref<Array<{ path: string; name: string }>>([])
const resultsEl = ref<HTMLElement | null>(null)

let searchTimer: number | undefined
let thumbTimer: number | undefined
let thumbQueue: string[] = []
let thumbPending = new Set<string>()
let searchToken = 0
let disposed = false
const history = ref<string[]>([''])
const historyIndex = ref(0)

const canBack = computed(() => historyIndex.value > 0)
const canForward = computed(() => historyIndex.value < history.value.length - 1)
const hasMore = computed(() => mode.value !== 'browse' && (total.value === null || items.value.length < total.value))
const kindFiltered = computed(() => kind.value !== 'all')
const engineLabel = computed(() => {
  const state = status.value?.state
  if (state === 'ready') return 'Everything 索引可用'
  if (state === 'not_running') return 'Everything 未运行'
  if (state === 'missing_cli') return '缺少 Everything 查询工具'
  if (state === 'not_installed') return '未安装 Everything'
  if (state === 'incompatible') return 'Everything 版本不兼容'
  return state ? '搜索暂不可用' : '正在检测搜索索引'
})

const crumbs = computed(() => {
  if (!browsePath.value) return []
  const parts = browsePath.value.replace(/\//g, '\\').split('\\').filter(Boolean)
  const result: Array<{ label: string; path: string }> = []
  let current = ''
  for (const part of parts) {
    current = current ? `${current}\\${part}` : (part.endsWith(':') ? `${part}\\` : part)
    result.push({ label: part, path: current })
  }
  return result
})

const dialogTitle = computed(() => {
  switch (dialog.value) {
    case 'rename': return '重命名'
    case 'mkdir': return '新建文件夹'
    case 'newFile': return '新建文件'
    case 'newCollection':
    case 'newCollectionForSelection': return '新建集合'
    case 'tagBatch': return '批量加标签'
    case 'trash': return '移到回收站'
    case 'delete': return '永久删除'
    default: return ''
  }
})
const dialogPlaceholder = computed(() => {
  if (dialog.value === 'rename') return baseName(activePath.value) || '新名称'
  if (dialog.value === 'mkdir') return '文件夹名称'
  if (dialog.value === 'newFile') return '文件名（含扩展名）'
  if (dialog.value === 'tagBatch') return '初音未来, 海报'
  return '集合名称'
})

function rpc<T = Record<string, any>>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  return props.requestRpc(method, params) as Promise<T>
}

function baseName(path: string): string {
  return path.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || path
}

function formatSize(size: number): string {
  let value = Math.max(0, Number(size) || 0)
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let index = 0
  while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1 }
  return index === 0 ? `${value} B` : `${value.toFixed(1)} ${units[index]}`
}

function formatDate(value: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const now = Date.now()
  const diff = now - date.getTime()
  if (diff >= 0 && diff < 86_400_000) return '今天'
  if (diff >= 0 && diff < 172_800_000) return '昨天'
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

async function loadStatus(refresh = false): Promise<void> {
  try {
    status.value = await rpc('libraryfs.status')
    if (refresh) message.value = '已重新检测搜索索引'
  } catch (err) {
    status.value = { state: 'error', message: `无法读取搜索状态：${String(err)}` }
  }
}

async function installEngine(): Promise<void> {
  engineBusy.value = true
  message.value = '正在下载 Everything 查询工具…'
  try {
    const data = await rpc('libraryfs.setup')
    const installation = (data.installation || {}) as Record<string, any>
    await loadStatus(true)
    if (installation.already_present) {
      message.value = '查询工具已经存在，已重新检测'
    } else {
      message.value = `查询工具已安装到 ${installation.path || '应用数据目录'}`
    }
    if (status.value?.available) await runSearch(true)
    else if (status.value?.state === 'not_running') message.value += '；启动 Everything 后点重试'
  } catch (err) {
    message.value = `下载失败：${String(err)}`
  } finally {
    engineBusy.value = false
  }
}

async function loadRoots(): Promise<void> {
  try {
    const data = await rpc('libraryfs.roots')
    roots.value = (data.roots || []) as RootEntry[]
  } catch {
    roots.value = []
  }
}

async function loadCollections(): Promise<void> {
  try {
    const data = await rpc('libraryfs.collection.list')
    collections.value = (data.collections || []) as CollectionEntry[]
  } catch {
    collections.value = []
  }
}

function onQueryInput(): void {
  if (mode.value !== 'search') {
    mode.value = 'search'
    activeCollection.value = null
    assetFilter.value = 'all'
  }
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => void runSearch(true), 260)
}

function clearQuery(): void {
  query.value = ''
  scopeCurrent.value = false
  mode.value = browsePath.value ? 'browse' : 'search'
  activeCollection.value = null
  assetFilter.value = 'all'
  if (mode.value === 'browse') void loadBrowse(browsePath.value, false)
  else void runSearch(true)
}

function setScope(current: boolean): void {
  if (current && !browsePath.value) return
  scopeCurrent.value = current
  void runSearch(true)
}

function setKind(value: string): void {
  kind.value = value
  mode.value = 'search'
  activeCollection.value = null
  assetFilter.value = 'all'
  void runSearch(true)
}

function setView(next: ViewMode): void {
  view.value = next
}

function currentSpec(): Record<string, unknown> {
  return {
    query: query.value,
    kinds: kind.value === 'all' ? [] : [kind.value],
    scope: scopeCurrent.value ? browsePath.value : '',
    sort: sort.value,
    descending: sort.value === 'date_modified' || sort.value === 'date_created',
  }
}

async function runSearch(reset = true, append = false): Promise<void> {
  if (mode.value === 'browse' && !query.value.trim() && !append) {
    await loadBrowse(browsePath.value, false)
    return
  }
  const token = ++searchToken
  loading.value = true
  error.value = ''
  try {
    const offset = append ? items.value.length : 0
    const data = await rpc('libraryfs.search', {
      ...currentSpec(),
      offset,
      limit: 60,
      only_assets: mode.value === 'assets',
      tags: assetFilter.value === 'all' ? [] : [],
      rating_min: assetFilter.value === 'five' ? 4 : 0,
      favorite_only: assetFilter.value === 'favorite',
    })
    if (disposed || token !== searchToken) return
    const failure = data.error as Record<string, unknown> | undefined
    if (failure) {
      error.value = String(failure.message || failure)
      if (!append) items.value = []
      total.value = 0
      return
    }
    const next = (data.items || []) as FileItem[]
    items.value = append ? [...items.value, ...next] : next
    total.value = data.total === null || data.total === undefined ? null : Number(data.total)
    elapsed.value = Number(data.elapsed_ms || 0)
    if (!append) {
      selected.value = []
      lastSelectedIndex.value = -1
      scheduleThumbs(items.value)
      if (resultsEl.value) resultsEl.value.scrollTop = 0
    } else {
      scheduleThumbs(next)
    }
  } catch (err) {
    if (token !== searchToken) return
    error.value = `搜索失败：${String(err)}`
    if (!append) items.value = []
  } finally {
    if (token === searchToken) loading.value = false
  }
}

async function loadBrowse(path: string, pushHistory = true): Promise<void> {
  searchToken += 1
  loading.value = true
  error.value = ''
  mode.value = 'browse'
  activeCollection.value = null
  try {
    const data = await rpc('libraryfs.browse', { path, sort: 'name', limit: 1200 })
    if (disposed) return
    if (data.error) {
      error.value = String(data.error)
      items.value = []
      return
    }
    browsePath.value = String(data.path || path || '')
    browseParent.value = String(data.parent || '')
    pathInput.value = browsePath.value
    const entries = (data.entries || []) as FileItem[]
    items.value = entries.filter(entry => !(entry as any).error)
    total.value = items.value.length
    elapsed.value = 0
    selected.value = []
    scheduleThumbs(items.value)
    if (pushHistory) {
      const trimmed = history.value.slice(0, historyIndex.value + 1)
      if (trimmed[trimmed.length - 1] !== browsePath.value) trimmed.push(browsePath.value)
      history.value = trimmed
      historyIndex.value = trimmed.length - 1
    }
  } catch (err) {
    error.value = `无法打开文件夹：${String(err)}`
  } finally {
    loading.value = false
  }
}

function openLocation(path: string): void {
  railOpen.value = false
  pathEditing.value = false
  if (!path) {
    browsePath.value = ''
    browseParent.value = ''
    pathInput.value = ''
    mode.value = 'search'
    items.value = []
    total.value = 0
    if (resultsEl.value) resultsEl.value.scrollTop = 0
    void runSearch(true)
    return
  }
  query.value = ''
  scopeCurrent.value = false
  void loadBrowse(path)
}

function submitPath(): void {
  const value = pathInput.value.trim()
  if (value) openLocation(value)
  pathEditing.value = false
}

function goBack(): void {
  if (!canBack.value) return
  historyIndex.value -= 1
  void loadBrowse(history.value[historyIndex.value] || '', false)
}

function goForward(): void {
  if (!canForward.value) return
  historyIndex.value += 1
  void loadBrowse(history.value[historyIndex.value] || '', false)
}

function goUp(): void {
  if (!browsePath.value) return
  openLocation(browseParent.value)
}

function refreshCurrent(): void {
  if (mode.value === 'browse') void loadBrowse(browsePath.value, false)
  else if (mode.value === 'collection' && activeCollection.value) void openCollection(activeCollection.value)
  else if (mode.value === 'assets') void loadAssetFilter(assetFilter.value)
  else void runSearch(true)
}

function openAssetFilter(filter: AssetFilter): void {
  assetFilter.value = filter
  mode.value = 'assets'
  activeCollection.value = null
  query.value = ''
  browsePath.value = ''
  void loadAssetFilter(filter)
}

async function loadAssetFilter(filter: AssetFilter): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const data = await rpc('libraryfs.asset.list', {
      favorite_only: filter === 'favorite',
      rating_min: filter === 'five' ? 4 : 0,
      sort: 'recent',
      limit: 200,
      refresh: true,
    })
    items.value = (data.assets || []).map(assetAsItem)
    total.value = Number(data.total || items.value.length)
    elapsed.value = 0
    selected.value = []
    scheduleThumbs(items.value)
  } catch (err) {
    error.value = `读取资产失败：${String(err)}`
  } finally {
    loading.value = false
  }
}

function assetAsItem(record: Record<string, any>): FileItem {
  const path = String(record.path || '')
  return {
    path,
    name: String(record.name || baseName(path)),
    directory: path.replace(/[\\/][^\\/]+$/, ''),
    extension: String(record.extension || ''),
    size: Number(record.size || 0),
    modified_at: record.mtime_ns ? new Date(Number(record.mtime_ns) / 1e6).toISOString() : '',
    is_dir: Boolean(record.is_dir),
    kind: String(record.kind || kindFromExtension(record.extension, Boolean(record.is_dir))),
    missing: Boolean(record.missing),
    asset: (record.asset as AssetSummary | undefined) ?? {
      asset_id: record.asset_id,
      display_name: record.display_name || '',
      favorite: Boolean(record.favorite),
      rating: Number(record.rating || 0),
      tags: Array.isArray(record.tags) ? record.tags : [],
      note: record.note || '',
      missing: Boolean(record.missing),
      identity_kind: record.identity_kind,
    },
  }
}

function kindFromExtension(extension: unknown, isDir: boolean): string {
  if (isDir) return 'folder'
  const value = String(extension || '').toLowerCase()
  if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'avif', 'svg', 'tif', 'tiff', 'ico'].includes(value)) return 'image'
  if (['mp4', 'mkv', 'avi', 'mov', 'wmv', 'webm'].includes(value)) return 'video'
  if (['mp3', 'wav', 'flac', 'm4a', 'ogg'].includes(value)) return 'audio'
  return 'document'
}

async function openCollection(collection: CollectionEntry): Promise<void> {
  activeCollection.value = collection
  mode.value = 'collection'
  loading.value = true
  error.value = ''
  try {
    const data = await rpc('libraryfs.collection.items', {
      collection_id: collection.collection_id,
      limit: 300,
      offset: 0,
    })
    items.value = (data.items || []) as FileItem[]
    total.value = Number(data.total || items.value.length)
    selected.value = []
    scheduleThumbs(items.value)
    if (resultsEl.value) resultsEl.value.scrollTop = 0
  } catch (err) {
    error.value = `读取集合失败：${String(err)}`
  } finally {
    loading.value = false
  }
}

async function onItemClick(item: FileItem, event: MouseEvent): Promise<void> {
  if (event.ctrlKey || event.metaKey) {
    toggleSelect(item.path)
    return
  }
  if (event.shiftKey && lastSelectedIndex.value >= 0) {
    const index = items.value.findIndex(entry => entry.path === item.path)
    if (index >= 0) {
      const [start, end] = [lastSelectedIndex.value, index].sort((a, b) => a - b)
      selected.value = items.value.slice(start, end + 1).map(entry => entry.path)
    }
    return
  }
  selected.value = [item.path]
  lastSelectedIndex.value = items.value.findIndex(entry => entry.path === item.path)
  await openPreview(item)
}

function toggleSelect(path: string): void {
  const index = selected.value.indexOf(path)
  if (index >= 0) selected.value.splice(index, 1)
  else selected.value.push(path)
  lastSelectedIndex.value = items.value.findIndex(entry => entry.path === path)
}

async function activateItem(item: FileItem): Promise<void> {
  if (item.is_dir) {
    openLocation(item.path)
    return
  }
  await openPreview(item)
  await openActive()
}

async function openPreview(item: FileItem): Promise<void> {
  activePath.value = item.path
  previewOpen.value = true
  previewLoading.value = true
  preview.value = null
  zoom.value = 1
  fullImage.value = ''
  releaseMedia()
  mediaError.value = ''
  tagDraft.value = ''
  relinkPath.value = ''
  try {
    const data = await rpc<PreviewPayload>('libraryfs.preview', { path: item.path })
    if (disposed || activePath.value !== item.path) return
    const asset = (data.asset as PreviewAsset | null) ?? (item.asset as PreviewAsset | null) ?? null
    preview.value = { ...data, asset }
    siblings.value = data.siblings || []
    if (data.kind === 'image') await loadFullImage(item.path)
    if (['video', 'audio'].includes(data.kind) || data.extension === 'pdf') await loadMedia(data)
  } catch (err) {
    preview.value = { path: item.path, name: item.name, kind: 'other', extension: '', mime: '', size: 0, modified_at: '', is_dir: false, error: String(err) }
  } finally {
    previewLoading.value = false
  }
}

async function loadFullImage(path: string): Promise<void> {
  try {
    const data = await rpc('libraryfs.thumbs', { paths: [path], size: 1600 })
    const first = (data.items || [])[0] as Record<string, any> | undefined
    if (!first?.data) return
    fullImage.value = `data:${first.mime || 'image/jpeg'};base64,${first.data}`
  } catch {
    fullImage.value = ''
  }
}

async function loadMedia(payload: PreviewPayload): Promise<void> {
  if (!props.transport) {
    mediaError.value = '当前连接不支持媒体播放，请用系统程序打开。'
    return
  }
  if (payload.size > 80 * 1024 * 1024) {
    mediaError.value = '文件超过 80 MB，请用系统程序打开。'
    return
  }
  try {
    const response = await props.transport.request<TransportHttpResponse>({
      kind: 'http',
      method: 'GET',
      path: `/library/raw?path=${encodeURIComponent(payload.path)}`,
      timeoutMs: 20_000,
    })
    if (response.status < 200 || response.status >= 300) {
      mediaError.value = '无法读取这个文件'
      return
    }
    releaseMedia()
    const type = response.headers['content-type'] || payload.mime || 'application/octet-stream'
    mediaObjectUrl = URL.createObjectURL(new Blob([Uint8Array.from(response.body)], { type }))
    mediaUrl.value = mediaObjectUrl
  } catch (err) {
    mediaError.value = String(err)
  }
}

function releaseMedia(): void {
  mediaUrl.value = ''
  if (mediaObjectUrl) {
    URL.revokeObjectURL(mediaObjectUrl)
    mediaObjectUrl = ''
  }
}

function closePreview(): void {
  previewOpen.value = false
  activePath.value = ''
  preview.value = null
  fullscreen.value = false
  releaseMedia()
}

function stepSibling(direction: number): void {
  if (!preview.value || siblings.value.length < 2) return
  const current = siblings.value.findIndex(item => item.path === preview.value?.path)
  const next = siblings.value[(current + direction + siblings.value.length) % siblings.value.length]
  if (!next) return
  const item = items.value.find(entry => entry.path === next.path) || assetAsItem({ path: next.path, name: next.name })
  void openPreview(item)
  fullscreen.value = true
}

function scheduleThumbs(list: FileItem[]): void {
  for (const item of list) {
    if (!item.path || item.is_dir || item.kind !== 'image' || thumbs.has(item.path) || thumbPending.has(item.path)) continue
    if (thumbs.size + thumbPending.size >= 240) break
    thumbPending.add(item.path)
    thumbQueue.push(item.path)
  }
  if (thumbTimer) window.clearTimeout(thumbTimer)
  thumbTimer = window.setTimeout(() => void flushThumbs(), 60)
}

async function flushThumbs(): Promise<void> {
  const batch = thumbQueue.splice(0, 36)
  if (!batch.length) return
  try {
    const data = await rpc('libraryfs.thumbs', { paths: batch, size: 320 })
    for (const entry of (data.items || []) as Array<Record<string, any>>) {
      thumbPending.delete(String(entry.path))
      if (entry.data) thumbs.set(String(entry.path), `data:${entry.mime || 'image/jpeg'};base64,${entry.data}`)
    }
  } catch {
    for (const path of batch) thumbPending.delete(path)
  }
  if (thumbQueue.length) thumbTimer = window.setTimeout(() => void flushThumbs(), 40)
}

function onResultsScroll(): void {
  const element = resultsEl.value
  if (!element || loading.value || !hasMore.value) return
  if (element.scrollTop + element.clientHeight >= element.scrollHeight - 240) {
    void runSearch(false, true)
  }
}

function onEscape(): void {
  if (fullscreen.value) { fullscreen.value = false; return }
  if (dialog.value) { closeDialog(); return }
  if (collectionPickerOpen.value) { collectionPickerOpen.value = false; return }
  if (previewOpen.value) closePreview()
}

async function updateAssetOnItem(path: string, patch: Record<string, unknown>): Promise<void> {
  const data = await rpc('libraryfs.asset.update', { path, ...patch })
  const asset = data.asset as Record<string, any> | undefined
  if (!asset) return
  const summary: AssetSummary = {
    asset_id: String(asset.asset_id || ''),
    display_name: String(asset.display_name || ''),
    favorite: Boolean(asset.favorite),
    rating: Number(asset.rating || 0),
    tags: Array.isArray(asset.tags) ? asset.tags as string[] : [],
    note: String(asset.note || ''),
    missing: Boolean(asset.missing),
    identity_kind: String(asset.identity_kind || ''),
  }
  const item = items.value.find(entry => entry.path === path)
  if (item) item.asset = summary
  if (preview.value && preview.value.path === path) {
    preview.value.asset = { ...(preview.value.asset || {}), ...summary }
  }
}

async function patchAsset(patch: Record<string, unknown>): Promise<void> {
  if (!preview.value) return
  try {
    await updateAssetOnItem(preview.value.path, patch)
    message.value = '资产信息已保存'
  } catch (err) {
    message.value = `保存失败：${String(err)}`
  }
}

async function toggleFavorite(): Promise<void> {
  if (!preview.value) return
  await patchAsset({ favorite: !preview.value.asset?.favorite })
}

async function setRating(star: number): Promise<void> {
  if (!preview.value) return
  const current = Number(preview.value.asset?.rating || 0)
  await patchAsset({ rating: current === star ? 0 : star })
}

async function addTag(): Promise<void> {
  const value = tagDraft.value.trim()
  if (!value || !preview.value) return
  tagDraft.value = ''
  await patchAsset({ add_tags: [value] })
}

async function removeTag(tag: string): Promise<void> {
  await patchAsset({ remove_tags: [tag] })
}

async function relinkActive(): Promise<void> {
  if (!preview.value?.asset?.asset_id || !relinkPath.value.trim()) return
  try {
    const data = await rpc('libraryfs.asset.relink', {
      asset_id: preview.value.asset.asset_id,
      path: relinkPath.value.trim(),
    })
    const asset = data.asset as Record<string, any> | undefined
    if (asset) {
      preview.value.path = String(asset.path || preview.value.path)
      preview.value.asset = { ...(preview.value.asset || {}), ...asset, missing: false }
      await runSearch(true)
    }
    relinkPath.value = ''
    message.value = '已重新关联'
  } catch (err) {
    message.value = `重新关联失败：${String(err)}`
  }
}

async function forgetActive(): Promise<void> {
  if (!preview.value?.asset?.asset_id) return
  try {
    await rpc('libraryfs.asset.forget', { asset_ids: [preview.value.asset.asset_id] })
    const item = items.value.find(entry => entry.path === preview.value?.path)
    if (item) item.asset = null
    preview.value.asset = null
    message.value = '已移除资产记录，磁盘文件未改动'
    await loadCollections()
  } catch (err) {
    message.value = `移除失败：${String(err)}`
  }
}

async function batchFavorite(): Promise<void> {
  if (!selected.value.length) return
  try {
    for (const path of selected.value.slice(0, 200)) {
      await updateAssetOnItem(path, { favorite: true })
    }
    message.value = `已收藏 ${selected.value.length} 项`
    await loadCollections()
  } catch (err) {
    message.value = `批量收藏失败：${String(err)}`
  }
}

async function batchTag(): Promise<void> {
  const tags = dialogValue.value.split(/[,，]/).map(tag => tag.trim()).filter(Boolean)
  if (!tags.length) return
  for (const path of selected.value.slice(0, 200)) {
    await updateAssetOnItem(path, { add_tags: tags })
  }
  message.value = `已给 ${selected.value.length} 项加标签`
  closeDialog()
}

function copySelection(op: 'copy' | 'cut'): void {
  clipboard.op = op
  clipboard.paths = [...selected.value]
  message.value = `${op === 'cut' ? '剪切' : '复制'}了 ${clipboard.paths.length} 项，进入目标文件夹后粘贴`
}

async function pasteIntoBrowse(): Promise<void> {
  if (!clipboard.paths.length || !browsePath.value) return
  try {
    const data = await rpc('libraryfs.file.operate', {
      op: clipboard.op === 'cut' ? 'move' : 'copy',
      paths: clipboard.paths,
      target_dir: browsePath.value,
      conflict: 'rename',
    })
    message.value = operationMessage(data)
    if (data.failed) await refreshCurrent()
    else {
      clipboard.paths = clipboard.op === 'cut' ? [] : clipboard.paths
      await refreshCurrent()
    }
  } catch (err) {
    message.value = `粘贴失败：${String(err)}`
  }
}

function operationMessage(data: Record<string, any>): string {
  const failed = Number(data.failed || 0)
  const skipped = Number(data.skipped || 0)
  const ok = Number(data.ok || 0)
  const firstFailure = (data.items || []).find((item: Record<string, any>) => item.status === 'failed')
  return `完成 ${ok} 项${skipped ? `，跳过 ${skipped} 项` : ''}${failed ? `，失败 ${failed} 项：${firstFailure?.message || ''}` : ''}`
}

function openDialog(next: DialogKind): void {
  if (next !== 'newCollection') smartSave.value = false
  dialog.value = next
  dialogValue.value = next === 'rename' ? baseName(activePath.value || selected.value[0] || '') : ''
  if (next === 'tagBatch') dialogValue.value = ''
}

function closeDialog(): void {
  dialog.value = null
  dialogValue.value = ''
  smartSave.value = false
}

async function confirmDialog(): Promise<void> {
  const action = dialog.value
  if (!action) return
  if (action === 'tagBatch') {
    await batchTag()
    return
  }
  if (action === 'trash' || action === 'delete') {
    await deleteSelected(action === 'delete')
    closeDialog()
    return
  }
  if (action === 'mkdir' || action === 'newFile') {
    const name = dialogValue.value.trim()
    if (!name) return
    const base = browsePath.value || (activePath.value ? activePath.value.replace(/[\\/][^\\/]+$/, '') : '')
    if (!base) { message.value = '请先进入一个文件夹'; closeDialog(); return }
    const target = `${base.replace(/[\\/]+$/, '')}\\${name}`
    await operate({ op: action === 'newFile' ? 'touch' : 'mkdir', paths: [target] })
    closeDialog()
    return
  }
  if (action === 'rename') {
    const target = activePath.value || selected.value[0]
    const name = dialogValue.value.trim()
    if (target && name) await operate({ op: 'rename', paths: [target], new_name: name, conflict: 'rename' })
    closeDialog()
    return
  }
  if (action === 'newCollection' || action === 'newCollectionForSelection') {
    const name = dialogValue.value.trim()
    if (!name) return
    const smart = smartSave.value && action === 'newCollection'
    try {
      const data = await rpc('libraryfs.collection.create', {
        name,
        kind: smart ? 'smart' : 'manual',
        query: smart
          ? { ...currentSpec(), kinds: kind.value === 'all' ? [] : [kind.value] }
          : {},
      })
      const collection = data.collection as CollectionEntry | undefined
      await loadCollections()
      if (action === 'newCollectionForSelection' && collection) {
        await addSelectionToCollection(collection.collection_id)
      }
      message.value = smart ? `已保存智能集合「${name}」` : `已创建集合「${name}」`
    } catch (err) {
      message.value = `创建集合失败：${String(err)}`
    }
    smartSave.value = false
    closeDialog()
  }
}

async function deleteSelected(permanent: boolean): Promise<void> {
  if (!selected.value.length) return
  await operate({
    op: permanent ? 'delete' : 'trash',
    paths: [...selected.value],
    confirm: permanent,
  })
}

async function operate(payload: Record<string, unknown>): Promise<void> {
  try {
    const data = await rpc('libraryfs.file.operate', payload)
    message.value = operationMessage(data)
    selected.value = []
    if (String(payload.op || '') !== 'copy' && previewOpen.value) closePreview()
    await refreshCurrent()
    await loadCollections()
  } catch (err) {
    message.value = `操作失败：${String(err)}`
  }
}

function openCollectionPicker(): void {
  if (!selected.value.length) return
  collectionPickerOpen.value = true
}

async function addSelectionToCollection(collectionId: string): Promise<void> {
  try {
    const data = await rpc('libraryfs.collection.add', {
      collection_id: collectionId,
      paths: selected.value,
    })
    message.value = `已加入集合：${Number(data.added || 0)} 项`
    collectionPickerOpen.value = false
    await loadCollections()
  } catch (err) {
    message.value = `加入集合失败：${String(err)}`
  }
}

async function saveSmartCollection(): Promise<void> {
  if (!query.value.trim() && !kindFiltered.value) return
  smartSave.value = true
  openDialog('newCollection')
}

async function openActive(): Promise<void> {
  if (!activePath.value) return
  try {
    await rpc('libraryfs.open', { path: activePath.value })
  } catch (err) {
    message.value = `打开失败：${String(err)}`
  }
}

async function revealActive(): Promise<void> {
  if (!activePath.value) return
  try {
    await rpc('libraryfs.reveal', { path: activePath.value })
  } catch (err) {
    message.value = `定位失败：${String(err)}`
  }
}

watch(() => selected.value.length, (length) => {
  if (length === 1) activePath.value = selected.value[0]
})

onMounted(() => {
  void loadStatus()
  void loadRoots()
  void loadCollections()
  void runSearch(true)
})

onBeforeUnmount(() => {
  disposed = true
  if (searchTimer) window.clearTimeout(searchTimer)
  if (thumbTimer) window.clearTimeout(thumbTimer)
  releaseMedia()
})
</script>

<style scoped>
.library-local-files {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  min-height: 0;
  height: 100%;
  color: var(--theme-main-text, var(--text));
}

.lf-banner {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius, 10px);
  background: color-mix(in srgb, var(--theme-main-text, var(--text)) 5%, transparent);
  font-size: 12px;
}
.lf-banner-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--orange, #d99a2b); flex: 0 0 auto; }
.lf-banner-copy { display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: baseline; min-width: 0; }
.lf-banner-copy strong { font-weight: 600; }
.lf-banner-copy span { color: color-mix(in srgb, var(--theme-main-text, var(--text)) 60%, transparent); }

.lf-top { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }
.lf-search {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 1 1 360px;
  min-width: 220px;
  padding: 0 var(--space-2);
  border-radius: 999px;
  background: color-mix(in srgb, var(--theme-control-background, var(--panel-2)) 72%, transparent);
  border: 1px solid color-mix(in srgb, var(--theme-main-text, var(--text)) 10%, transparent);
}
.lf-search:focus-within { border-color: color-mix(in srgb, var(--blue, #4c8dff) 55%, transparent); }
.lf-search-icon { width: 16px; height: 16px; flex: 0 0 auto; opacity: .6; }
.lf-search-icon svg { width: 100%; height: 100%; }
.lf-search input {
  flex: 1 1 auto;
  min-width: 0;
  border: 0;
  background: transparent;
  padding: var(--space-2) 0;
  font-size: 13px;
}
.lf-search input:focus { outline: none; }
.lf-clear { width: 22px; height: 22px; border-radius: 50%; font-size: 15px; line-height: 1; opacity: .6; }
.lf-clear:hover { background: color-mix(in srgb, var(--theme-main-text, var(--text)) 8%, transparent); opacity: 1; }

.lf-scope, .lf-view-switch { display: inline-flex; padding: 2px; gap: 2px; border-radius: 999px; background: color-mix(in srgb, var(--theme-main-text, var(--text)) 5%, transparent); }
.lf-scope-btn, .lf-view-switch button {
  padding: 4px 10px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  font-size: 12px;
  color: color-mix(in srgb, var(--theme-main-text, var(--text)) 70%, transparent);
  white-space: nowrap;
}
.lf-scope-btn:disabled { opacity: .4; cursor: default; }
.lf-scope-btn.active, .lf-view-switch button.active {
  background: color-mix(in srgb, var(--theme-main-background, var(--bg)) 86%, transparent);
  color: var(--theme-main-text, var(--text));
  box-shadow: 0 1px 2px rgb(0 0 0 / 8%);
}

.lf-filter-row { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }
.lf-chips { display: flex; gap: 4px; flex-wrap: wrap; }
.lf-chip { padding: 3px 9px; border: 0; border-radius: 999px; font-size: 12px; line-height: 1.5; white-space: nowrap; background: transparent; color: color-mix(in srgb, var(--theme-main-text, var(--text)) 66%, transparent); }
.lf-chip:hover { background: color-mix(in srgb, var(--theme-main-text, var(--text)) 6%, transparent); }
.lf-chip.active { background: color-mix(in srgb, var(--blue, #4c8dff) 16%, transparent); color: var(--blue, #4c8dff); }
.lf-filter-spacer { flex: 1 1 auto; }
.lf-sort { width: 96px; font-size: 12px; padding: 4px 8px; border-radius: 8px; }

.lf-shell { display: grid; grid-template-columns: 196px minmax(0, 1fr); gap: var(--space-2); flex: 1 1 auto; min-height: 0; }
.lf-shell.has-preview { grid-template-columns: 196px minmax(0, 1fr) minmax(300px, 370px); }

.lf-rail { display: flex; flex-direction: column; gap: var(--space-3); overflow: auto; padding-right: 2px; }
.lf-rail-section { display: flex; flex-direction: column; gap: 1px; }
.lf-rail-section h3 { margin: 0 0 4px; font-size: 11px; font-weight: 600; letter-spacing: .04em; color: color-mix(in srgb, var(--theme-main-text, var(--text)) 45%, transparent); display: flex; align-items: center; justify-content: space-between; }
.lf-rail-heading { text-transform: none; }
.lf-rail-add { width: 18px; height: 18px; border-radius: 5px; font-size: 14px; line-height: 1; opacity: .7; }
.lf-rail-add:hover { background: color-mix(in srgb, var(--theme-main-text, var(--text)) 8%, transparent); opacity: 1; }
.lf-rail-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 7px;
  border-radius: 7px;
  border: 0;
  background: transparent;
  font-size: 12px;
  text-align: left;
  color: color-mix(in srgb, var(--theme-main-text, var(--text)) 72%, transparent);
  min-width: 0;
}
.lf-rail-item:hover { background: color-mix(in srgb, var(--theme-main-text, var(--text)) 6%, transparent); color: var(--theme-main-text, var(--text)); }
.lf-rail-item.active { background: color-mix(in srgb, var(--blue, #4c8dff) 12%, transparent); color: var(--theme-main-text, var(--text)); }
.lf-rail-icon { width: 14px; text-align: center; opacity: .55; flex: 0 0 auto; }
.lf-rail-label { flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lf-rail-count { font-size: 10px; opacity: .5; font-variant-numeric: tabular-nums; }
.lf-rail-empty { margin: 2px 7px; font-size: 11px; line-height: 1.5; color: color-mix(in srgb, var(--theme-main-text, var(--text)) 45%, transparent); }

.lf-main { display: flex; flex-direction: column; min-width: 0; min-height: 0; gap: var(--space-2); }
.lf-browse-bar { display: flex; align-items: center; gap: var(--space-2); min-width: 0; }
.lf-nav { display: flex; gap: 2px; flex: 0 0 auto; }
.lf-icon-btn { min-width: 26px; height: 26px; padding: 0 6px; border: 0; border-radius: 6px; font-size: 14px; line-height: 1; color: inherit; opacity: .7; background: transparent; }
.lf-icon-btn svg { width: 14px; height: 14px; display: block; }
.lf-icon-btn:hover { background: color-mix(in srgb, var(--theme-main-text, var(--text)) 8%, transparent); opacity: 1; }
.lf-icon-btn:disabled { opacity: .25; cursor: default; }
.lf-crumbs { display: flex; align-items: center; gap: 2px; min-width: 0; overflow: auto hidden; flex: 1 1 auto; }
.lf-crumb { font-size: 12px; padding: 2px 4px; border: 0; border-radius: 5px; background: transparent; color: color-mix(in srgb, var(--theme-main-text, var(--text)) 58%, transparent); white-space: nowrap; }
.lf-crumb:hover { background: color-mix(in srgb, var(--theme-main-text, var(--text)) 7%, transparent); }
.lf-crumb.current { color: var(--theme-main-text, var(--text)); }
.lf-crumb-sep { font-size: 11px; opacity: .3; }
.lf-path-input { flex: 0 1 220px; font-size: 11px; padding: 4px 7px; border-radius: 7px; }

.lf-toolbar { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; min-height: 24px; }
.lf-rail-toggle { display: none; }
.lf-result-summary { font-size: 11px; color: color-mix(in srgb, var(--theme-main-text, var(--text)) 55%, transparent); font-variant-numeric: tabular-nums; }
.lf-selection { font-size: 11px; color: var(--blue, #4c8dff); white-space: nowrap; }
.lf-actions { display: flex; gap: 4px; flex-wrap: wrap; margin-left: auto; }
.lf-batchbar {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  padding: 3px 6px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--blue, #4c8dff) 7%, transparent);
}
.lf-btn { padding: 4px 9px; border: 0; border-radius: 7px; font-size: 12px; background: color-mix(in srgb, var(--theme-main-text, var(--text)) 8%, transparent); }
.lf-btn:hover { background: color-mix(in srgb, var(--theme-main-text, var(--text)) 13%, transparent); }
.lf-btn:disabled { opacity: .35; cursor: default; }
.lf-btn-quiet { background: transparent; color: color-mix(in srgb, var(--theme-main-text, var(--text)) 68%, transparent); }
.lf-btn-danger { background: color-mix(in srgb, var(--red, #d9534f) 16%, transparent); color: var(--red, #d9534f); }

.lf-error { display: flex; align-items: center; gap: var(--space-2); padding: 6px 8px; border-radius: 7px; font-size: 12px; background: color-mix(in srgb, var(--red, #d9534f) 9%, transparent); color: var(--red, #d9534f); }

.lf-results { flex: 1 1 auto; overflow: auto; min-height: 0; padding-right: 2px; }
.lf-loading, .lf-empty, .lf-end { padding: var(--space-4); text-align: center; font-size: 12px; color: color-mix(in srgb, var(--theme-main-text, var(--text)) 48%, transparent); }
.lf-loading { display: flex; align-items: center; justify-content: center; gap: 6px; }
.lf-loading-inline { padding: var(--space-3); }
.lf-spinner { width: 12px; height: 12px; border-radius: 50%; border: 1.5px solid color-mix(in srgb, var(--theme-main-text, var(--text)) 22%, transparent); border-top-color: var(--theme-main-text, var(--text)); animation: lf-spin .7s linear infinite; }
@keyframes lf-spin { to { transform: rotate(360deg); } }

.lf-item { display: flex; align-items: center; gap: var(--space-2); padding: 5px 7px; border-radius: 7px; cursor: default; min-width: 0; }
.lf-item:hover { background: color-mix(in srgb, var(--theme-main-text, var(--text)) 5%, transparent); }
.lf-item.selected { background: color-mix(in srgb, var(--blue, #4c8dff) 12%, transparent); }
.lf-item.active { box-shadow: inset 2px 0 0 var(--blue, #4c8dff); }
.lf-item.missing { opacity: .55; }
.lf-thumb { width: 34px; height: 34px; flex: 0 0 auto; border-radius: 6px; background: color-mix(in srgb, var(--theme-main-text, var(--text)) 7%, transparent); display: flex; align-items: center; justify-content: center; overflow: hidden; }
.lf-thumb img { width: 100%; height: 100%; object-fit: cover; }
.lf-thumb-ext { font-size: 8px; font-weight: 700; letter-spacing: .03em; color: color-mix(in srgb, var(--theme-main-text, var(--text)) 52%, transparent); }
.lf-item-main { display: flex; flex-direction: column; min-width: 0; flex: 1 1 auto; }
.lf-item-name { font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lf-item-dir { font-size: 10.5px; color: color-mix(in srgb, var(--theme-main-text, var(--text)) 45%, transparent); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lf-item-meta { display: flex; gap: var(--space-3); font-size: 11px; color: color-mix(in srgb, var(--theme-main-text, var(--text)) 48%, transparent); font-variant-numeric: tabular-nums; }
.lf-size { min-width: 52px; text-align: right; }
.lf-date { min-width: 70px; text-align: right; }
.lf-item-marks { display: flex; gap: 3px; align-items: center; flex: 0 0 auto; }
.lf-mark { font-size: 10px; padding: 1px 5px; border-radius: 999px; background: color-mix(in srgb, var(--theme-main-text, var(--text)) 7%, transparent); color: color-mix(in srgb, var(--theme-main-text, var(--text)) 62%, transparent); }
.lf-mark.favorite { color: var(--orange, #d99a2b); background: color-mix(in srgb, var(--orange, #d99a2b) 12%, transparent); }
.lf-mark.rating { color: var(--orange, #d99a2b); }
.lf-mark.offline { color: var(--red, #d9534f); }

.lf-results-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(132px, 1fr)); gap: var(--space-2); align-content: start; }
.lf-results-grid .lf-item { flex-direction: column; align-items: stretch; padding: 6px; gap: 4px; }
.lf-results-grid .lf-thumb { width: 100%; height: 96px; }
.lf-results-grid .lf-item-dir, .lf-results-grid .lf-item-meta { display: none; }
.lf-results-grid .lf-item-name { font-size: 11.5px; }
.lf-results-grid .lf-item-marks { min-height: 16px; }

.lf-results-waterfall { columns: 4 180px; column-gap: var(--space-2); }
.lf-results-waterfall .lf-item { break-inside: avoid; flex-direction: column; align-items: stretch; padding: 4px; margin-bottom: var(--space-2); background: color-mix(in srgb, var(--theme-main-text, var(--text)) 4%, transparent); }
.lf-results-waterfall .lf-thumb { width: 100%; height: auto; min-height: 90px; max-height: 320px; }
.lf-results-waterfall .lf-thumb img { height: auto; max-height: 320px; object-fit: cover; }
.lf-results-waterfall .lf-thumb-ext { min-height: 108px; }
.lf-results-waterfall .lf-item-dir, .lf-results-waterfall .lf-item-meta { display: none; }
.lf-results-waterfall .lf-item-name { font-size: 11px; padding: 2px 2px 0; }

.lf-preview { display: flex; flex-direction: column; min-height: 0; border-left: 1px solid color-mix(in srgb, var(--theme-main-text, var(--text)) 8%, transparent); padding-left: var(--space-3); }
.lf-preview-head { display: flex; align-items: flex-start; gap: var(--space-2); padding-bottom: var(--space-2); }
.lf-preview-title { display: flex; flex-direction: column; min-width: 0; flex: 1 1 auto; }
.lf-preview-title strong { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lf-preview-title span { font-size: 10.5px; color: color-mix(in srgb, var(--theme-main-text, var(--text)) 48%, transparent); }
.lf-preview-actions { display: flex; gap: 2px; flex: 0 0 auto; }
.lf-preview-body { flex: 1 1 auto; min-height: 120px; overflow: auto; display: flex; flex-direction: column; justify-content: center; }
.lf-image-stage { position: relative; display: flex; align-items: center; justify-content: center; min-height: 160px; overflow: hidden; }
.lf-image-stage img { max-width: 100%; max-height: 100%; transition: transform var(--dur-fast, .18s) var(--ease-out, ease-out); transform-origin: center; }
.lf-image-tools { position: absolute; bottom: 4px; left: 50%; transform: translateX(-50%); display: flex; gap: 4px; align-items: center; padding: 3px 6px; border-radius: 999px; background: color-mix(in srgb, var(--theme-main-background, var(--bg)) 80%, transparent); font-size: 10px; backdrop-filter: blur(8px); }
.lf-media video, .lf-media audio { width: 100%; max-height: 320px; }
.lf-media.lf-audio { padding: var(--space-3) 0; }
.lf-pdf { width: 100%; height: 360px; border: 0; border-radius: 8px; background: color-mix(in srgb, var(--theme-main-text, var(--text)) 4%, transparent); }
.lf-text { margin: 0; padding: var(--space-2); font-size: 11px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; max-height: 360px; overflow: auto; border-radius: 8px; background: color-mix(in srgb, var(--theme-main-text, var(--text)) 4%, transparent); font-family: var(--font-mono, ui-monospace, monospace); }
.lf-folder-info { display: flex; flex-direction: column; align-items: center; gap: var(--space-2); font-size: 12px; }

.lf-asset { display: flex; flex-direction: column; gap: 6px; padding-top: var(--space-2); border-top: 1px solid color-mix(in srgb, var(--theme-main-text, var(--text)) 8%, transparent); }
.lf-asset-row { display: flex; align-items: center; gap: var(--space-2); }
.lf-stars { display: flex; gap: 1px; }
.lf-star { font-size: 15px; line-height: 1; color: color-mix(in srgb, var(--theme-main-text, var(--text)) 24%, transparent); padding: 0 1px; border: 0; background: transparent; }
.lf-star.on { color: var(--orange, #d99a2b); }
.lf-star:first-child { font-size: 17px; margin-right: 4px; }
.lf-asset-hint { font-size: 10.5px; color: color-mix(in srgb, var(--theme-main-text, var(--text)) 45%, transparent); margin-left: auto; }
.lf-field { display: flex; flex-direction: column; gap: 2px; font-size: 10.5px; color: color-mix(in srgb, var(--theme-main-text, var(--text)) 50%, transparent); }
.lf-field input, .lf-field textarea { font-size: 11.5px; padding: 4px 6px; border-radius: 6px; }
.lf-tags { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.lf-tag { display: inline-flex; align-items: center; gap: 2px; font-size: 10.5px; padding: 2px 6px; border-radius: 999px; background: color-mix(in srgb, var(--blue, #4c8dff) 12%, transparent); }
.lf-tag button { font-size: 12px; line-height: 1; opacity: .6; }
.lf-tag-input { flex: 1 1 100px; min-width: 90px; font-size: 11px; padding: 3px 6px; border-radius: 999px; }
.lf-relink { display: flex; flex-direction: column; gap: 4px; font-size: 10.5px; color: var(--orange, #d99a2b); }
.lf-relink-row { display: flex; gap: 4px; }
.lf-relink-row input { flex: 1 1 auto; font-size: 11px; padding: 3px 6px; }
.lf-asset-footer { display: flex; align-items: center; gap: var(--space-2); }
.lf-asset-id { font-size: 10px; opacity: .45; margin-right: auto; }
.lf-link-danger { font-size: 10.5px; color: color-mix(in srgb, var(--red, #d9534f) 80%, transparent); }
.lf-hint { margin: 4px 0 0; font-size: 11px; opacity: .7; }

.lf-statusbar { display: flex; align-items: center; gap: var(--space-2); padding-top: 2px; font-size: 10.5px; color: color-mix(in srgb, var(--theme-main-text, var(--text)) 45%, transparent); min-height: 18px; }
.lf-engine { display: inline-flex; align-items: center; gap: 4px; }
.lf-engine-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--green, #4caf50); }
.lf-engine[data-state='not_running'] .lf-engine-dot, .lf-engine[data-state='missing_cli'] .lf-engine-dot, .lf-engine[data-state='not_installed'] .lf-engine-dot, .lf-engine[data-state='incompatible'] .lf-engine-dot, .lf-engine[data-state='error'] .lf-engine-dot { background: var(--orange, #d99a2b); }
.lf-status-spacer { flex: 1 1 auto; }
.lf-message { color: color-mix(in srgb, var(--theme-main-text, var(--text)) 62%, transparent); max-width: 60%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lf-clipboard { font-variant-numeric: tabular-nums; }

.lf-fullscreen { position: fixed; inset: 0; z-index: 60; display: flex; align-items: center; justify-content: center; background: rgb(0 0 0 / 82%); backdrop-filter: blur(6px); }
.lf-fullscreen img { max-width: 94vw; max-height: 92vh; object-fit: contain; }
.lf-fullscreen-close { position: absolute; top: 16px; right: 20px; color: #fff; font-size: 26px; opacity: .8; }
.lf-fullscreen-nav { position: absolute; top: 50%; transform: translateY(-50%); color: #fff; font-size: 42px; opacity: .55; padding: 12px; }
.lf-fullscreen-nav:hover { opacity: 1; }
.lf-fullscreen-nav.prev { left: 12px; }
.lf-fullscreen-nav.next { right: 12px; }

.lf-popover, .lf-dialog-backdrop { position: fixed; inset: 0; z-index: 55; display: flex; align-items: center; justify-content: center; background: rgb(0 0 0 / 28%); }
.lf-popover-card, .lf-dialog { width: min(360px, 88vw); max-height: 70vh; overflow: auto; padding: var(--space-3); border-radius: 12px; background: var(--theme-main-background, var(--bg)); border: 1px solid color-mix(in srgb, var(--theme-main-text, var(--text)) 12%, transparent); box-shadow: 0 18px 50px rgb(0 0 0 / 22%); display: flex; flex-direction: column; gap: 4px; }
.lf-popover-card h3, .lf-dialog h3 { margin: 0 0 var(--space-2); font-size: 13px; }
.lf-popover-item { display: flex; justify-content: space-between; gap: var(--space-2); padding: 6px 8px; border-radius: 7px; font-size: 12px; text-align: left; }
.lf-popover-item:hover { background: color-mix(in srgb, var(--theme-main-text, var(--text)) 7%, transparent); }
.lf-popover-item span { opacity: .45; font-size: 10px; }
.lf-dialog-copy { margin: 0 0 var(--space-2); font-size: 12px; line-height: 1.5; color: color-mix(in srgb, var(--theme-main-text, var(--text)) 64%, transparent); }
.lf-dialog-copy.lf-danger { color: var(--red, #d9534f); }
.lf-dialog-input { font-size: 12px; padding: 6px 8px; border-radius: 7px; }
.lf-dialog-actions { display: flex; justify-content: flex-end; gap: var(--space-2); margin-top: var(--space-2); }

@media (max-width: 1180px) {
  .lf-shell, .lf-shell.has-preview { grid-template-columns: minmax(0, 1fr); }
  .lf-preview { position: fixed; right: 12px; top: 72px; bottom: 44px; width: min(380px, 92vw); z-index: 40; padding: var(--space-3); border-radius: 12px; background: var(--theme-main-background, var(--bg)); border: 1px solid color-mix(in srgb, var(--theme-main-text, var(--text)) 10%, transparent); box-shadow: 0 18px 50px rgb(0 0 0 / 20%); }
  .lf-item-meta { display: none; }
}
@media (max-width: 980px) {
  .lf-rail-toggle { display: inline-flex; align-items: center; }
  .lf-rail {
    display: none;
    position: fixed;
    left: 12px;
    top: 72px;
    bottom: 44px;
    width: 220px;
    z-index: 45;
    padding: var(--space-3);
    border-radius: 12px;
    background: var(--theme-main-background, var(--bg));
    border: 1px solid color-mix(in srgb, var(--theme-main-text, var(--text)) 10%, transparent);
    box-shadow: 0 18px 50px rgb(0 0 0 / 20%);
  }
  .lf-rail.open { display: flex; }
}
@media (max-width: 720px) {
  .lf-search { flex-basis: 100%; }
  .lf-scope-btn { padding: 4px 8px; }
  .lf-view-switch button { padding: 4px 7px; }
  .lf-results-waterfall { columns: 2 140px; }
}
</style>
