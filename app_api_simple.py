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
    # 优先尝试官方注册入口（0.2.0 起应已提供 entrypoint）
    from sqlalchemy.dialects import registry as _registry
    try:
        _registry.load('libsql')
    except Exception:
        # 兜底注册（兼容旧版本的路径）
        for module_path, obj_name in [
            ('sqlalchemy_libsql', 'dialect'),
            ('sqlalchemy_libsql.dialect', 'dialect'),
            ('sqlalchemy_libsql.libsql', 'dialect'),
            ('sqlalchemy_libsql.libsql', 'LibSQLDialect'),
        ]:
            try:
                _registry.register('libsql', module_path, obj_name)
                _registry.load('libsql')
                break
            except Exception:
                continue
except Exception as _e:
    # 延迟到 /api/turso-test 再反馈详细错误
    pass

def _ensure_libsql_dialect_registered():
    """确保 SQLAlchemy 能加载到 libsql 方言，必要时手动注册。
    返回 (import_ok, registered_ok, message)
    """
    import_ok = False
    registered_ok = False
    message = ''
    try:
        import sqlalchemy_libsql  # noqa: F401
        import_ok = True
    except Exception as e:
        message = f'sqlalchemy_libsql import error: {e}'
        return import_ok, registered_ok, message

    try:
        from sqlalchemy.dialects import registry
        # 先尝试直接加载
        try:
            registry.load('libsql')
            registered_ok = True
            return import_ok, registered_ok, message
        except Exception:
            # 未注册则手动注册，尝试多种候选位置
            candidates = [
                ('sqlalchemy_libsql', 'dialect'),
                ('sqlalchemy_libsql.dialect', 'dialect'),
                ('sqlalchemy_libsql.base', 'dialect'),
                ('sqlalchemy_libsql.base', 'LibSQLDialect'),
                ('sqlalchemy_libsql.libsql', 'dialect'),
                ('sqlalchemy_libsql.libsql', 'LibSQLDialect'),
            ]
            last_error = None
            for module_path, obj_name in candidates:
                try:
                    registry.register('libsql', module_path, obj_name)
                    registry.load('libsql')
                    registered_ok = True
                    message = f'registered via {module_path}:{obj_name}'
                    break
                except Exception as e2:
                    last_error = e2
            if not registered_ok:
                message = f'failed to register libsql dialect; last_error={last_error}'
    except Exception as e:
        message = f'registry access error: {e}'
    return import_ok, registered_ok, message

# 创建 Flask 应用
app = Flask(__name__)
CORS(app)  # 启用跨域支持

# 数据库配置
config = get_database_config()
app.config.update(config)

# 启动时打印明显标记与关键信息，便于在 Zeabur 日志确认版本是否已更新
try:
    from urllib.parse import urlparse, parse_qsl
    from datetime import datetime
    uri_boot = app.config.get('SQLALCHEMY_DATABASE_URI', '') or ''
    parsed_boot = urlparse(uri_boot) if uri_boot else None
    q_boot = dict(parse_qsl(parsed_boot.query)) if parsed_boot else {}
    print("=== BOOT_MARKER v2 ===")
    print(f"time={datetime.utcnow().isoformat()}Z")
    print(f"db.scheme={(parsed_boot.scheme if parsed_boot else '')}")
    print(f"db.has_authToken={'authToken' in q_boot}")
    print(f"db.has_secure={'secure' in q_boot or 'tls' in q_boot}")
    print(f"db.has_follow_redirects={'follow_redirects' in q_boot}")
except Exception as _boot_err:
    print("=== BOOT_MARKER v2 (error) ===", str(_boot_err))

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

@app.route('/api/health2', methods=['GET'])
def health2():
    """健康检查（含版本标记）"""
    from datetime import datetime
    uri = app.config.get('SQLALCHEMY_DATABASE_URI', '') or ''
    scheme = uri.split(':', 1)[0] if uri else ''
    return jsonify({
        'status': 'ok',
        'marker': 'health2-v2',
        'utc': datetime.utcnow().isoformat() + 'Z',
        'database_type': app.config.get('DATABASE_TYPE', 'unknown'),
        'uri_scheme': scheme
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

@app.route('/api/pip', methods=['GET'])
def pip_info():
    """显示关键包版本，帮助判断是否使用了旧缓存或预发布版。"""
    try:
        from importlib import metadata as importlib_metadata
    except Exception:
        import importlib_metadata  # type: ignore

    def get_ver(name):
        try:
            return importlib_metadata.version(name)
        except Exception:
            return None

    data = {
        'sqlalchemy': get_ver('SQLAlchemy'),
        'sqlalchemy-libsql': get_ver('sqlalchemy-libsql'),
        'flask': get_ver('Flask'),
        'gunicorn': get_ver('gunicorn'),
    }
    # 简单校验要求
    require_ok = True
    msg = []
    ver = data.get('sqlalchemy-libsql')
    if ver is None:
        require_ok = False
        msg.append('sqlalchemy-libsql 未安装')
    else:
        msg.append(f'sqlalchemy-libsql={ver}')
        # 期望 0.2.0 及以上
        try:
            from packaging.version import Version
            if Version(ver) < Version('0.2.0'):
                require_ok = False
                msg.append('版本过低，需 >= 0.2.0')
        except Exception:
            pass

    return jsonify({'packages': data, 'ok': require_ok, 'note': '; '.join(msg)}), (200 if require_ok else 500)

@app.route('/api/env-check', methods=['GET'])
def env_check():
    """检查关键 Turso 环境变量是否存在（不回显真实值）。"""
    def _mask(val: str | None) -> str:
        if not val:
            return 'missing'
        return f"set(len={len(val)})"

    from urllib.parse import urlparse, parse_qsl
    uri = app.config.get('SQLALCHEMY_DATABASE_URI')
    parsed = None
    q = {}
    try:
        parsed = urlparse(uri) if uri else None
        q = dict(parse_qsl(parsed.query)) if parsed else {}
    except Exception:
        parsed = None
        q = {}

    return jsonify({
        'DATABASE_TYPE': os.getenv('DATABASE_TYPE', 'missing'),
        'TURSO_URL': _mask(os.getenv('TURSO_URL')),
        'TURSO_AUTH_TOKEN': _mask(os.getenv('TURSO_AUTH_TOKEN')),
        'uri_scheme': (parsed.scheme if parsed else None),
        'uri_has_authToken': ('authToken' in q),
        'uri_has_secure': (('secure' in q) or ('tls' in q)),
        'uri_has_follow_redirects': ('follow_redirects' in q),
    })

@app.route('/api/turso-test', methods=['GET'])
def turso_test():
    """Turso 数据库连接测试（直接使用 SQLAlchemy Engine）"""
    from sqlalchemy import create_engine, text
    uri = app.config.get('SQLALCHEMY_DATABASE_URI')
    if not uri:
        return jsonify({'status': 'error', 'error': 'No SQLALCHEMY_DATABASE_URI configured'}), 500

    try:
        import_ok, registered_ok, reg_msg = _ensure_libsql_dialect_registered()
        engine = create_engine(uri, pool_pre_ping=True)
        with engine.connect() as conn:
            row = conn.execute(text("SELECT datetime('now') as current_time"))
            result = row.fetchone()
        return jsonify({
            'status': 'success',
            'database_type': app.config.get('DATABASE_TYPE'),
            'uri_scheme': uri.split(':', 1)[0],
            'test_query': str(result[0]) if result else 'No result',
            'libsql_import_ok': import_ok,
            'libsql_registered_ok': registered_ok,
            'libsql_message': reg_msg,
            'note': 'using URL query + connect_args for authToken/secure/follow_redirects',
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'database_type': app.config.get('DATABASE_TYPE'),
            'error': str(e),
            'uri_scheme': (uri.split(':', 1)[0] if uri else None),
        }), 500

if __name__ == '__main__':
    print("🚀 启动 Flask API 服务器...")
    print(f"📊 数据库类型: {app.config.get('DATABASE_TYPE')}")
    app.run(debug=True, host='0.0.0.0', port=8080)
