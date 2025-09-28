#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成Flask SECRET_KEY工具
"""

import secrets
import os

def generate_secret_key():
    """生成安全的SECRET_KEY"""
    return secrets.token_hex(32)

def main():
    """主函数"""
    print("Flask SECRET_KEY 生成器")
    print("=" * 40)
    
    # 生成新的SECRET_KEY
    secret_key = generate_secret_key()
    
    print(f"生成的SECRET_KEY: {secret_key}")
    print()
    print("使用方法:")
    print("1. 在.env文件中设置:")
    print(f"   SECRET_KEY={secret_key}")
    print()
    print("2. 在Netlify环境变量中设置:")
    print(f"   SECRET_KEY = {secret_key}")
    print()
    print("3. 在命令行中设置:")
    print(f"   export SECRET_KEY={secret_key}")
    print()
    print("⚠️  重要提醒:")
    print("- 请妥善保管此密钥，不要泄露给他人")
    print("- 生产环境和开发环境应使用不同的密钥")
    print("- 如果密钥泄露，请立即更换")

if __name__ == "__main__":
    main()
