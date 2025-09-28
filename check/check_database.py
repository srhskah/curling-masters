#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查数据库文件状态
"""

import apsw
import os

def check_database():
    """检查数据库文件状态"""
    db_path = 'curling_masters.db'
    
    if not os.path.exists(db_path):
        print(f"❌ 数据库文件不存在: {db_path}")
        return False
    
    print(f"✅ 数据库文件存在: {db_path}")
    print(f"文件大小: {os.path.getsize(db_path)} 字节")
    
    try:
        # 尝试作为普通 SQLite 数据库打开
        conn = apsw.Connection(db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor]
        
        print(f"✅ 作为普通 SQLite 数据库打开成功!")
        print(f"发现 {len(tables)} 个表:")
        for table in tables:
            print(f"  - {table}")
        
        return True
        
    except Exception as e:
        print(f"❌ 作为普通 SQLite 数据库打开失败: {e}")
        
        # 尝试作为 SQLCipher 数据库打开
        try:
            conn = apsw.Connection(db_path)
            conn.execute("PRAGMA key = 'default_key_change_me';")
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cursor]
            
            print(f"✅ 作为 SQLCipher 数据库打开成功!")
            print(f"发现 {len(tables)} 个表:")
            for table in tables:
                print(f"  - {table}")
            
            return True
            
        except Exception as e2:
            print(f"❌ 作为 SQLCipher 数据库打开也失败: {e2}")
            return False

if __name__ == "__main__":
    check_database()
