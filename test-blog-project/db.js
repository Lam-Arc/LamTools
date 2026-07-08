const Database = require('better-sqlite3');
const path = require('path');

let db;
try {
  db = new Database(path.join(__dirname, 'blog.db'));
} catch (err) {
  console.error('数据库连接失败:', err.message);
  process.exit(1);
}

// 初始化表结构
function init() {
  try {
    db.exec(`
      CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        slug TEXT UNIQUE NOT NULL,
        content TEXT NOT NULL,
        summary TEXT,
        author TEXT DEFAULT 'Admin',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        published INTEGER DEFAULT 1
      );
    `);

    // 创建用户表
    db.exec(`
      CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT DEFAULT 'admin',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
      );
    `);

    // 插入示例数据（如果表为空）
    const count = db.prepare('SELECT COUNT(*) as count FROM posts').get();
    if (count.count === 0) {
      const insert = db.prepare(`
        INSERT INTO posts (title, slug, content, summary, author)
        VALUES (?, ?, ?, ?, ?)
      `);
      insert.run(
        '欢迎来到我的个人博客',
        'welcome',
        '这是我的第一篇博客文章。这个博客使用 Node.js + Express + SQLite 构建，简洁、快速且易于维护。\n\n在这里，我会分享技术心得、生活感悟和有趣的项目。希望你能喜欢！',
        '这是我的第一篇博客文章，介绍博客的技术栈和初衷。',
        'Admin'
      );
      insert.run(
        '如何学习 Node.js',
        'learn-nodejs',
        'Node.js 是一个非常强大的 JavaScript 运行时环境。以下是一些学习建议：\n\n1. **掌握 JavaScript 基础**：了解 ES6+ 语法、异步编程、Promise 等概念。\n2. **理解 Node.js 核心模块**：如 fs、path、http、events 等。\n3. **学习 Express 框架**：快速构建 Web 应用。\n4. **实践项目**：通过实际项目加深理解。\n\n最重要的是保持好奇心和持续学习的心态！',
        '分享 Node.js 学习路径和建议。',
        'Admin'
      );
      insert.run(
        'SQLite 入门指南',
        'sqlite-guide',
        'SQLite 是一个嵌入式关系型数据库，非常适合中小型项目。\n\n## 特点\n\n- 零配置，无需单独的服务器进程\n- 单文件存储，便于备份和迁移\n- 支持 ACID 事务\n- 跨平台兼容\n\n## 基本用法\n\n```javascript\nconst db = new Database(\'data.db\');\ndb.exec("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)");\nconst stmt = db.prepare("INSERT INTO users (name) VALUES (?)");\nstmt.run("Alice");\n```\n\nSQLite 是构建个人项目和原型开发的绝佳选择。',
        '介绍 SQLite 数据库的特点和基本用法。',
        'Admin'
      );
    }
  } catch (err) {
    console.error('数据库初始化失败:', err.message);
    throw err;
  }
}

// 获取所有文章（按时间倒序）
function getAllPosts(published = true) {
  try {
    const sql = published
      ? 'SELECT * FROM posts WHERE published = 1 ORDER BY created_at DESC'
      : 'SELECT * FROM posts ORDER BY created_at DESC';
    return db.prepare(sql).all();
  } catch (err) {
    console.error('获取文章列表失败:', err.message);
    return [];
  }
}

// 根据 slug 获取单篇文章
function getPostBySlug(slug) {
  try {
    return db.prepare('SELECT * FROM posts WHERE slug = ?').get(slug);
  } catch (err) {
    console.error('根据 slug 获取文章失败:', err.message);
    return null;
  }
}

// 根据 ID 获取文章
function getPostById(id) {
  try {
    return db.prepare('SELECT * FROM posts WHERE id = ?').get(id);
  } catch (err) {
    console.error('根据 ID 获取文章失败:', err.message);
    return null;
  }
}

// 创建文章
function createPost({ title, slug, content, summary, author = 'Admin' }) {
  try {
    const result = db.prepare(`
      INSERT INTO posts (title, slug, content, summary, author)
      VALUES (?, ?, ?, ?, ?)
    `).run(title, slug, content, summary, author);
    return result.lastInsertRowid;
  } catch (err) {
    console.error('创建文章失败:', err.message);
    return null;
  }
}

// 更新文章
function updatePost(id, { title, slug, content, summary, published }) {
  try {
    const result = db.prepare(`
      UPDATE posts
      SET title = ?, slug = ?, content = ?, summary = ?, published = ?, updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
    `).run(title, slug, content, summary, published ? 1 : 0, id);
    return result.changes > 0;
  } catch (err) {
    console.error('更新文章失败:', err.message);
    return false;
  }
}

// 删除文章
function deletePost(id) {
  try {
    const result = db.prepare('DELETE FROM posts WHERE id = ?').run(id);
    return result.changes > 0;
  } catch (err) {
    console.error('删除文章失败:', err.message);
    return false;
  }
}

// 搜索文章
function searchPosts(keyword) {
  try {
    const sql = `
      SELECT * FROM posts 
      WHERE published = 1 
        AND (title LIKE ? OR content LIKE ? OR summary LIKE ?)
      ORDER BY created_at DESC
    `;
    const pattern = '%' + keyword + '%';
    return db.prepare(sql).all(pattern, pattern, pattern);
  } catch (err) {
    console.error('搜索文章失败:', err.message);
    return [];
  }
}

// 获取分页文章
function getPostsPaginated(page = 1, perPage = 10) {
  try {
    const offset = (page - 1) * perPage;
    const posts = db.prepare(
      'SELECT * FROM posts WHERE published = 1 ORDER BY created_at DESC LIMIT ? OFFSET ?'
    ).all(perPage, offset);
    const countResult = db.prepare('SELECT COUNT(*) as total FROM posts WHERE published = 1').get();
    return {
      posts,
      total: countResult.total,
      page,
      perPage,
      totalPages: Math.ceil(countResult.total / perPage)
    };
  } catch (err) {
    console.error('获取分页文章失败:', err.message);
    return { posts: [], total: 0, page: 1, perPage, totalPages: 0 };
  }
}

// 生成 slug
function slugify(title) {
  return title
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, '')
    .replace(/[\s_-]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

// 创建用户
function createUser({ username, passwordHash, role = 'admin' }) {
  try {
    const result = db.prepare(`
      INSERT INTO users (username, password_hash, role)
      VALUES (?, ?, ?)
    `).run(username, passwordHash, role);
    return result.lastInsertRowid;
  } catch (err) {
    console.error('创建用户失败:', err.message);
    return null;
  }
}

// 根据用户名获取用户
function getUserByUsername(username) {
  try {
    return db.prepare('SELECT * FROM users WHERE username = ?').get(username);
  } catch (err) {
    console.error('获取用户失败:', err.message);
    return null;
  }
}

// 初始化默认管理员账户
function initDefaultAdmin() {
  try {
    const count = db.prepare('SELECT COUNT(*) as count FROM users').get();
    if (count.count === 0) {
      const bcrypt = require('bcrypt');
      const defaultPassword = process.env.ADMIN_PASSWORD || 'admin123';
      const hash = bcrypt.hashSync(defaultPassword, 10);
      createUser({ username: 'admin', passwordHash: hash, role: 'admin' });
      console.log('默认管理员账户已创建（用户名: admin）');
    }
  } catch (err) {
    console.error('初始化默认管理员失败:', err.message);
  }
}

module.exports = {
  init,
  getAllPosts,
  getPostBySlug,
  getPostById,
  createPost,
  updatePost,
  deletePost,
  searchPosts,
  getPostsPaginated,
  slugify,
  createUser,
  getUserByUsername,
  initDefaultAdmin
};
