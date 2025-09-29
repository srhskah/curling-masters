#!/bin/bash
# Zeabur 启动脚本

echo "🚀 启动 Flask API 服务器..."

# 安装依赖
pip install -r requirements.txt

# 设置环境变量
export DATABASE_TYPE=${DATABASE_TYPE:-"local"}
export SECRET_KEY=${SECRET_KEY:-"curling-masters-secret-key"}
export DB_ENCRYPTION_KEY=${DB_ENCRYPTION_KEY:-"curling-encryption-key"}

# 启动应用
gunicorn app_api_simple:app --bind 0.0.0.0:8080 --workers 1 --timeout 60
