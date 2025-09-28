#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库架构迁移脚本
添加缺失的列以匹配模型定义
"""

import apsw
import os

def migrate_database():
    """迁移数据库架构"""
    try:
        # 打开加密数据库
        conn = apsw.Connection('curling_masters.db')
        conn.execute('PRAGMA key = "default_key_change_me";')
        
        print("开始数据库迁移...")
        
        # 检查并添加 players.status 列
        cursor = conn.execute('PRAGMA table_info(players);')
        columns = [row[1] for row in cursor]
        
        if 'status' not in columns:
            print("添加 players.status 列...")
            conn.execute('ALTER TABLE players ADD COLUMN status INTEGER NOT NULL DEFAULT 1;')
            print("✅ players.status 列添加成功")
        else:
            print("✅ players.status 列已存在")
        
        # 检查并添加 tournament.t_format 列
        cursor = conn.execute('PRAGMA table_info(tournament);')
        columns = [row[1] for row in cursor]
        
        if 't_format' not in columns:
            print("添加 tournament.t_format 列...")
            conn.execute('ALTER TABLE tournament ADD COLUMN t_format INTEGER;')
            print("✅ tournament.t_format 列添加成功")
        else:
            print("✅ tournament.t_format 列已存在")
        
        # 检查并添加 tournament.player_count 列
        if 'player_count' not in columns:
            print("添加 tournament.player_count 列...")
            conn.execute('ALTER TABLE tournament ADD COLUMN player_count INTEGER;')
            print("✅ tournament.player_count 列添加成功")
        else:
            print("✅ tournament.player_count 列已存在")
        
        # 检查并添加 tournament.status 列
        if 'status' not in columns:
            print("添加 tournament.status 列...")
            conn.execute('ALTER TABLE tournament ADD COLUMN status INTEGER NOT NULL DEFAULT 1;')
            print("✅ tournament.status 列添加成功")
        else:
            print("✅ tournament.status 列已存在")
        
        # 检查并添加 matches.m_type 列
        cursor = conn.execute('PRAGMA table_info(matches);')
        columns = [row[1] for row in cursor]
        
        if 'm_type' not in columns:
            print("添加 matches.m_type 列...")
            conn.execute('ALTER TABLE matches ADD COLUMN m_type INTEGER;')
            print("✅ matches.m_type 列添加成功")
        else:
            print("✅ matches.m_type 列已存在")
        
        # 检查并添加 rankings.scores 列
        cursor = conn.execute('PRAGMA table_info(rankings);')
        columns = [row[1] for row in cursor]
        
        if 'scores' not in columns:
            print("添加 rankings.scores 列...")
            conn.execute('ALTER TABLE rankings ADD COLUMN scores INTEGER;')
            print("✅ rankings.scores 列添加成功")
        else:
            print("✅ rankings.scores 列已存在")
        
        print("\n✅ 数据库迁移完成!")
        
        # 验证迁移结果
        print("\n验证迁移结果:")
        cursor = conn.execute('PRAGMA table_info(players);')
        print("players 表结构:")
        for row in cursor:
            print(f"  {row}")
        
        cursor = conn.execute('PRAGMA table_info(tournament);')
        print("\ntournament 表结构:")
        for row in cursor:
            print(f"  {row}")
        
        cursor = conn.execute('PRAGMA table_info(matches);')
        print("\nmatches 表结构:")
        for row in cursor:
            print(f"  {row}")
        
        cursor = conn.execute('PRAGMA table_info(rankings);')
        print("\nrankings 表结构:")
        for row in cursor:
            print(f"  {row}")
        
        return True
        
    except Exception as e:
        print(f"❌ 数据库迁移失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    migrate_database()
