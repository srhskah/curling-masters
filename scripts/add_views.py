#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
添加缺失的数据库视图
"""

import apsw
import os

def add_missing_views():
    """添加缺失的数据库视图"""
    try:
        print("正在添加缺失的数据库视图...")
        
        # 打开加密数据库
        conn = apsw.Connection('curling_masters.db')
        conn.execute('PRAGMA key = "default_key_change_me";')
        
        # 读取并执行视图定义
        view_files = ['t_s_view.sql', 'w_t_l_view.sql']
        
        for view_file in view_files:
            if os.path.exists(view_file):
                print(f"正在处理 {view_file}...")
                with open(view_file, 'r', encoding='utf-8') as f:
                    sql_content = f.read()
                
                # 分割并执行 SQL 语句
                statements = sql_content.split(';')
                for statement in statements:
                    statement = statement.strip()
                    if statement:
                        try:
                            conn.execute(statement)
                            print(f"✅ 执行: {statement[:50]}...")
                        except Exception as e:
                            print(f"❌ 执行失败: {statement[:50]}... - {e}")
            else:
                print(f"⚠️ 文件不存在: {view_file}")
        
        # 验证视图是否创建成功
        print("\n验证视图创建结果:")
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='view';")
        views = [row[0] for row in cursor]
        
        print(f"数据库中的视图: {views}")
        
        # 测试 tournament_session_view
        if 'tournament_session_view' in views:
            print("\n测试 tournament_session_view:")
            cursor = conn.execute("SELECT * FROM tournament_session_view LIMIT 3;")
            for row in cursor:
                print(f"  {row}")
        
        return True
        
    except Exception as e:
        print(f"❌ 添加视图失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    add_missing_views()
