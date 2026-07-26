#!/usr/bin/env python3
"""
Alias runner for front_door_ai.py to support multi-camera AI Person Detection.
Monitors Front Door (192.168.1.38) and Office (192.168.1.31) cameras.
"""
from front_door_ai import main

if __name__ == "__main__":
    main()
