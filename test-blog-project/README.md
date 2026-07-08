# 个人博客网站

一个简洁、现代的个人博客系统，基于 Node.js + Express + SQLite 构建。

## 功能特性

- 📝 Markdown 文章支持
- 🎨 现代化的响应式设计
- 🛠️ 管理后台（增删改查文章）
- 📱 移动端友好
- 🗄️ SQLite 数据库存储

## 技术栈

- **后端**: Node.js + Express
- **模板引擎**: EJS
- **数据库**: SQLite (better-sqlite3)
- **样式**: 纯 CSS
- **Markdown 解析**: marked

## 快速开始

### 安装依赖

```bash
npm install
```

### 启动应用

```bash
# 开发模式（自动重启）
npm run dev

# 生产模式
npm start
```

访问 http://localhost:3000 查看博客，管理后台地址：http://localhost:3000/admin

## 项目结构

```
.
├── server.js          # 主入口
├── db.js              # 数据库操作
├── public/            # 静态资源（CSS）
├── views/             # EJS 模板
│   ├── layout.ejs     # 基础布局
│   ├── index.ejs      # 首页
│   ├── post.ejs       # 文章详情
│   ├── admin.ejs      # 管理后台
│   ├── edit.ejs       # 编辑/新建文章
│   └── error.ejs      # 错误页面
└── blog.db            # SQLite 数据库（自动生成）
```
