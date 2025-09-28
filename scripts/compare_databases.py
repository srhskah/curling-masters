#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
比较数据库架构
"""

import apsw

def compare_databases():
    """比较两个数据库的架构"""
    try:
        print("检查未加密数据库:")
        conn1 = apsw.Connection('curling_masters_unencrypted.db')
        cursor = conn1.execute('PRAGMA table_info(players);')
        print("players 表结构:")
        for row in cursor:
            print(f"  {row}")
        
        print("\n检查加密数据库:")
        conn2 = apsw.Connection('curling_masters.db')
        conn2.execute('PRAGMA key = "default_key_change_me";')
        cursor = conn2.execute('PRAGMA table_info(players);')
        print("players 表结构:")
        for row in cursor:
            print(f"  {row}")
        
    except Exception as e:
        print(f"错误: {e}")

if __name__ == "__main__":
    compare_databases()
