#!/usr/bin/env python3
"""
Frozen-Flask 开发环境运行脚本
支持热重载和完整 Flask 功能
"""

from flask_frozen import Freezer
from app_frozen import app

freezer = Freezer(app)

if __name__ == '__main__':
    print("🚀 启动开发服务器...")
    print("📝 支持热重载和完整 Flask 功能")
    print("🌐 访问: http://localhost:5000")
    print("💡 修改 templates/ 和 app.py 后自动重载")
    
    # 开发模式，支持热重载
    freezer.run(debug=True, host='0.0.0.0', port=5000)
