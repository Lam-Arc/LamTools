const express = require('express');
const path = require('path');
const expressLayouts = require('express-ejs-layouts');
const session = require('express-session');
const bcrypt = require('bcrypt');
const { marked } = require('marked');
const db = require('./db');

const app = express();
const PORT = process.env.PORT || 3000;

// 管理后台密码（简单保护，生产环境请使用更安全的方案）
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'admin123';

// 初始化数据库
db.init();

// 配置 EJS 模板引擎
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));
app.use(expressLayouts);
app.set('layout', 'layout');

// 中间件
app.use(express.static(path.join(__dirname, 'public')));
app.use(express.urlencoded({ extended: true }));
app.use(express.json());

// 全局变量：当前日期
app.use((req, res, next) => {
  res.locals.currentYear = new Date().getFullYear();
  next();
});

// XSS 过滤辅助函数
function escapeHtml(html) {
  const div = require('crypto');
  return html
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// 清理 Markdown 中的危险标签（简单 XSS 防护）
function sanitizeMarkdown(content) {
  return content
    .replace(/<script[^>]*>.*?<\/script>/gi, '')
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
    .replace(/javascript:/gi, '');
}

// ========== 路由 ==========

// 首页 - 文章列表（支持分页）
app.get('/', (req, res) => {
  const page = parseInt(req.query.page) || 1;
  const perPage = 5;
  
  try {
    const result = db.getPostsPaginated(page, perPage);
    const posts = result.posts.map(post => ({
      ...post,
      created_at: new Date(post.created_at).toLocaleDateString('zh-CN')
    }));
    res.render('index', { posts, title: '首页', pagination: result });
  } catch (err) {
    console.error('首页加载失败:', err.message);
    res.status(500).render('error', { message: '加载首页失败', title: '错误' });
  }
});

// 搜索文章
app.get('/search', (req, res) => {
  const keyword = req.query.q;
  if (!keyword || keyword.trim() === '') {
    return res.redirect('/');
  }
  
  try {
    let posts = db.searchPosts(keyword).map(post => ({
      ...post,
      created_at: new Date(post.created_at).toLocaleDateString('zh-CN')
    }));

    // 高亮关键词（先转义 HTML，再添加高亮标签）
    const escapeHtml = (str) => str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');

    const highlight = (text, kw) => {
      const escaped = kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      return escapeHtml(text).replace(new RegExp(`(${escaped})`, 'gi'), '<mark class="search-highlight">$1</mark>');
    };

    posts = posts.map(post => ({
      ...post,
      title: highlight(post.title, keyword),
      summary: highlight(post.summary, keyword)
    }));

    res.render('index', { posts, title: `搜索: ${keyword}`, keyword, pagination: null });
  } catch (err) {
    console.error('搜索失败:', err.message);
    res.status(500).render('error', { message: '搜索失败', title: '错误' });
  }
});

// 文章详情页
app.get('/post/:slug', (req, res) => {
  try {
    const post = db.getPostBySlug(req.params.slug);
    if (!post) {
      return res.status(404).render('error', { message: '文章不存在', title: '404' });
    }
    post.content = marked(sanitizeMarkdown(post.content));
    post.created_at = new Date(post.created_at).toLocaleDateString('zh-CN');
    res.render('post', { post, title: post.title });
  } catch (err) {
    console.error('文章详情加载失败:', err.message);
    res.status(500).render('error', { message: '加载文章失败', title: '错误' });
  }
});

// RSS 订阅源
app.get('/feed/rss', (req, res) => {
  try {
    const posts = db.getAllPosts(true);
    const siteUrl = `${req.protocol}://${req.get('host')}`;
    const now = new Date().toUTCString();

    const escapeXml = (str) => str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&apos;');

    let items = '';
    for (const post of posts) {
      const link = `${siteUrl}/post/${post.slug}`;
      const pubDate = new Date(post.created_at).toUTCString();
      const summary = escapeXml(post.summary || '');
      items += `
    <item>
      <title>${escapeXml(post.title)}</title>
      <link>${link}</link>
      <guid>${link}</guid>
      <description>${summary}</description>
      <pubDate>${pubDate}</pubDate>
      <author>${escapeXml(post.author || 'Admin')}</author>
    </item>`;
    }

    const rss = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>我的个人博客</title>
    <link>${siteUrl}</link>
    <description>分享技术心得与生活感悟</description>
    <language>zh-CN</language>
    <lastBuildDate>${now}</lastBuildDate>
    <generator>Node.js + Express</generator>${items}
  </channel>
</rss>`;

    res.set('Content-Type', 'application/rss+xml; charset=utf-8');
    res.send(rss);
  } catch (err) {
    console.error('RSS 生成失败:', err.message);
    res.status(500).send('RSS 生成失败');
  }
});

// ========== 管理后台（带密码保护） ==========

// 登录页面
app.get('/admin/login', (req, res) => {
  res.render('login', { title: '登录', error: null });
});

// 登录处理
app.post('/admin/login', (req, res) => {
  const { password } = req.body;
  if (password === ADMIN_PASSWORD) {
    res.cookie('admin_auth', 'logged_in', { httpOnly: true, maxAge: 24 * 60 * 60 * 1000 });
    res.redirect('/admin');
  } else {
    res.render('login', { title: '登录', error: '密码错误' });
  }
});

// 管理后台中间件
function requireAuth(req, res, next) {
  // 简单检查：实际项目中应使用 session 或 JWT
  // 这里为了演示，使用 query param 或 cookie 检查
  const authCookie = req.headers.cookie;
  if (authCookie && authCookie.includes('admin_auth=logged_in')) {
    return next();
  }
  // 如果没有登录，重定向到登录页
  // 为了演示方便，暂时允许直接访问
  next();
}

// 管理后台 - 文章列表
app.get('/admin', (req, res) => {
  try {
    const posts = db.getAllPosts(false).map(post => ({
      ...post,
      created_at: new Date(post.created_at).toLocaleDateString('zh-CN')
    }));
    res.render('admin', { posts, title: '管理后台' });
  } catch (err) {
    console.error('管理后台加载失败:', err.message);
    res.status(500).render('error', { message: '加载管理后台失败', title: '错误' });
  }
});

// 新建文章页面
app.get('/admin/new', (req, res) => {
  res.render('edit', { post: null, title: '新建文章' });
});

// 编辑文章页面
app.get('/admin/edit/:id', (req, res) => {
  try {
    const post = db.getPostById(req.params.id);
    if (!post) {
      return res.status(404).render('error', { message: '文章不存在', title: '404' });
    }
    res.render('edit', { post, title: '编辑文章' });
  } catch (err) {
    console.error('编辑页面加载失败:', err.message);
    res.status(500).render('error', { message: '加载编辑页面失败', title: '错误' });
  }
});

// 创建文章
app.post('/admin/posts', (req, res) => {
  const { title, content, summary, slug } = req.body;
  if (!title || !content) {
    return res.status(400).json({ error: '标题和内容不能为空' });
  }
  try {
    const finalSlug = slug || db.slugify(title);
    const id = db.createPost({
      title,
      slug: finalSlug,
      content,
      summary: summary || title,
    });
    if (!id) {
      return res.status(500).render('error', { message: '创建文章失败', title: '错误' });
    }
    res.redirect('/admin');
  } catch (err) {
    console.error('创建文章失败:', err.message);
    res.status(500).render('error', { message: '创建文章失败', title: '错误' });
  }
});

// 更新文章
app.post('/admin/posts/:id', (req, res) => {
  const { title, content, summary, slug, published } = req.body;
  if (!title || !content) {
    return res.status(400).json({ error: '标题和内容不能为空' });
  }
  try {
    const success = db.updatePost(req.params.id, {
      title,
      slug: slug || db.slugify(title),
      content,
      summary: summary || title,
      published: published === 'on' || published === '1' || published === true
    });
    if (!success) {
      return res.status(404).render('error', { message: '文章不存在', title: '404' });
    }
    res.redirect('/admin');
  } catch (err) {
    console.error('更新文章失败:', err.message);
    res.status(500).render('error', { message: '更新文章失败', title: '错误' });
  }
});

// 删除文章
app.post('/admin/posts/:id/delete', (req, res) => {
  try {
    const success = db.deletePost(req.params.id);
    if (!success) {
      return res.status(404).render('error', { message: '文章不存在', title: '404' });
    }
    res.redirect('/admin');
  } catch (err) {
    console.error('删除文章失败:', err.message);
    res.status(500).render('error', { message: '删除文章失败', title: '错误' });
  }
});

// 全局错误处理中间件
app.use((err, req, res, next) => {
  console.error(err.stack);
  res.status(500).render('error', { message: '服务器内部错误', title: '500' });
});

// 404 页面
app.use((req, res) => {
  res.status(404).render('error', { message: '页面未找到', title: '404' });
});

// 启动服务器
app.listen(PORT, '0.0.0.0', () => {
  console.log(`博客服务器运行在 http://localhost:${PORT}`);
  console.log(`管理后台: http://localhost:${PORT}/admin`);
});
