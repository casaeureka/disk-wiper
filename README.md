# disk-wiper

Standalone disk wiping utility for preparing storage devices in home server environments.

## Purpose

Completely wipes storage devices to prepare for use:
- Removes all partitions
- Clears filesystem signatures
- Removes LVM/RAID/ZFS metadata
- Verifies devices are clean

## Features

- Auto-detects non-USB disks (interactive mode)
- Shows detailed device information
- Double confirmation before wiping
- USB device protection (prevents accidental wipe of boot drive)
- Complete cleanup (partitions + filesystem signatures + metadata)
- Verification after wipe

## Usage

```bash
# Interactive: auto-detect and wipe all non-USB disks
sudo disk-wiper

# Wipe specific devices
sudo disk-wiper /dev/sda
sudo disk-wiper /dev/sda /dev/sdb
```

## Requirements

- Must run as root
- Python 3.10+
- System utilities: wipefs, sgdisk, lsblk, blkid, dd, blockdev, partprobe

## Installation

### Via Nix

```bash
nix profile install github:casaeureka/disk-wiper
disk-wiper --version
```

### Standalone

```bash
# Install dependencies first
bash install-dependencies.sh

# Run directly
sudo python3 disk_wiper.py
```

## Safety Features

- Refuses to wipe USB devices by default (likely your boot drive)
- Requires typing "WIPE ALL DATA" to confirm
- Requires additional "YES" confirmation
- Shows device details before wiping
- Override available for USB devices (requires explicit confirmation)

## License

GPLv3 - See [LICENSE](LICENSE)

## Support

[![GitHub Sponsors](https://img.shields.io/badge/GitHub-Sponsor-ea4aaa?logo=github)](https://github.com/sponsors/W3Max)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support-ff5f5f?logo=ko-fi)](https://ko-fi.com/w3max)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/w3max)
