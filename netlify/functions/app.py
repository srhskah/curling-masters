#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Netlify Functions - Flask应用适配器
将Flask应用适配为Netlify Functions
"""

import os
import sys
import json
from serverless_wsgi import handle_request

# 添加项目根目录到Python路径
project_root = os.path.join(os.path.dirname(__file__), '..', '..')
sys.path.insert(0, project_root)

# 确保使用Turso数据库（生产环境默认）
if not os.getenv('DATABASE_TYPE'):
    os.environ['DATABASE_TYPE'] = 'turso'

# 设置Flask环境
os.environ['FLASK_ENV'] = 'production'

try:
    # 导入原生Flask应用（包含数据库和Jinja2）
    from app import app
    
    def handler(event, context):
        """Netlify Functions处理器"""
        try:
            print(f"Event: {json.dumps(event)}")
            print(f"Context: {context}")
            result = handle_request(app, event, context)
            print(f"Result status: {result.get('statusCode', 'unknown')}")
            return result
        except Exception as e:
            print(f"Handler error: {str(e)}")
            import traceback
            traceback.print_exc()
            return {
                'statusCode': 500,
                'headers': {
                    'Content-Type': 'text.html; charset=utf-8'
                },
                'body': f'''
                <html>
                <head><title>服务器错误</title></head>
                <body>
                    <h1>服务器内部错误</h1>
                    <p>错误信息: {str(e)}</p>
                    <p>请检查应用配置或联系管理员。</p>
                    <pre>{traceback.format_exc()}</pre>
                </body>
                </html>
                '''
            }
            
except ImportError as e:
    print(f"Import error: {str(e)}")
    
    def handler(event, context):
        """错误处理器"""
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'text/html; charset=utf-8'
            },
            'body': f'''
            <html>
            <head><title>应用加载失败</title></head>
            <body>
                <h1>应用加载失败</h1>
                <p>错误信息: {str(e)}</p>
                <p>请检查应用配置。</p>
            </body>
            </html>
            '''
        }
