#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库切换工具
一行代码切换本地或远程数据库
"""

import os
import sys
from database_config import switch_to_local, switch_to_turso, get_current_database_type, print_database_info

def main():
    """主函数 - 支持命令行参数切换数据库"""
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == 'local':
            switch_to_local()
        elif command == 'turso':
            switch_to_turso()
        elif command == 'status':
            print_database_info()
        elif command == 'help':
            print_help()
        else:
            print(f"未知命令: {command}")
            print_help()
    else:
        # 交互式切换
        current_type = get_current_database_type()
        print(f"当前数据库类型: {current_type}")
        print("\n选择数据库类型:")
        print("1. 本地SQLCipher数据库")
        print("2. Turso远程数据库")
        print("3. 查看当前状态")
        print("4. 退出")
        
        choice = input("\n请输入选择 (1-4): ").strip()
        
        if choice == '1':
            switch_to_local()
        elif choice == '2':
            switch_to_turso()
        elif choice == '3':
            print_database_info()
        elif choice == '4':
            print("退出")
        else:
            print("无效选择")

def print_help():
    """打印帮助信息"""
    print("数据库切换工具")
    print("用法:")
    print("  python switch_database.py local    # 切换到本地数据库")
    print("  python switch_database.py turso    # 切换到Turso数据库")
    print("  python switch_database.py status   # 查看当前状态")
    print("  python switch_database.py help     # 显示帮助")
    print("  python switch_database.py          # 交互式切换")
    print("\n环境变量:")
    print("  DATABASE_TYPE: 'local' 或 'turso'")
    print("  DB_ENCRYPTION_KEY: 本地数据库加密密钥")
    print("  TURSO_URL: Turso数据库URL")
    print("  TURSO_AUTH_TOKEN: Turso认证令牌")

if __name__ == "__main__":
    main()
