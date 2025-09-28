#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 SQL 文件恢复数据到加密数据库（处理列数不匹配问题）
"""

import apsw
import os
import re

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
                    # 处理列数不匹配的问题
                    modified_statement = fix_insert_statement(statement)
                    conn.execute(modified_statement)
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

def fix_insert_statement(statement):
    """修复 INSERT 语句以匹配当前数据库架构"""
    # 解析 INSERT 语句
    match = re.match(r'INSERT INTO "(\w+)" VALUES \((.*)\)', statement)
    if not match:
        return statement
    
    table_name = match.group(1)
    values_str = match.group(2)
    
    # 解析值
    values = parse_values(values_str)
    
    # 根据表名调整值
    if table_name == 'players':
        # players 表有 3 列：player_id, name, status
        # SQL 文件只有 2 个值，需要添加 status 默认值
        if len(values) == 2:
            values.append('1')  # 默认 status = 1
    elif table_name == 'rankings':
        # rankings 表有 5 列：r_id, t_id, player_id, ranks, scores
        # SQL 文件只有 4 个值，需要添加 scores 默认值
        if len(values) == 4:
            values.append('NULL')  # scores 可以为 NULL
    elif table_name == 'tournament':
        # tournament 表有 6 列：t_id, season_id, type, t_format, player_count, status
        # SQL 文件只有 5 个值，需要添加 status 默认值
        if len(values) == 5:
            values.append('1')  # 默认 status = 1
    
    # 重新构建语句
    values_str = ','.join(values)
    return f'INSERT INTO "{table_name}" VALUES ({values_str})'

def parse_values(values_str):
    """解析 VALUES 中的值"""
    values = []
    current_value = ""
    in_quotes = False
    quote_char = None
    
    i = 0
    while i < len(values_str):
        char = values_str[i]
        
        if not in_quotes:
            if char in ["'", '"']:
                in_quotes = True
                quote_char = char
                current_value += char
            elif char == ',':
                values.append(current_value.strip())
                current_value = ""
            else:
                current_value += char
        else:
            current_value += char
            if char == quote_char:
                # 检查是否是转义的引号
                if i + 1 < len(values_str) and values_str[i + 1] == quote_char:
                    current_value += values_str[i + 1]
                    i += 1
                else:
                    in_quotes = False
                    quote_char = None
        
        i += 1
    
    if current_value.strip():
        values.append(current_value.strip())
    
    return values

if __name__ == "__main__":
    restore_data_from_sql()
