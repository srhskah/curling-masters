#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库配置模块
支持本地SQLCipher和远程Turso数据库的一键切换
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from scripts.sqlcipher_connector import get_sqlcipher_database_uri

def get_database_config():
    """
    获取数据库配置
    支持通过环境变量切换数据库类型
    
    环境变量：
    - DATABASE_TYPE: 'local' 或 'turso' (默认: 'turso' for production)
    - DB_ENCRYPTION_KEY: 本地数据库加密密钥
    - TURSO_URL: Turso数据库URL
    - TURSO_AUTH_TOKEN: Turso认证令牌
    """
    
    # 默认使用Turso数据库（适合生产环境）
    # 如果设置了TURSO_URL和TURSO_AUTH_TOKEN，自动使用Turso
    turso_url = os.getenv('TURSO_URL')
    turso_token = os.getenv('TURSO_AUTH_TOKEN')
    
    if turso_url and turso_token:
        # 如果Turso配置完整，默认使用Turso
        database_type = os.getenv('DATABASE_TYPE', 'turso').lower()
    else:
        # 如果Turso配置不完整，使用本地数据库
        database_type = os.getenv('DATABASE_TYPE', 'local').lower()
    
    if database_type == 'turso':
        return get_turso_config()
    else:
        return get_local_config()

def get_local_config():
    """获取本地SQLCipher数据库配置"""
    db_path = os.path.join(os.path.dirname(__file__), 'curling_masters.db')
    encryption_key = os.getenv('DB_ENCRYPTION_KEY', 'default_key_change_me')
    
    # 使用自定义SQLCipher连接器
    database_uri = get_sqlcipher_database_uri(db_path, encryption_key)
    
    return {
        'DATABASE_TYPE': 'local',
        'SQLALCHEMY_DATABASE_URI': database_uri,
        'SQLALCHEMY_ENGINE_OPTIONS': {
            'poolclass': NullPool,
            'connect_args': {
                'timeout': 30,
                'check_same_thread': False
            }
        }
    }

def get_turso_config():
    """获取Turso远程数据库配置"""
    turso_url = os.getenv('TURSO_URL')
    turso_token = os.getenv('TURSO_AUTH_TOKEN')
    
    if not turso_url or not turso_token:
        print("⚠️  Turso配置不完整，回退到本地SQLite数据库")
        return get_local_config()
    
    # 规范化 URL：允许传入已包含协议的 URL 或纯主机名
    # 合法示例：
    # - libsql://<db-host>.turso.io
    # - https://<db-host>.turso.io
    # - <db-host>.turso.io
    url = turso_url.strip()
    if not (url.startswith('libsql://') or url.startswith('https://') or url.startswith('libsql+https://')):
        # 默认采用 libsql+https 以避免 308 重定向（Hrana 走 HTTPS）
        url = f"libsql+https://{url}"

    # 将 authToken 作为查询参数附加（若未包含）
    separator = '&' if ('?' in url) else '?'
    params = []
    if 'authToken=' not in url:
        params.append(f"authToken={turso_token}")
    # 提示驱动使用安全连接并尽量跟随重定向，减少 308 问题
    if 'secure=' not in url and 'tls=' not in url:
        params.append('secure=true')
    if 'follow_redirects=' not in url:
        params.append('follow_redirects=true')
    if params:
        url = f"{url}{separator}{'&'.join(params)}"

    print("✅ 使用 Turso 远程数据库")
    print(f"   Turso URL: {turso_url}")
    print(f"   认证令牌: {'已设置' if turso_token else '未设置'}")

    # 兼容不同版本驱动可能接受的关键字参数
    connect_args = {
        'timeout': 30,
        # 常见键名
        'authToken': turso_token,
        'secure': True,
        'follow_redirects': True,
        # 兼容形式
        'auth_token': turso_token,
        'tls': True,
    }

    return {
        'DATABASE_TYPE': 'turso',
        'SQLALCHEMY_DATABASE_URI': url,
        'SQLALCHEMY_ENGINE_OPTIONS': {
            'poolclass': NullPool,
            'connect_args': connect_args
        }
    }

def switch_to_local():
    """切换到本地数据库"""
    os.environ['DATABASE_TYPE'] = 'local'
    print("已切换到本地SQLCipher数据库")

def switch_to_turso():
    """切换到Turso数据库"""
    os.environ['DATABASE_TYPE'] = 'turso'
    print("已切换到Turso远程数据库")

def get_current_database_type():
    """获取当前数据库类型"""
    turso_url = os.getenv('TURSO_URL')
    turso_token = os.getenv('TURSO_AUTH_TOKEN')
    
    if turso_url and turso_token:
        return os.getenv('DATABASE_TYPE', 'turso').lower()
    else:
        return os.getenv('DATABASE_TYPE', 'local').lower()

def print_database_info():
    """打印当前数据库配置信息"""
    db_type = get_current_database_type()
    print(f"当前数据库类型: {db_type}")
    
    if db_type == 'local':
        db_path = os.path.join(os.path.dirname(__file__), 'curling_masters.db')
        print(f"本地数据库路径: {db_path}")
        print(f"数据库文件存在: {os.path.exists(db_path)}")
    else:
        turso_url = os.getenv('TURSO_URL', '未设置')
        print(f"Turso URL: {turso_url}")
        print(f"认证令牌: {'已设置' if os.getenv('TURSO_AUTH_TOKEN') else '未设置'}")

if __name__ == "__main__":
    # 测试数据库配置
    print("=== 数据库配置测试 ===")
    print_database_info()
    
    try:
        config = get_database_config()
        print(f"数据库URI: {config['SQLALCHEMY_DATABASE_URI'][:50]}...")
        print("配置加载成功！")
    except Exception as e:
        print(f"配置加载失败: {e}")
