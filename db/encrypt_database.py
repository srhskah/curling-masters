#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 SQLite 数据库加密为 SQLCipher 格式
"""

import apsw
import os
import shutil

def encrypt_database(source_db, target_db, encryption_key):
    """
    将 SQLite 数据库加密为 SQLCipher 格式
    
    Args:
        source_db: 源数据库文件路径
        target_db: 目标加密数据库文件路径
        encryption_key: 加密密钥
    """
    try:
        # 备份原文件
        backup_file = f"{source_db}.backup_before_encryption"
        shutil.copy2(source_db, backup_file)
        print(f"✅ 已创建备份文件: {backup_file}")
        
        # 打开源数据库
        source_conn = apsw.Connection(source_db)
        
        # 创建加密数据库
        target_conn = apsw.Connection(target_db)
        
        # 设置加密密钥
        target_conn.execute(f"PRAGMA key = '{encryption_key}';")
        
        # 复制所有数据
        print("正在复制数据库结构...")
        
        # 获取所有表结构
        cursor = source_conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        tables = [row[0] for row in cursor]
        
        for table_sql in tables:
            if table_sql:
                target_conn.execute(table_sql)
                print(f"  - 创建表: {table_sql.split('(')[0].split()[-1]}")
        
        # 复制数据
        print("正在复制数据...")
        cursor = source_conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        table_names = [row[0] for row in cursor]
        
        for table_name in table_names:
            # 获取表结构
            cursor = source_conn.execute(f"PRAGMA table_info({table_name});")
            columns = [row[1] for row in cursor]
            
            # 复制数据
            cursor = source_conn.execute(f"SELECT * FROM {table_name};")
            rows = cursor.fetchall()
            
            if rows:
                # 构建插入语句
                placeholders = ','.join(['?' for _ in columns])
                insert_sql = f"INSERT INTO {table_name} VALUES ({placeholders});"
                
                for row in rows:
                    target_conn.execute(insert_sql, row)
                
                print(f"  - 复制表 {table_name}: {len(rows)} 行")
        
        # 复制索引
        print("正在复制索引...")
        cursor = source_conn.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%';")
        indexes = [row[0] for row in cursor]
        
        for index_sql in indexes:
            if index_sql:
                target_conn.execute(index_sql)
                print(f"  - 创建索引: {index_sql.split()[-1]}")
        
        print("✅ 数据库加密完成!")
        
        # 验证加密数据库
        print("正在验证加密数据库...")
        cursor = target_conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor]
        print(f"✅ 加密数据库验证成功，包含 {len(tables)} 个表")
        
        return True
        
    except Exception as e:
        print(f"❌ 数据库加密失败: {e}")
        return False

def test_encrypted_database(db_path, encryption_key):
    """测试加密数据库"""
    try:
        conn = apsw.Connection(db_path)
        conn.execute(f"PRAGMA key = '{encryption_key}';")
        
        cursor = conn.execute("SELECT COUNT(*) FROM players;")
        count = cursor.fetchone()[0]
        
        print(f"✅ 加密数据库测试成功，players 表有 {count} 条记录")
        return True
        
    except Exception as e:
        print(f"❌ 加密数据库测试失败: {e}")
        return False

if __name__ == "__main__":
    # 配置
    source_db = "curling_masters.db"
    target_db = "curling_masters_encrypted.db"
    encryption_key = os.getenv('DB_ENCRYPTION_KEY', 'default_key_change_me')
    
    print("=" * 50)
    print("SQLite 数据库加密工具")
    print("=" * 50)
    print(f"源数据库: {source_db}")
    print(f"目标数据库: {target_db}")
    print(f"加密密钥: {'*' * len(encryption_key)} (长度: {len(encryption_key)})")
    
    # 检查源数据库
    if not os.path.exists(source_db):
        print(f"❌ 源数据库文件不存在: {source_db}")
        exit(1)
    
    # 执行加密
    if encrypt_database(source_db, target_db, encryption_key):
        # 测试加密数据库
        if test_encrypted_database(target_db, encryption_key):
            print("\n✅ 数据库加密和验证都成功完成!")
            print(f"加密后的数据库文件: {target_db}")
        else:
            print("\n❌ 加密数据库验证失败")
    else:
        print("\n❌ 数据库加密失败")
