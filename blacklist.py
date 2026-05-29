#!/usr/bin/env python3
"""
Blacklist Manager
=================
Quickly add or remove symbols from the corporate events blacklist.

Usage:
    python blacklist.py add CFLT "Acquired by IBM - delisted"
    python blacklist.py remove CFLT
    python blacklist.py list
"""

import sys
import json
from pathlib import Path

BLACKLIST_FILE = "config/blacklist.json"

def load():
    if Path(BLACKLIST_FILE).exists():
        return json.loads(Path(BLACKLIST_FILE).read_text())
    return {}

def save(bl):
    Path(BLACKLIST_FILE).parent.mkdir(exist_ok=True)
    Path(BLACKLIST_FILE).write_text(json.dumps(bl, indent=2))

def main():
    bl = load()
    args = sys.argv[1:]

    if not args or args[0] == "list":
        if not bl:
            print("Blacklist is empty.")
        else:
            print(f"\n{'='*50}")
            print(f"  BLACKLISTED SYMBOLS ({len(bl)})")
            print(f"{'='*50}")
            for sym, reason in bl.items():
                print(f"  {sym:<10} {reason}")
            print(f"{'='*50}\n")
        return

    if args[0] == "add" and len(args) >= 3:
        sym = args[1].upper()
        reason = " ".join(args[2:])
        bl[sym] = reason
        save(bl)
        print(f"Added {sym} to blacklist: {reason}")
        return

    if args[0] == "remove" and len(args) >= 2:
        sym = args[1].upper()
        if sym in bl:
            del bl[sym]
            save(bl)
            print(f"Removed {sym} from blacklist.")
        else:
            print(f"{sym} not in blacklist.")
        return

    print("Usage:")
    print("  python blacklist.py list")
    print("  python blacklist.py add SYMBOL \"reason\"")
    print("  python blacklist.py remove SYMBOL")

if __name__ == "__main__":
    main()
