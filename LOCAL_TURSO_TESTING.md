# 本地Turso数据库测试指南

## 快速开始

### 方法1：使用测试工具
```bash
python local_turso_test.py
```

### 方法2：手动设置环境变量
```bash
# Windows PowerShell
$env:DATABASE_TYPE="turso"
$env:TURSO_URL="libsql://curling-masters-srhskah.aws-ap-northeast-1.turso.io"
$env:TURSO_AUTH_TOKEN="your-token"
$env:SECRET_KEY="35dbd882431eaa21e81c3cc9f884efd97a18e359b85df5bc89119a92f40b8d92"

# 启动应用
python app.py
```

```bash
# Linux/Mac
export DATABASE_TYPE=turso
export TURSO_URL=libsql://curling-masters-srhskah.aws-ap-northeast-1.turso.io
export TURSO_AUTH_TOKEN=your-token
export SECRET_KEY=35dbd882431eaa21e81c3cc9f884efd97a18e359b85df5bc89119a92f40b8d92

# 启动应用
python app.py
```

### 方法3：使用.env文件
创建 `.env` 文件：
```bash
DATABASE_TYPE=turso
TURSO_URL=libsql://curling-masters-srhskah.aws-ap-northeast-1.turso.io
TURSO_AUTH_TOKEN=your-token-here
SECRET_KEY=35dbd882431eaa21e81c3cc9f884efd97a18e359b85df5bc89119a92f40b8d92
```

然后启动应用：
```bash
python app.py
```

## 数据库切换

### 切换到Turso数据库
```bash
python switch_database.py turso
```

### 切换回本地数据库
```bash
python switch_database.py local
```

### 查看当前状态
```bash
python switch_database.py status
```

## 重要说明

### ⚠️ 本地开发限制
由于本地环境缺少libsql驱动，当前实现使用以下fallback方案：
1. **开发环境**: 使用临时SQLite数据库模拟Turso连接
2. **生产环境**: 在Netlify等云环境中使用真实的Turso连接

### ✅ 推荐测试流程
1. **本地开发**: 使用本地SQLCipher数据库
2. **功能测试**: 通过环境变量模拟Turso配置
3. **部署测试**: 在Netlify上使用真实Turso数据库

### 🔧 故障排除

**问题1: libsql驱动不可用**
```
解决方案: 本地使用SQLite兼容模式，部署时自动切换到Turso
```

**问题2: 环境变量未生效**
```bash
# 检查环境变量
python switch_database.py status

# 重新设置环境变量
python local_turso_test.py
```

**问题3: 连接超时**
```
解决方案: 检查网络连接，确认Turso URL和Token正确
```

## 测试验证

### 1. 启动应用
```bash
python app.py
```

### 2. 访问测试页面
- 主页: http://localhost:5000
- 管理后台: http://localhost:5000/admin-secret

### 3. 验证数据库连接
- 查看控制台输出的数据库类型
- 测试数据的读取和写入
- 确认功能正常运行

## 部署准备

### 环境变量检查清单
- [x] DATABASE_TYPE=turso
- [x] TURSO_URL=your-turso-url
- [x] TURSO_AUTH_TOKEN=your-token
- [x] SECRET_KEY=your-secret-key

### Netlify部署
1. 推送代码到GitHub
2. 在Netlify中设置环境变量
3. 部署应用
4. 验证Turso连接

本地测试完成后即可部署到Netlify！
