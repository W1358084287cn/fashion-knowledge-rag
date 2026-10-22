# -*- coding: utf-8 -*-
"""
后端启动入口
------------------------------------------------------------
在 backend 目录执行：python run.py
监听 0.0.0.0，手机与电脑在同一局域网时可通过 IP 直接访问。
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
