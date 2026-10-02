import argparse
import json
import os
import socket
from pathlib import Path

import uvicorn

from . import __version__
from .app import create_app
from .config import Settings, default_data_dir
from .diagnostics import setup_logging


def main():
    parser = argparse.ArgumentParser(description="Edge TTS Desktop local backend")
    parser.add_argument("--port", type=int, default=0, help="0 selects an available loopback port")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--concurrency", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--proxy", default=os.environ.get("EDGE_TTS_PROXY"))
    parser.add_argument(
        "--azure-base-url",
        default=os.environ.get("EDGE_TTS_AZURE_BASE_URL"),
        help="Override the Azure Speech endpoint (gateway or testing); default is official",
    )
    parser.add_argument(
        "--origin", action="append", help="Allowed frontend origin; repeat as needed"
    )
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    options = {
        "data_dir": args.data_dir.resolve(),
        "concurrency": args.concurrency,
        "proxy": args.proxy,
        "azure_base_url": args.azure_base_url,
    }
    token = os.environ.get("EDGE_TTS_TOKEN")
    if token:
        options["token"] = token
    if args.origin:
        options["origins"] = tuple(args.origin)
    settings = Settings(**options)
    setup_logging(settings.data_dir)
    app = create_app(settings)

    # Send readiness after startup finishes, through the parent's private stdout pipe.
    # The parent must retain this message privately: it contains the session credential.
    class ReadyServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets)
            if self.started:
                print(
                    json.dumps(
                        {
                            "event": "ready",
                            "host": "127.0.0.1",
                            "port": listener.getsockname()[1],
                            "token": settings.token,
                            "version": __version__,
                        }
                    ),
                    flush=True,
                )

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", args.port))
        server = ReadyServer(
            uvicorn.Config(
                app,
                log_level="info",
                log_config=None,  # 交给根日志配置，uvicorn 的日志也会写入文件
                access_log=False,
                timeout_graceful_shutdown=5,
            )
        )
        app.state.request_shutdown = lambda: setattr(server, "should_exit", True)
        server.run(sockets=[listener])


if __name__ == "__main__":
    main()
