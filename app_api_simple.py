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
 
# 确保注册 libsql 方言
try:
    import sqlalchemy_libsql  # noqa: F401
except Exception as _e:
    # 延迟到 /api/turso-test 再反馈详细错误
    pass

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

@app.route('/api/deps', methods=['GET'])
def deps():
    """依赖与方言检测"""
    info = {
        'sqlalchemy_version': None,
        'sqlalchemy_libsql_importable': False,
        'sqlalchemy_libsql_version': None,
        'entrypoint_libsql_ok': False,
        'message': ''
    }
    try:
        import sqlalchemy
        info['sqlalchemy_version'] = getattr(sqlalchemy, '__version__', 'unknown')
    except Exception as e:
        info['message'] = f'sqlalchemy import error: {e}'
        return jsonify(info), 500

    try:
        import sqlalchemy_libsql as _sl
        info['sqlalchemy_libsql_importable'] = True
        info['sqlalchemy_libsql_version'] = getattr(_sl, '__version__', 'unknown')
    except Exception as e:
        info['message'] = f'sqlalchemy_libsql import error: {e}'
        return jsonify(info), 500

    # 检测方言是否可被 SQLAlchemy 解析
    try:
        from sqlalchemy.dialects import registry
        # 尝试通过 registry 加载 libsql 方言
        loaded = False
        try:
            registry.load('libsql')
            loaded = True
        except Exception:
            loaded = False
        info['entrypoint_libsql_ok'] = loaded
        if not loaded:
            info['message'] = 'sqlalchemy.dialects registry cannot load libsql (entrypoint 未注册)'
    except Exception as e:
        info['message'] = f'registry check error: {e}'
        return jsonify(info), 500

    status_code = 200 if info['entrypoint_libsql_ok'] else 500
    return jsonify(info), status_code

@app.route('/api/turso-test', methods=['GET'])
def turso_test():
    """Turso 数据库连接测试（直接使用 SQLAlchemy Engine）"""
    from sqlalchemy import create_engine, text
    uri = app.config.get('SQLALCHEMY_DATABASE_URI')
    if not uri:
        return jsonify({'status': 'error', 'error': 'No SQLALCHEMY_DATABASE_URI configured'}), 500

    try:
        engine = create_engine(uri, pool_pre_ping=True)
        with engine.connect() as conn:
            row = conn.execute(text("SELECT datetime('now') as current_time"))
            result = row.fetchone()
        return jsonify({
            'status': 'success',
            'database_type': app.config.get('DATABASE_TYPE'),
            'uri_scheme': uri.split(':', 1)[0],
            'test_query': str(result[0]) if result else 'No result',
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'database_type': app.config.get('DATABASE_TYPE'),
            'error': str(e),
        }), 500

if __name__ == '__main__':
    print("🚀 启动 Flask API 服务器...")
    print(f"📊 数据库类型: {app.config.get('DATABASE_TYPE')}")
    app.run(debug=True, host='0.0.0.0', port=8080)
