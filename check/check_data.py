#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查数据库中的数据
"""

import apsw

def check_data():
    """检查数据库中的数据"""
    try:
        print("检查加密数据库中的数据...")
        conn = apsw.Connection('curling_masters.db')
        conn.execute('PRAGMA key = "default_key_change_me";')
        
        # 检查各表的数据量
        tables = ['players', 'seasons', 'tournament', 'matches', 'rankings', 'managers']
        
        for table in tables:
            try:
                cursor = conn.execute(f'SELECT COUNT(*) FROM {table};')
                count = cursor.fetchone()[0]
                print(f"{table}: {count} 条记录")
                
                # 如果有数据，显示前几条
                if count > 0:
                    cursor = conn.execute(f'SELECT * FROM {table} LIMIT 3;')
                    print(f"  前3条记录:")
                    for row in cursor:
                        print(f"    {row}")
            except Exception as e:
                print(f"{table}: 查询失败 - {e}")
        
        print("\n检查备份数据库中的数据...")
        conn2 = apsw.Connection('curling_masters.db.bak')
        
        for table in tables:
            try:
                cursor = conn2.execute(f'SELECT COUNT(*) FROM {table};')
                count = cursor.fetchone()[0]
                print(f"{table}: {count} 条记录")
                
                # 如果有数据，显示前几条
                if count > 0:
                    cursor = conn2.execute(f'SELECT * FROM {table} LIMIT 3;')
                    print(f"  前3条记录:")
                    for row in cursor:
                        print(f"    {row}")
            except Exception as e:
                print(f"{table}: 查询失败 - {e}")
        
    except Exception as e:
        print(f"检查失败: {e}")

if __name__ == "__main__":
    check_data()
