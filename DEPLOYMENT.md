# 部署指南

## 数据库配置

### 自动检测机制
系统会自动检测环境变量：
- 如果设置了 `TURSO_URL` 和 `TURSO_AUTH_TOKEN`，默认使用Turso数据库
- 如果Turso配置不完整，自动回退到本地SQLCipher数据库

### 本地开发
```bash
# 使用本地SQLCipher数据库
python switch_database.py local

# 或设置环境变量
export DATABASE_TYPE=local
export DB_ENCRYPTION_KEY=your_encryption_key
```

### 远程Turso数据库
```bash
# 切换到Turso数据库
python switch_database.py turso

# 设置环境变量
export DATABASE_TYPE=turso
export TURSO_URL=your-turso-database-url
export TURSO_AUTH_TOKEN=your-turso-auth-token
```

### 一键切换
```bash
# 查看当前状态
python switch_database.py status

# 切换到本地
python switch_database.py local

# 切换到Turso
python switch_database.py turso
```

## Netlify部署

### 1. 准备Turso数据库
1. 在 [Turso官网](https://turso.tech/) 创建账户
2. 创建数据库并获取URL和认证令牌
3. 将本地数据迁移到Turso（可选）

### 2. 生成SECRET_KEY
```bash
# 使用内置工具生成
python scripts/generate_secret_key.py

# 或使用Python命令
python -c "import secrets; print(secrets.token_hex(32))"
```

### 3. 配置Netlify环境变量
在Netlify控制台的 Site settings > Environment variables 中设置：

```
DATABASE_TYPE=turso
TURSO_URL=your-turso-database-url
TURSO_AUTH_TOKEN=your-turso-auth-token
SECRET_KEY=your-generated-secret-key
```

### 4. 部署到Netlify
1. 将代码推送到GitHub仓库
2. 在Netlify中连接GitHub仓库
3. 构建设置：
   - Build command: `pip install -r requirements.txt`
   - Publish directory: `.`
   - Functions directory: `netlify/functions`

### 5. 验证部署
访问你的Netlify域名，确认应用正常运行。

## 数据迁移

### 从本地迁移到Turso
```bash
# 1. 导出本地数据
python scripts/export_to_sql.py

# 2. 切换到Turso
python switch_database.py turso

# 3. 导入数据到Turso
python scripts/import_from_sql.py
```

## 故障排除

### 常见问题
1. **数据库连接失败**
   - 检查环境变量是否正确设置
   - 确认Turso URL和令牌有效

2. **构建失败**
   - 检查requirements.txt中的依赖
   - 确认Python版本兼容性

3. **函数超时**
   - 检查数据库查询性能
   - 考虑添加缓存机制

### 调试命令
```bash
# 测试数据库连接
python database_config.py

# 检查当前配置
python switch_database.py status
```
