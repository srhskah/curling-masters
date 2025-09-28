# SQLCipher 数据库配置说明

## 概述

本项目已成功配置为使用 SQLCipher 加密数据库。SQLCipher 是 SQLite 的加密版本，提供透明的数据库加密功能。

## 技术实现

### 使用的库
- **apsw**: Another Python SQLite Wrapper，提供对 SQLCipher 的支持
- **SQLAlchemy**: ORM 框架，通过事件监听器处理加密
- **Flask-SQLAlchemy**: Flask 的 SQLAlchemy 扩展

### 配置方式
1. 使用标准的 `sqlite://` 协议
2. 通过 SQLAlchemy 事件监听器在连接时设置加密密钥
3. 使用 `apsw` 作为底层 SQLite 驱动

## 环境变量配置

为了使用 SQLCipher 加密数据库，您需要设置以下环境变量：

### 必需的环境变量

1. **DB_ENCRYPTION_KEY**: 数据库加密密钥
   - 这是访问加密数据库的密钥
   - 请使用强密钥（建议至少32个字符）
   - 示例：`DB_ENCRYPTION_KEY=your_very_strong_encryption_key_here_32_chars_min`

2. **SECRET_KEY**: Flask 应用密钥
   - 用于会话管理和安全功能
   - 示例：`SECRET_KEY=your_flask_secret_key_here`

### 可选的环境变量

3. **DATABASE_URL**: 自定义数据库连接字符串
   - 如果使用默认配置，可以省略
   - 示例：`DATABASE_URL=sqlite:///path/to/your/database.db`

## 设置方法

### Windows (PowerShell)
```powershell
$env:DB_ENCRYPTION_KEY="your_very_strong_encryption_key_here_32_chars_min"
$env:SECRET_KEY="your_flask_secret_key_here"
```

### Windows (CMD)
```cmd
set DB_ENCRYPTION_KEY=your_very_strong_encryption_key_here_32_chars_min
set SECRET_KEY=your_flask_secret_key_here
```

### Linux/Mac
```bash
export DB_ENCRYPTION_KEY="your_very_strong_encryption_key_here_32_chars_min"
export SECRET_KEY="your_flask_secret_key_here"
```

## 数据库文件

- **主数据库文件**: `curling_masters.db` (已加密)
- **备份文件**: `curling_masters.db.bak` (未加密)
- **未加密版本**: `curling_masters_unencrypted.db` (用于开发)

## 项目文件说明

### 核心文件
- `app.py`: Flask 应用主文件，包含 SQLCipher 配置
- `sqlcipher_connector.py`: SQLCipher 连接器和工具函数
- `models.py`: 数据库模型定义
- `requirements.txt`: 项目依赖

### 工具脚本
- `encrypt_database.py`: 数据库加密工具
- `migrate_database.py`: 数据库架构迁移工具
- `test_sqlcipher_connection.py`: SQLCipher 连接测试
- `test_app_sqlcipher.py`: 应用和数据库集成测试
- `check_database.py`: 数据库状态检查工具

## 安全建议

1. **密钥管理**: 请勿将真实的加密密钥提交到版本控制系统
2. **密钥强度**: 使用至少32个字符的强密钥
3. **密钥备份**: 安全地备份您的加密密钥，丢失密钥将无法访问数据
4. **定期更新**: 定期更换加密密钥以提高安全性
5. **环境隔离**: 在不同环境（开发、测试、生产）使用不同的加密密钥

## 故障排除

### 常见问题

1. **"Can't load plugin" 错误**
   - 确保已安装 `apsw` 库：`pip install apsw`
   - 检查 Python 版本兼容性

2. **"file is not a database" 错误**
   - 检查数据库文件是否已正确加密
   - 验证加密密钥是否正确

3. **"no such column" 错误**
   - 运行数据库迁移脚本：`python migrate_database.py`
   - 检查模型定义和数据库架构是否匹配

4. **连接超时**
   - 检查数据库文件是否被其他进程占用
   - 增加连接超时时间

### 测试命令

```bash
# 测试数据库连接
python test_sqlcipher_connection.py

# 测试应用配置
python test_app_sqlcipher.py

# 检查数据库状态
python check_database.py

# 运行数据库迁移
python migrate_database.py
```

## 开发注意事项

1. **数据库备份**: 在进行任何数据库操作前，请先备份数据库文件
2. **架构变更**: 修改模型后，需要运行迁移脚本更新数据库架构
3. **密钥管理**: 开发环境可以使用默认密钥，但生产环境必须使用强密钥
4. **性能考虑**: SQLCipher 加密会略微影响数据库性能，但提供了重要的安全保障

## 更新日志

- **2024-01-XX**: 成功集成 SQLCipher 加密数据库
- **2024-01-XX**: 解决 pysqlcipher3 安装问题，改用 apsw
- **2024-01-XX**: 完成数据库架构迁移
- **2024-01-XX**: 实现应用和数据库集成测试
