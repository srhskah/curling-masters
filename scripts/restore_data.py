#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 SQL 文件恢复数据到加密数据库
"""

import apsw
import os

def restore_data_from_sql():
    """从 SQL 文件恢复数据"""
    try:
        print("正在从 SQL 文件恢复数据...")
        
        # 打开加密数据库
        conn = apsw.Connection('curling_masters.db')
        conn.execute('PRAGMA key = "default_key_change_me";')
        
        # 读取 SQL 文件
        sql_file = 'curling_masters.db.test1.sql'
        if not os.path.exists(sql_file):
            print(f"❌ SQL 文件不存在: {sql_file}")
            return False
        
        with open(sql_file, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        # 分割 SQL 语句
        statements = sql_content.split(';')
        
        print(f"找到 {len(statements)} 条 SQL 语句")
        
        # 执行 INSERT 语句
        insert_count = 0
        for statement in statements:
            statement = statement.strip()
            if statement.upper().startswith('INSERT INTO'):
                try:
                    conn.execute(statement)
                    insert_count += 1
                    print(f"✅ 执行: {statement[:50]}...")
                except Exception as e:
                    print(f"❌ 执行失败: {statement[:50]}... - {e}")
        
        print(f"\n✅ 数据恢复完成! 成功执行了 {insert_count} 条 INSERT 语句")
        
        # 验证数据
        print("\n验证恢复的数据:")
        tables = ['players', 'seasons', 'tournament', 'matches', 'rankings', 'managers']
        
        for table in tables:
            try:
                cursor = conn.execute(f'SELECT COUNT(*) FROM {table};')
                count = cursor.fetchone()[0]
                print(f"{table}: {count} 条记录")
            except Exception as e:
                print(f"{table}: 查询失败 - {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ 数据恢复失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    restore_data_from_sql()
