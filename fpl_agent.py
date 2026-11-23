#!/usr/bin/env python3
"""Convenience wrapper to run the FPL Agent CLI.

Usage:
    python fpl_agent.py refresh
    python fpl_agent.py recommend --manager-id <your team ID>
    python fpl_agent.py api
"""

from fpl_agent.cli.main import cli

if __name__ == "__main__":
    cli()
