# Netlify部署修复指南

## 🔧 问题诊断

根据Turso官方文档和当前部署情况，主要问题包括：

1. **Turso连接配置错误** - 使用了临时SQLite fallback而非真正的libsql驱动
2. **Netlify配置不完整** - 发布目录和重定向规则需要调整
3. **依赖包版本问题** - 需要正确的libsql-sqlalchemy版本

## ✅ 已修复的配置

### 1. 更新Turso数据库连接

**`database_config.py`** - 使用真正的libsql驱动：
```python
def get_turso_config():
    """获取Turso远程数据库配置"""
    turso_url = os.getenv('TURSO_URL')
    turso_token = os.getenv('TURSO_AUTH_TOKEN')
    
    if not turso_url or not turso_token:
        raise ValueError("Turso配置不完整，请设置TURSO_URL和TURSO_AUTH_TOKEN环境变量")
    
    # 使用libsql-sqlalchemy驱动连接Turso
    # 根据Turso官方文档：https://docs.turso.tech/sdk/ts/quickstart
    database_uri = f"libsql://{turso_url.replace('libsql://', '')}?authToken={turso_token}"
    
    return {
        'SQLALCHEMY_DATABASE_URI': database_uri,
        'SQLALCHEMY_ENGINE_OPTIONS': {
            'poolclass': NullPool,
            'connect_args': {
                'timeout': 30,
                'check_same_thread': False
            }
        }
    }
```

### 2. 更新依赖包

**`requirements.txt`** - 添加libsql-sqlalchemy：
```
Flask==2.3.3
SQLAlchemy==2.0.36
Flask-SQLAlchemy==3.0.3
python-dotenv==1.0.0
apsw==3.50.4.0
libsql-client==0.2.0
serverless-wsgi==3.1.0
libsql-sqlalchemy==0.1.0
```

### 3. 修复Netlify配置

**`netlify.toml`** - 简化配置：
```toml
[build]
  command = "pip install -r requirements.txt"
  publish = "."

[build.environment]
  PYTHON_VERSION = "3.11"
  DATABASE_TYPE = "turso"

[[redirects]]
  from = "/*"
  to = "/.netlify/functions/app"
  status = 200

[functions]
  directory = "netlify/functions"
```

## 🚀 部署步骤

### 1. 提交修复
```bash
git add .
git commit -m "Fix Turso database connection and Netlify deployment"
git push origin main
```

### 2. 设置Netlify环境变量

在Netlify控制台 → Site settings → Environment variables 中添加：

```
DATABASE_TYPE = turso
TURSO_URL = libsql://curling-masters-srhskah.aws-ap-northeast-1.turso.io
TURSO_AUTH_TOKEN = eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3NTg5NzQ4OTUsImlkIjoiZTgwYTQ1NzAtYmEzOC00OTA5LWI0MGUtZDMyYjMxOGNiODg2IiwicmlkIjoiOTU4MjRlOTAtZjEwMi00NWYwLTg3ZmItOTg2OWVmMWM4OGQwIn0.8Z71cnPaikSoElncKie4clMQ7n_PZhynGmXbm14vU1nu1QNsqzEMrEANC-mgAJBqlSpuQJG06VQNzBKoPowxDQ
SECRET_KEY = 35dbd882431eaa21e81c3cc9f884efd97a18e359b85df5bc89119a92f40b8d92
```

### 3. 验证部署

1. 等待Netlify重新部署完成
2. 访问 `https://curling-masters.netlify.app`
3. 检查应用是否正常加载
4. 查看Netlify函数日志确认Turso连接

## 🔍 故障排除

### 如果仍然出现"Page Not Found"：

1. **检查函数日志**：
   - Netlify控制台 → Functions → 查看错误日志
   - 确认libsql-sqlalchemy是否正确安装

2. **验证环境变量**：
   - 确认TURSO_URL和TURSO_AUTH_TOKEN已正确设置
   - 检查SECRET_KEY是否有效

3. **测试Turso连接**：
   - 使用本地测试脚本验证数据库连接
   - 确认数据库表结构正确

### 常见错误及解决方案：

**错误：`Can't load plugin: sqlalchemy.dialects:libsql`**
- 解决：确保libsql-sqlalchemy==0.1.0已安装

**错误：`Turso配置不完整`**
- 解决：检查环境变量TURSO_URL和TURSO_AUTH_TOKEN

**错误：`ImportError: No module named 'app'`**
- 解决：检查netlify/functions/app.py中的导入路径

## 📋 检查清单

- [x] 更新database_config.py使用libsql驱动
- [x] 添加libsql-sqlalchemy到requirements.txt
- [x] 修复netlify.toml配置
- [x] 删除不必要的netlify/index.html
- [ ] 提交并推送修复
- [ ] 设置Netlify环境变量
- [ ] 验证部署成功

现在可以提交这些修复并重新部署了！
