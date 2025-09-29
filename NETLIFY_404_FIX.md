# Netlify 404 问题修复指南

## 🔍 问题分析

根据 [Netlify 官方支持指南](https://answers.netlify.com/t/support-guide-i-ve-deployed-my-site-but-i-still-see-page-not-found/125)，"Page Not Found" 的常见原因包括：

### 1. 发布目录配置错误 ❌
**问题**：`publish = "netlify"` 指向了不存在的目录
**解决**：改为 `publish = "."` 指向项目根目录

### 2. 缺少 index.html 文件 ❌
**问题**：根目录没有 `index.html` 作为默认页面
**解决**：创建根目录 `index.html` 作为加载页面

### 3. 重定向规则问题 ❌
**问题**：`force = true` 可能导致重定向冲突
**解决**：移除 `force = true`，使用标准重定向

## ✅ 已修复的配置

### 1. 更新 `netlify.toml`
```toml
[build]
  command = "pip install -r requirements.txt"
  publish = "."  # 修复：指向根目录

[build.environment]
  PYTHON_VERSION = "3.11"
  DATABASE_TYPE = "turso"

# 重定向规则 - 将所有请求转发到Flask应用
[[redirects]]
  from = "/*"
  to = "/.netlify/functions/app"
  status = 200  # 修复：移除 force = true

[functions]
  directory = "netlify/functions"
```

### 2. 创建根目录 `index.html`
- 提供加载页面和自动重定向
- 确保用户访问根URL时有内容显示
- 2秒后自动跳转到Flask应用

### 3. 更新 `.gitignore`
- 添加 `node_modules/` 忽略规则
- 添加 Node.js 相关文件忽略

## 🚀 部署步骤

### 1. 撤销之前的 git add
```bash
git reset HEAD  # 撤销所有已添加的文件
```

### 2. 重新添加文件
```bash
git add .gitignore
git add netlify.toml
git add index.html
git add requirements.txt
git add database_config.py
git add netlify/functions/app.py
git add DEPLOYMENT_FIX.md
git add NETLIFY_404_FIX.md
```

### 3. 提交并推送
```bash
git commit -m "Fix Netlify 404: correct publish directory and add index.html"
git push origin main
```

## 🔧 关键修复点

### 发布目录修复
- **之前**：`publish = "netlify"` (目录不存在)
- **现在**：`publish = "."` (项目根目录)

### 默认页面修复
- **之前**：根目录没有 `index.html`
- **现在**：创建了 `index.html` 作为加载页面

### 重定向规则修复
- **之前**：`force = true` 可能导致冲突
- **现在**：使用标准重定向规则

## 📋 验证步骤

1. **等待 Netlify 重新部署**
2. **访问根URL**：`https://curling-masters.netlify.app`
3. **应该看到**：加载页面，然后自动跳转到Flask应用
4. **检查函数日志**：确认Flask应用正常启动

## 🚨 如果问题仍然存在

### 检查 Netlify 函数日志
1. Netlify控制台 → Functions → 查看错误日志
2. 确认 `libsql-sqlalchemy` 是否正确安装
3. 检查Turso数据库连接

### 验证环境变量
确保在Netlify控制台设置了：
- `DATABASE_TYPE=turso`
- `TURSO_URL=libsql://curling-masters-srhskah.aws-ap-northeast-1.turso.io`
- `TURSO_AUTH_TOKEN=你的令牌`
- `SECRET_KEY=你的密钥`

### 测试本地构建
```bash
# 测试本地构建
pip install -r requirements.txt
python -c "from database_config import get_database_config; print(get_database_config())"
```

现在按照上述步骤重新部署，应该能解决404问题！
