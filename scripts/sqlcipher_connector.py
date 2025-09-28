#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SQLCipher 数据库连接模块
使用 apsw 和自定义连接器来处理加密数据库
"""

import os
import apsw
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.dialects.sqlite.base import SQLiteDialect
from sqlalchemy.engine import Engine
from sqlalchemy.pool import Pool
import logging

logger = logging.getLogger(__name__)

class SQLCipherDialect(SQLiteDialect):
    """自定义 SQLCipher 方言"""
    
    def create_connect_args(self, url):
        """创建连接参数"""
        opts = url.translate_connect_args()
        opts.update(url.query)
        
        # 获取加密密钥
        encryption_key = opts.pop('key', None)
        if not encryption_key:
            encryption_key = os.getenv('DB_ENCRYPTION_KEY', 'default_key_change_me')
        
        # 设置连接参数
        connect_args = {
            'timeout': int(opts.pop('timeout', 30)),
            'check_same_thread': opts.pop('check_same_thread', False),
        }
        
        return [], connect_args, encryption_key

def create_sqlcipher_engine(database_path, encryption_key=None):
    """
    创建 SQLCipher 数据库引擎
    
    Args:
        database_path: 数据库文件路径
        encryption_key: 加密密钥
    
    Returns:
        SQLAlchemy Engine 对象
    """
    if not encryption_key:
        encryption_key = os.getenv('DB_ENCRYPTION_KEY', 'default_key_change_me')
    
    # 创建自定义连接器
    def connect():
        """创建加密数据库连接"""
        conn = apsw.Connection(database_path)
        
        # 设置加密密钥
        conn.execute(f"PRAGMA key = '{encryption_key}';")
        
        # 验证连接是否成功
        try:
            conn.execute("SELECT 1;")
            logger.info("SQLCipher 数据库连接成功")
        except Exception as e:
            logger.error(f"SQLCipher 数据库连接失败: {e}")
            raise
        
        return conn
    
    # 创建引擎
    engine = create_engine(
        'sqlite:///',  # 使用默认的 SQLite URL
        creator=connect,
        poolclass=NullPool,
        echo=False
    )
    
    return engine

def get_sqlcipher_database_uri(database_path, encryption_key=None):
    """
    获取 SQLCipher 数据库的 URI 字符串
    
    Args:
        database_path: 数据库文件路径
        encryption_key: 加密密钥
    
    Returns:
        数据库 URI 字符串
    """
    if not encryption_key:
        encryption_key = os.getenv('DB_ENCRYPTION_KEY', 'default_key_change_me')
    
    # 使用标准的 sqlite 协议，通过事件监听器处理加密
    return f'sqlite:///{database_path}'

def test_sqlcipher_connection(database_path, encryption_key=None):
    """
    测试 SQLCipher 数据库连接
    
    Args:
        database_path: 数据库文件路径
        encryption_key: 加密密钥
    
    Returns:
        bool: 连接是否成功
    """
    try:
        if not encryption_key:
            encryption_key = os.getenv('DB_ENCRYPTION_KEY', 'default_key_change_me')
        
        conn = apsw.Connection(database_path)
        conn.execute(f"PRAGMA key = '{encryption_key}';")
        
        # 测试查询
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor]
        
        print(f"✅ SQLCipher 数据库连接成功!")
        print(f"发现 {len(tables)} 个表:")
        for table in tables:
            print(f"  - {table}")
        
        return True
        
    except Exception as e:
        print(f"❌ SQLCipher 数据库连接失败: {e}")
        return False

if __name__ == "__main__":
    # 测试连接
    db_path = os.path.join(os.path.dirname(__file__), 'curling_masters.db')
    test_sqlcipher_connection(db_path)
