#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查数据库架构
"""

import apsw

def check_database_schema():
    """检查数据库架构"""
    try:
        conn = apsw.Connection('curling_masters.db')
        conn.execute('PRAGMA key = "default_key_change_me";')
        
        print("检查 players 表结构:")
        cursor = conn.execute('PRAGMA table_info(players);')
        for row in cursor:
            print(f"  {row}")
        
        print("\n检查所有表:")
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor]
        for table in tables:
            print(f"\n{table} 表结构:")
            cursor = conn.execute(f'PRAGMA table_info({table});')
            for row in cursor:
                print(f"  {row}")
        
    except Exception as e:
        print(f"错误: {e}")

if __name__ == "__main__":
    check_database_schema()
