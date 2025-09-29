#!/usr/bin/env python3
"""
Frozen-Flask 构建脚本
将 Flask 应用转换为静态站点
参考：https://testdriven.io/blog/static-site-flask-and-netlify/
"""

from flask_frozen import Freezer
from app_frozen import app

freezer = Freezer(app)

if __name__ == '__main__':
    print("🔄 开始生成静态文件...")
    
    try:
        freezer.freeze()
        print("✅ 静态文件生成成功！")
        print("📁 输出目录: build/")
        
        # 显示生成的文件
        print("\n📋 生成的文件:")
        import os
        for root, dirs, files in os.walk('build'):
            level = root.replace('build', '').count(os.sep)
            indent = ' ' * 2 * level
            print(f"{indent}{os.path.basename(root)}/")
            subindent = ' ' * 2 * (level + 1)
            for file in files:
                print(f"{subindent}{file}")
                
    except Exception as e:
        print(f"❌ 生成失败: {e}")
        raise
