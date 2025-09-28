#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Netlify Functions - Flask应用适配器
将Flask应用适配为Netlify Functions
"""

import os
import sys
from serverless_wsgi import handle_request

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# 导入Flask应用
from app import app

# 确保使用Turso数据库（生产环境默认）
if not os.getenv('DATABASE_TYPE'):
    os.environ['DATABASE_TYPE'] = 'turso'

def handler(event, context):
    """Netlify Functions处理器"""
    return handle_request(app, event, context)
