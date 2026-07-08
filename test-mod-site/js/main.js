/**
 * Lam's Mods - Main JavaScript
 * Handles mod data, rendering, search/filter, and UI interactions
 */

// ============================================
// Mod Data
// ============================================
const modsData = [
  {
    id: 1,
    name: "Enhanced Furnaces",
    version: "1.20.1",
    description: "为原版熔炉添加多种升级变体，包括双倍熔炼、自动燃料补给等功能，大幅提升冶炼效率。",
    category: "tech",
    downloads: "15.2K",
    rating: "4.9",
    mcVersions: "1.18-1.20",
    icon: "🔥"
  },
  {
    id: 2,
    name: "Mystic Arts",
    version: "2.3.0",
    description: "一个以东方神秘学为主题的魔法 Mod，包含独特的法术系统、符文制作和法器锻造。",
    category: "magic",
    downloads: "8.7K",
    rating: "4.7",
    mcVersions: "1.19-1.20",
    icon: "✨"
  },
  {
    id: 3,
    name: "Dungeon Crawler",
    version: "1.1.5",
    description: "在世界各地生成独特的地下城结构，包含丰富的战利品、Boss 战和探险要素。",
    category: "adventure",
    downloads: "12.1K",
    rating: "4.8",
    mcVersions: "1.19-1.20",
    icon: "🏰"
  },
  {
    id: 4,
    name: "AutoCraft Pro",
    version: "3.0.2",
    description: "强大的自动化合成系统，支持配方记忆、批量制作和物流管道集成。",
    category: "tech",
    downloads: "22.5K",
    rating: "4.9",
    mcVersions: "1.18-1.20",
    icon: "⚙️"
  },
  {
    id: 5,
    name: "Inventory Sorter",
    version: "1.5.0",
    description: "一键整理背包和箱子，支持自定义分类规则和快捷键操作。",
    category: "utility",
    downloads: "35.8K",
    rating: "4.9",
    mcVersions: "1.16-1.20",
    icon: "📦"
  },
  {
    id: 6,
    name: "Elemental Wands",
    version: "1.2.1",
    description: "收集元素精华制作各式魔杖，每种魔杖都有独特的元素能力和组合效果。",
    category: "magic",
    downloads: "6.3K",
    rating: "4.6",
    mcVersions: "1.19-1.20",
    icon: "🪄"
  },
  {
    id: 7,
    name: "Biome Overhaul",
    version: "2.0.0",
    description: "全面优化原版生物群系，添加新的植物、动物和地形特征，让探索更加有趣。",
    category: "adventure",
    downloads: "18.9K",
    rating: "4.8",
    mcVersions: "1.18-1.20",
    icon: "🌿"
  },
  {
    id: 8,
    name: "Redstone Plus",
    version: "1.8.3",
    description: "扩展红石系统，添加逻辑门、无线传输和高级计时器等新组件。",
    category: "tech",
    downloads: "11.4K",
    rating: "4.7",
    mcVersions: "1.18-1.20",
    icon: "🔴"
  },
  {
    id: 9,
    name: "Waypoints",
    version: "4.1.0",
    description: "设置和管理传送点，支持跨维度传送和共享路标功能。",
    category: "utility",
    downloads: "28.6K",
    rating: "4.9",
    mcVersions: "1.16-1.20",
    icon: "📍"
  },
  {
    id: 10,
    name: "Alchemist's Table",
    version: "1.3.2",
    description: "深度炼金系统，通过元素组合创造全新材料和物品，支持自定义配方。",
    category: "magic",
    downloads: "7.1K",
    rating: "4.5",
    mcVersions: "1.19-1.20",
    icon: "⚗️"
  },
  {
    id: 11,
    name: "Nether Explorer",
    version: "1.0.8",
    description: "丰富下界探索体验，新增下界遗迹、独特生物和专属装备。",
    category: "adventure",
    downloads: "9.2K",
    rating: "4.7",
    mcVersions: "1.18-1.20",
    icon: "🔥"
  },
  {
    id: 12,
    name: "Chunk Loader",
    version: "2.2.1",
    description: "服务端友好的区块加载器，支持多种加载模式和性能优化选项。",
    category: "utility",
    downloads: "14.5K",
    rating: "4.8",
    mcVersions: "1.18-1.20",
    icon: "🗺️"
  }
];

const categoryLabels = {
  tech: { label: "科技", className: "tech" },
  magic: { label: "魔法", className: "magic" },
  adventure: { label: "冒险", className: "adventure" },
  utility: { label: "工具", className: "utility" }
};

// ============================================
// Utility Functions
// ============================================

function createModCard(mod) {
  const cat = categoryLabels[mod.category] || { label: mod.category, className: mod.category };
  return `
    <div class="mod-card" data-category="${mod.category}" data-name="${mod.name.toLowerCase()}" data-desc="${mod.description.toLowerCase()}">
      <div class="mod-card-header">
        <span>${mod.icon}</span>
      </div>
      <div class="mod-card-body">
        <h3 class="mod-card-title">${mod.name}</h3>
        <span class="mod-card-version">v${mod.version}</span>
        <p class="mod-card-desc">${mod.description}</p>
        <div style="margin-bottom: 10px;">
          <span class="mod-tag ${cat.className}">${cat.label}</span>
        </div>
        <div class="mod-card-meta">
          <span>⬇️ ${mod.downloads}</span>
          <span>⭐ ${mod.rating}</span>
          <span>🎮 ${mod.mcVersions}</span>
        </div>
      </div>
    </div>
  `;
}

function renderFeaturedMods() {
  const container = document.getElementById('featuredMods');
  if (!container) return;
  const featured = [...modsData]
    .sort((a, b) => parseFloat(b.downloads) - parseFloat(a.downloads))
    .slice(0, 3);
  container.innerHTML = featured.map(createModCard).join('');
}

function renderAllMods(mods = modsData) {
  const container = document.getElementById('modGrid');
  if (!container) return;
  if (mods.length === 0) {
    container.innerHTML = '';
    const noResults = document.getElementById('noResults');
    if (noResults) noResults.style.display = 'block';
    return;
  }
  const noResults = document.getElementById('noResults');
  if (noResults) noResults.style.display = 'none';
  container.innerHTML = mods.map(createModCard).join('');
}

// ============================================
// Search & Filter
// ============================================

let currentFilter = 'all';
let currentSearch = '';

function filterMods() {
  let filtered = modsData;
  if (currentFilter !== 'all') {
    filtered = filtered.filter(mod => mod.category === currentFilter);
  }
  if (currentSearch) {
    const query = currentSearch.toLowerCase();
    filtered = filtered.filter(mod =>
      mod.name.toLowerCase().includes(query) ||
      mod.description.toLowerCase().includes(query) ||
      mod.category.toLowerCase().includes(query)
    );
  }
  renderAllMods(filtered);
}

function setupSearchAndFilter() {
  const searchInput = document.getElementById('modSearch');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      currentSearch = e.target.value.trim();
      filterMods();
    });
  }

  const filterButtons = document.querySelectorAll('.filter-btn');
  filterButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      filterButtons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentFilter = btn.dataset.filter;
      filterMods();
    });
  });
}

// ============================================
// Mobile Menu
// ============================================

function setupMobileMenu() {
  const menuToggle = document.getElementById('menuToggle');
  const navLinks = document.getElementById('navLinks');

  if (menuToggle && navLinks) {
    menuToggle.addEventListener('click', () => {
      navLinks.classList.toggle('show');
    });
    navLinks.querySelectorAll('a').forEach(link => {
      link.addEventListener('click', () => {
        navLinks.classList.remove('show');
      });
    });
  }
}

// ============================================
// Back to Top
// ============================================

function setupBackToTop() {
  const backToTop = document.getElementById('backToTop');
  if (!backToTop) return;
  window.addEventListener('scroll', () => {
    if (window.scrollY > 300) {
      backToTop.classList.add('visible');
    } else {
      backToTop.classList.remove('visible');
    }
  });
  backToTop.addEventListener('click', () => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });
}

// ============================================
// Scroll Animations
// ============================================

function setupScrollAnimations() {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.style.opacity = '1';
        entry.target.style.transform = 'translateY(0)';
      }
    });
  }, { threshold: 0.1 });

  document.querySelectorAll('.fade-in').forEach(el => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(30px)';
    el.style.transition = 'opacity 0.6s ease-out, transform 0.6s ease-out';
    observer.observe(el);
  });
}

// ============================================
// Active Navigation
// ============================================

function setActiveNav() {
  const currentPage = window.location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.nav-links a').forEach(link => {
    link.classList.remove('active');
    if (link.getAttribute('href') === currentPage) {
      link.classList.add('active');
    }
  });
}

// ============================================
// Initialize
// ============================================

document.addEventListener('DOMContentLoaded', () => {
  renderFeaturedMods();
  renderAllMods();
  setupSearchAndFilter();
  setupMobileMenu();
  setupBackToTop();
  setupScrollAnimations();
  setActiveNav();
});
