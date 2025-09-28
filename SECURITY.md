# 安全配置指南

## 🔒 敏感信息保护

### 1. 环境变量保护

**❌ 永远不要提交到Git：**
- `.env` 文件
- 数据库连接字符串
- API密钥和令牌
- 密码和密钥

**✅ 安全做法：**
- 使用 `.env.example` 作为模板
- 在 `.gitignore` 中忽略敏感文件
- 通过环境变量传递敏感信息

### 2. 当前项目的敏感信息

**需要保护的信息：**
```bash
# Turso数据库配置
TURSO_URL=libsql://your-database.region.turso.io
TURSO_AUTH_TOKEN=your-auth-token

# Flask安全密钥
SECRET_KEY=your-secret-key

# 本地数据库加密密钥
DB_ENCRYPTION_KEY=your-encryption-key
```

### 3. 本地开发配置

**创建 `.env` 文件（不提交到Git）：**
```bash
# 复制模板文件
cp env.example .env

# 编辑 .env 文件，填入真实值
DATABASE_TYPE=local
DB_ENCRYPTION_KEY=your_local_encryption_key
SECRET_KEY=your_local_secret_key
```

### 4. 生产环境配置

**Netlify环境变量设置：**
1. 登录Netlify控制台
2. 进入 Site settings > Environment variables
3. 添加以下变量：

```
DATABASE_TYPE = turso
TURSO_URL = libsql://your-database.region.turso.io
TURSO_AUTH_TOKEN = your-auth-token
SECRET_KEY = your-secret-key
```

### 5. 安全检查清单

**提交代码前检查：**
- [ ] `.env` 文件已添加到 `.gitignore`
- [ ] 敏感信息已从代码中移除
- [ ] 使用 `env.example` 作为模板
- [ ] 数据库文件已忽略
- [ ] 日志文件已忽略

**部署前检查：**
- [ ] 生产环境变量已正确设置
- [ ] 使用强密钥和令牌
- [ ] 定期轮换敏感信息
- [ ] 监控访问日志

### 6. 密钥管理最佳实践

**生成强密钥：**
```bash
# 生成SECRET_KEY
python scripts/generate_secret_key.py

# 生成随机字符串
python -c "import secrets; print(secrets.token_hex(32))"
```

**密钥轮换：**
- 定期更换SECRET_KEY
- 定期更新数据库令牌
- 监控异常访问

### 7. 紧急情况处理

**如果敏感信息泄露：**
1. 立即更换所有密钥和令牌
2. 检查访问日志
3. 更新环境变量
4. 重新部署应用

**联系信息：**
- 项目维护者：[你的联系方式]
- 安全报告：[安全邮箱]

## 🛡️ 安全工具

### Git Hooks
```bash
# 安装pre-commit hook
pip install pre-commit
pre-commit install
```

### 代码扫描
```bash
# 扫描敏感信息
git secrets --scan
```

### 环境检查
```bash
# 检查环境变量
python -c "import os; print('SECRET_KEY' in os.environ)"
```

记住：安全是一个持续的过程，不是一次性的配置！
