# SQLCipher 数据库配置说明

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
   - 示例：`DATABASE_URL=sqlcipher:///path/to/your/database.db`

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

## 安全建议

1. **密钥管理**: 请勿将真实的加密密钥提交到版本控制系统
2. **密钥强度**: 使用至少32个字符的强密钥
3. **密钥备份**: 安全地备份您的加密密钥，丢失密钥将无法访问数据
4. **定期更新**: 定期更换加密密钥以提高安全性

## 数据库文件

- 默认数据库文件：`curling_masters.db`
- 确保数据库文件已通过 SQLCipher 加密
- 如果数据库未加密，请先使用 SQLCipher 工具进行加密
