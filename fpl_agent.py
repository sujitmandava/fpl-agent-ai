#!/usr/bin/env python3
"""Convenience wrapper to run the FPL Agent CLI.

Usage:
    python fpl_agent.py refresh
    python fpl_agent.py recommend --manager-id 123456
    python fpl_agent.py apply --manager-id 123456 --email x --password y
"""

from fpl_agent.cli.main import cli

if __name__ == "__main__":
    cli()
