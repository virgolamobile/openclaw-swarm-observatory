#!/usr/bin/env python3
"""
Standalone bus reader for agent-dashboard.
Runs tail_bus from app.py as a standalone debug utility.
Note: the webapp now starts its own in-process reader; this script is optional.
"""
import os
import sys
from app import tail_bus, BUS_PATH

if __name__ == '__main__':
    print(f'[READER] Starting standalone reader (pid={os.getpid()}, ppid={os.getppid()})')
    try:
        tail_bus(BUS_PATH)
    except KeyboardInterrupt:
        print('[READER] Interrupted, exiting')
    except Exception as e:
        print(f'[READER] Exception: {e}', file=sys.stderr)
        raise
