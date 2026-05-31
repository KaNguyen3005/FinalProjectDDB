from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the RTO Benchmark FastAPI app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    print(f"API:       http://{args.host}:{args.port}/api/health")
    print(f"Demo:      http://{args.host}:{args.port}/demo")
    print(f"Benchmark: http://{args.host}:{args.port}/benchmark")
    print(f"Logs:      http://{args.host}:{args.port}/logs")
    uvicorn.run("api.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
