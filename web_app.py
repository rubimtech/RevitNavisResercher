#!/usr/bin/env python3
"""
RevitNavisResearcher Web App — entry point.
Module structure in web_app/ package.
"""
import argparse
import uvicorn
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

from web_app import app  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="RevitNavis Researcher Web App")
    parser.add_argument("--host", default="0.0.0.0", help="Хост (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Порт (default: 8080)")
    parser.add_argument("--reload", action="store_true", help="Автоперезагрузка при изменении кода")
    args = parser.parse_args()
    uvicorn.run("web_app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
