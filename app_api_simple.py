#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化的 Flask API 后端
前后端分离架构
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import os
from database_config import get_database_config

# 创建 Flask 应用
app = Flask(__name__)
CORS(app)  # 启用跨域支持

# 数据库配置
config = get_database_config()
app.config.update(config)

@app.route('/', methods=['GET'])
def root():
    """根路径 - 返回完整的 index.html"""
    return '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>冰壶大师赛 API</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: white;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: rgba(255, 255, 255, 0.1);
            padding: 30px;
            border-radius: 15px;
            backdrop-filter: blur(10px);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
        }
        .header {
            text-align: center;
            margin-bottom: 30px;
        }
        .status-card {
            background: rgba(255, 255, 255, 0.2);
            padding: 20px;
            border-radius: 10px;
            margin: 20px 0;
        }
        .btn {
            background: rgba(255, 255, 255, 0.2);
            border: 2px solid white;
            color: white;
            padding: 10px 20px;
            border-radius: 5px;
            cursor: pointer;
            margin: 10px;
            transition: all 0.3s;
            text-decoration: none;
            display: inline-block;
        }
        .btn:hover {
            background: rgba(255, 255, 255, 0.3);
            transform: translateY(-2px);
        }
        .api-link {
            margin: 10px 0;
            padding: 15px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 8px;
            border-left: 4px solid #90EE90;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🏒 冰壶大师赛 API</h1>
            <p>前后端分离架构 - 后端服务</p>
        </div>

        <div class="status-card">
            <h3>✅ 服务状态</h3>
            <p>Flask API 服务器运行正常！</p>
            <p><strong>数据库类型:</strong> ''' + str(app.config.get('DATABASE_TYPE', 'unknown')) + '''</p>
        </div>

        <div class="status-card">
            <h3>🔗 可用 API 端点</h3>
            
            <div class="api-link">
                <strong>GET /api/health</strong><br>
                健康检查 - 验证服务状态
                <br><a href="/api/health" class="btn">访问</a>
            </div>

            <div class="api-link">
                <strong>GET /api/test</strong><br>
                测试接口 - 返回示例数据
                <br><br><a href="/api/test" class="btn">访问</a>
            </div>

            <div class="api-link">
                <strong>GET /api/config</strong><br>
                配置信息 - 查看系统配置
                <br><br><a href="/api/config" class="btn">访问</a>
            </div>
        </div>

        <div class="status-card">
            <h3>📋 下一步</h3>
            <ol>
                <li>测试上述 API 端点是否正常</li>
                <li>确认 Turso 数据库连接配置</li>
                <li>部署后端到 Render/Railway</li>
                <li>部署前端到 Netlify</li>
            </ol>
        </div>
    </div>
</body>
</html>
    '''

@app.route('/api/health', methods=['GET'])
def health():
    """健康检查"""
    return jsonify({
        'status': 'ok',
        'message': 'API is running',
        'database_type': app.config.get('DATABASE_TYPE', 'unknown')
    })

@app.route('/api/test', methods=['GET'])
def test():
    """测试路由"""
    return jsonify({
        'message': 'Hello from Flask API!',
        'timestamp': __import__('datetime').datetime.now().isoformat()
    })

@app.route('/api/config', methods=['GET'])
def config_info():
    """配置信息（调试用）"""
    return jsonify({
        'database_type': app.config.get('DATABASE_TYPE'),
        'database_uri': '***hidden***',
        'environment': 'production'
    })

if __name__ == '__main__':
    print("🚀 启动 Flask API 服务器...")
    print(f"📊 数据库类型: {app.config.get('DATABASE_TYPE')}")
    app.run(debug=True, host='0.0.0.0', port=8080)
