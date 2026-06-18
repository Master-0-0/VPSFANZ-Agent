from setuptools import setup

setup(
    name="ipvps",
    version="1.0.0",
    description="IP/VPS 溯源工具集 — 基础信息收集 + 云厂商识别",
    py_modules=["cli", "orchestrator", "hunter_tool", "threatbook_tool", "whois_tool"],
    entry_points={"console_scripts": ["ipvps=cli:app"]},
    install_requires=["typer>=0.9", "requests", "python-dotenv", "playwright"],
    python_requires=">=3.8",
)
