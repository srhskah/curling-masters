# Git 仓库设置指南

## 🔒 敏感信息保护配置

### 1. 已创建的安全文件

**`.gitignore`** - 忽略敏感文件：
- `.env` 环境变量文件
- `*.db` 数据库文件
- `__pycache__/` Python缓存
- 测试文件和临时文件

**`SECURITY.md`** - 安全配置指南
**`env.example`** - 环境变量模板

### 2. 初始化Git仓库

```bash
# 初始化Git仓库
git init

# 配置用户信息（替换为你的信息）
git config user.name "Your Name"
git config user.email "your-email@example.com"

# 添加安全文件
git add .gitignore SECURITY.md env.example

# 提交安全配置
git commit -m "Add security configuration files"
```

### 3. 添加项目文件

```bash
# 添加项目文件（敏感信息已被.gitignore保护）
git add app.py models.py db.py requirements.txt
git add templates/ static/ scripts/
git add database_config.py switch_database.py
git add netlify.toml netlify/ DEPLOYMENT.md
git add LOCAL_TURSO_TESTING.md

# 提交项目代码
git commit -m "Add Flask application with Turso database support"
```

### 4. 推送到GitHub

```bash
# 添加远程仓库（替换为你的仓库URL）
git remote add origin https://github.com/yourusername/your-repo.git

# 推送到GitHub
git push -u origin main
```

### 5. 安全检查

**提交前检查：**
```bash
# 检查哪些文件会被提交
git status

# 确保敏感文件被忽略
git check-ignore .env
git check-ignore *.db
```

**验证敏感信息保护：**
- [ ] `.env` 文件不在git status中
- [ ] 数据库文件被忽略
- [ ] 环境变量模板使用占位符
- [ ] 没有硬编码的密钥或令牌

### 6. 环境变量设置

**本地开发：**
```bash
# 创建本地环境变量文件
cp env.example .env

# 编辑 .env 文件，填入真实值
# 注意：.env 文件已被 .gitignore 忽略
```

**Netlify部署：**
1. 在Netlify控制台设置环境变量
2. 不要将敏感信息提交到代码仓库
3. 使用环境变量模板作为参考

### 7. 持续安全实践

**定期检查：**
- 审查 `.gitignore` 规则
- 更新环境变量模板
- 轮换密钥和令牌
- 监控访问日志

**团队协作：**
- 共享 `env.example` 模板
- 使用不同的开发环境变量
- 定期更新安全文档

## 🚨 重要提醒

1. **永远不要提交敏感信息到Git**
2. **使用环境变量传递配置**
3. **定期轮换密钥和令牌**
4. **监控生产环境访问**

现在你的项目已经配置好安全保护，可以安全地推送到GitHub了！
