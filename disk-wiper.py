#!/usr/bin/env python3
"""
Disk Wipe Tool for Home Servers
Wipes storage devices to prepare for use

This script:
1. Auto-detects all non-USB disks (default: just press Enter)
2. Shows device information for each device
3. Requires double confirmation before wiping
4. Wipes devices completely (partitions, LVM, RAID, filesystem signatures)
5. Verifies devices are clean

DANGER: This script will PERMANENTLY DESTROY ALL DATA on specified devices
Use with extreme caution!

Usage:
  sudo python3 disk-wiper.py [devices...]

Arguments:
  devices  Space-separated device paths (e.g., /dev/sda /dev/sdb)
           If not provided, will auto-detect all non-USB disks

Examples:
  sudo python3 disk-wiper.py                         # Interactive: wipe all non-USB (press Enter)
  sudo python3 disk-wiper.py /dev/sda                # Wipe single device
  sudo python3 disk-wiper.py /dev/sda /dev/sdb       # Wipe multiple devices

Requirements:
  - Must run as root
  - Python 3.10+
"""

import argparse
import contextlib
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Version
VERSION = "1.0.0"


# Terminal colors
class Colors:
    """ANSI color codes for terminal output"""

    RED = "\033[0;31m"
    YELLOW = "\033[1;33m"
    GREEN = "\033[0;32m"
    CYAN = "\033[0;36m"
    BOLD = "\033[1m"
    NC = "\033[0m"  # No Color


# =============================================================================
# Utility Functions
# =============================================================================


def error(message: str) -> None:
    """Print error message and exit"""
    print(f"{Colors.RED}ERROR: {message}{Colors.NC}", file=sys.stderr)
    sys.exit(1)


def warn(message: str) -> None:
    """Print warning message"""
    print(f"{Colors.YELLOW}WARNING: {message}{Colors.NC}")


def success(message: str) -> None:
    """Print success message"""
    print(f"{Colors.GREEN}✓ {message}{Colors.NC}")


def info(message: str) -> None:
    """Print info message"""
    print(f"{Colors.CYAN}{message}{Colors.NC}")


def run_command(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run shell command and return result"""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=check, timeout=30)
        return result
    except subprocess.CalledProcessError as e:
        if check:
            raise
        return e


def check_root() -> None:
    """Check if running as root"""
    if os.geteuid() != 0:
        error("This script must be run as root")


def check_tools() -> None:
    """Check required tools are installed"""
    missing_tools = []

    for tool in ["wipefs", "sgdisk", "lsblk", "blkid", "dd", "blockdev", "partprobe", "sfdisk", "parted"]:
        if not which(tool):
            missing_tools.append(tool)

    if missing_tools:
        error(f"Missing required tools: {', '.join(missing_tools)}. Run setup script first.")


def which(program: str) -> bool:
    """Check if program exists in PATH"""
    result = subprocess.run(["which", program], capture_output=True, timeout=5)
    return result.returncode == 0


# =============================================================================
# Device Discovery
# =============================================================================


def is_usb_device(device_path: str) -> bool:
    """Check if device is a USB device"""
    # Check transport type via lsblk
    try:
        result = run_command(["lsblk", "-d", "-n", "-o", "TRAN", device_path], check=False)
        if result.returncode == 0:
            transport = result.stdout.strip().lower()
            if transport == "usb":
                return True
    except (subprocess.SubprocessError, OSError):
        pass

    # Also check by-id symlinks for "usb" in path
    try:
        by_id_dir = Path("/dev/disk/by-id")
        if by_id_dir.exists():
            for link in by_id_dir.iterdir():
                try:
                    if link.resolve() == Path(device_path).resolve() and "usb" in str(link).lower():
                        return True
                except (OSError, RuntimeError):
                    continue
    except (OSError, RuntimeError):
        pass

    return False


def get_all_block_devices() -> list[str]:
    """Get all block devices (disks only, not partitions)"""
    try:
        result = run_command(["lsblk", "-d", "-n", "-o", "NAME,TYPE"], check=False)
        if result.returncode != 0:
            return []

        devices = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 2:
                name, dev_type = parts[0], parts[1]
                if dev_type == "disk":
                    devices.append(f"/dev/{name}")

        return devices
    except (subprocess.SubprocessError, OSError):
        return []


def get_non_usb_devices() -> list[str]:
    """Get all non-USB block devices"""
    all_devices = get_all_block_devices()
    non_usb = [dev for dev in all_devices if not is_usb_device(dev)]
    return non_usb


def show_all_devices() -> None:
    """Display all available block devices with details"""
    print()
    print("╔═══════════════════════════════════════════════════════════╗")
    print("║                  Available Block Devices                  ║")
    print("╚═══════════════════════════════════════════════════════════╗")
    print()

    try:
        result = run_command(["lsblk", "-d", "-o", "NAME,SIZE,TYPE,TRAN,MODEL"], check=False)
        if result.returncode == 0:
            print(result.stdout)
    except (subprocess.SubprocessError, OSError):
        warn("Could not list block devices")

    print()


# =============================================================================
# Device Information
# =============================================================================


def get_device_info(device_path: str) -> dict[str, Any]:
    """Get information about a device"""
    # Resolve symlink to actual device
    try:
        real_device = Path(device_path).resolve()
    except (OSError, RuntimeError) as e:
        warn(f"Could not resolve device path {device_path}: {e}")
        real_device = device_path

    info = {
        "path": device_path,
        "real_path": str(real_device),
        "exists": Path(real_device).exists() if isinstance(real_device, Path) else False,
    }

    # Get device info from lsblk
    if info["exists"]:
        try:
            result = run_command(["lsblk", "-o", "NAME,SIZE,MODEL,SERIAL", str(real_device)], check=False)
            if result.returncode == 0:
                info["lsblk"] = result.stdout.strip()
        except (subprocess.SubprocessError, OSError) as e:
            warn(f"Could not query device info for {real_device}: {e}")

    return info


def show_devices_to_wipe(devices: list[str]) -> None:
    """Display all devices that will be wiped"""
    print()
    print("╔═══════════════════════════════════════════════════════════╗")
    print("║              Devices to be Wiped                          ║")
    print("╚═══════════════════════════════════════════════════════════╝")
    print()

    for device in devices:
        device_info = get_device_info(device)

        print(f"  Device: {device}")
        if device != device_info["real_path"]:
            print(f"  → Resolves to: {device_info['real_path']}")

        if device_info["exists"]:
            if "lsblk" in device_info:
                for line in device_info["lsblk"].split("\n"):
                    print(f"    {line}")
        else:
            warn(f"    Device not found: {device_info['real_path']}")
        print()


# =============================================================================
# Confirmation
# =============================================================================


def confirm_wipe(devices: list[str]) -> bool:
    """Get confirmation from user before wiping"""
    print()
    print(f"{Colors.RED}{Colors.BOLD}╔═══════════════════════════════════════════════════════════╗{Colors.NC}")
    print(f"{Colors.RED}{Colors.BOLD}║  YOU ARE ABOUT TO PERMANENTLY DESTROY ALL DATA           ║{Colors.NC}")
    print(f"{Colors.RED}{Colors.BOLD}╚═══════════════════════════════════════════════════════════╝{Colors.NC}")
    print()
    print("The following devices will be COMPLETELY WIPED:")
    print()

    for device in devices:
        device_info = get_device_info(device)
        print(f"  {Colors.RED}✗ {device}{Colors.NC}")
        if device != device_info["real_path"]:
            print(f"    {Colors.RED}→ {device_info['real_path']}{Colors.NC}")

    print()
    warn("This operation is IRREVERSIBLE!")
    warn("All partitions, filesystems, LVM, RAID metadata will be destroyed!")
    print()

    confirmation = input("Type 'WIPE ALL DATA' to confirm: ")

    if confirmation != "WIPE ALL DATA":
        print("Aborted. No changes made.")
        return False

    print()
    final_confirm = input("Are you absolutely sure? Type 'YES' to proceed: ")

    if final_confirm != "YES":
        print("Aborted. No changes made.")
        return False

    return True


# =============================================================================
# Disk Wiping
# =============================================================================

MAX_WIPE_ATTEMPTS = 3


def sync_kernel_partitions(drive: str, wait_seconds: int = 2) -> None:
    """Force kernel to re-read partition table and wait"""
    run_command(["blockdev", "--rereadpt", drive], check=False)
    run_command(["partprobe", drive], check=False)
    # Also trigger udev to settle
    run_command(["udevadm", "settle", "--timeout=5"], check=False)
    time.sleep(wait_seconds)


def get_partition_list(drive: str) -> list[str]:
    """Get list of partition devices for a drive"""
    result = run_command(["lsblk", "-ln", "-o", "NAME", drive], check=False)
    if result.returncode != 0:
        return []

    lines = result.stdout.strip().split("\n")
    if len(lines) <= 1:
        return []

    partitions = []
    for part_name in lines[1:]:
        part_device = f"/dev/{part_name.strip()}"
        if part_device != drive:
            partitions.append(part_device)
    return partitions


def stop_raid_arrays(drive: str) -> None:
    """Stop any RAID arrays using this drive"""
    if not which("mdadm"):
        return

    print("  Stopping RAID arrays...")
    # Find RAID arrays that use this drive or its partitions
    result = run_command(["cat", "/proc/mdstat"], check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return

    # Get all md devices
    for line in result.stdout.split("\n"):
        if line.startswith("md"):
            md_name = line.split()[0]
            md_device = f"/dev/{md_name}"
            # Stop this array (will fail if drive not part of it, that's ok)
            run_command(["mdadm", "--stop", md_device], check=False)


def remove_raid_metadata(drive: str, partitions: list[str]) -> None:
    """Remove RAID superblock metadata from drive and partitions"""
    if not which("mdadm"):
        return

    print("  Removing RAID metadata...")
    # Remove from partitions first
    for part in partitions:
        run_command(["mdadm", "--zero-superblock", "--force", part], check=False)
    # Remove from whole drive
    run_command(["mdadm", "--zero-superblock", "--force", drive], check=False)


def delete_partitions_explicitly(drive: str) -> None:
    """Explicitly delete all partitions using multiple methods"""
    print("  Deleting partitions explicitly...")

    # Method 1: Use sfdisk to delete all partitions
    # sfdisk --delete removes all partitions when no partition number specified
    run_command(["sfdisk", "--delete", drive], check=False)

    sync_kernel_partitions(drive, 1)

    # Method 2: If partitions still exist, use parted to create empty label
    partitions = get_partition_list(drive)
    if partitions:
        print("    Using parted to create empty GPT...")
        # This overwrites partition table completely
        run_command(["parted", "-s", drive, "mklabel", "gpt"], check=False)
        sync_kernel_partitions(drive, 1)


def wipe_drive_once(drive: str, attempt: int) -> bool:
    """Single wipe attempt. Returns True if drive appears clean."""
    if attempt > 1:
        print(f"  Wipe attempt {attempt}/{MAX_WIPE_ATTEMPTS}...")

    # Step 1: Stop any RAID arrays using this drive
    stop_raid_arrays(drive)

    # Step 2: Unmount all partitions first
    partitions = get_partition_list(drive)
    for part in partitions:
        run_command(["umount", "-f", part], check=False)

    # Step 3: Deactivate LVM volume groups that might use this drive
    print("  Deactivating LVM...")
    # Scan for VGs using this PV
    result = run_command(["pvs", "--noheadings", "-o", "vg_name", drive], check=False)
    if result.returncode == 0 and result.stdout.strip():
        for vg in result.stdout.strip().split("\n"):
            vg = vg.strip()
            if vg:
                run_command(["vgchange", "-an", vg], check=False)
    for part in partitions:
        result = run_command(["pvs", "--noheadings", "-o", "vg_name", part], check=False)
        if result.returncode == 0 and result.stdout.strip():
            for vg in result.stdout.strip().split("\n"):
                vg = vg.strip()
                if vg:
                    run_command(["vgchange", "-an", vg], check=False)

    # Step 4: Remove RAID metadata
    remove_raid_metadata(drive, partitions)

    # Step 5: Remove LVM metadata
    print("  Removing LVM metadata...")
    for part in partitions:
        run_command(["pvremove", "-ff", "-y", part], check=False)
    run_command(["pvremove", "-ff", "-y", drive], check=False)

    # Step 6: Remove ZFS labels
    if which("zpool"):
        print("  Removing ZFS labels...")
        run_command(["zpool", "labelclear", "-f", drive], check=False)
        for part in partitions:
            run_command(["zpool", "labelclear", "-f", part], check=False)

    # Step 7: Wipe filesystem signatures
    print("  Wiping filesystem signatures...")
    for part in partitions:
        run_command(["wipefs", "--all", "--force", part], check=False)
    run_command(["wipefs", "--all", "--force", drive], check=False)

    # Step 8: Delete partitions explicitly
    delete_partitions_explicitly(drive)

    # Step 9: Destroy GPT/MBR partition tables
    print("  Destroying partition tables...")
    run_command(["sgdisk", "--zap-all", drive], check=False)

    # Step 10: Zero partition table areas (beginning and end of disk)
    print("  Zeroing partition table areas...")
    with contextlib.suppress(subprocess.SubprocessError, subprocess.TimeoutExpired, OSError):
        # Zero first 2MB (covers MBR, GPT header, and partition entries)
        subprocess.run(
            ["dd", "if=/dev/zero", f"of={drive}", "bs=1M", "count=2"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=60,
        )

    # Zero end of disk (backup GPT)
    result = run_command(["blockdev", "--getsz", drive], check=False)
    if result.returncode == 0:
        try:
            disk_sectors = int(result.stdout.strip())
            # Zero last 2MB (4096 sectors at 512 bytes each)
            seek_pos = max(0, disk_sectors - 4096)
            subprocess.run(
                ["dd", "if=/dev/zero", f"of={drive}", "bs=512", f"seek={seek_pos}", "count=4096"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=60,
            )
        except (subprocess.SubprocessError, subprocess.TimeoutExpired, OSError, ValueError):
            pass

    # Step 11: Final sync with longer wait
    print("  Syncing kernel partition table...")
    sync_kernel_partitions(drive, 3)

    # Verify no partitions remain
    remaining = get_partition_list(drive)
    return len(remaining) == 0


def wipe_drive(device: str) -> bool:
    """Wipe a single drive with retry logic

    Returns True if successful, False otherwise
    """
    device_info = get_device_info(device)
    drive = device_info["real_path"]

    print()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"Wiping: {device}")
    if device != drive:
        print(f"  → {drive}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    if not device_info["exists"]:
        warn(f"Device not found, skipping: {drive}")
        return True

    # Retry loop - keep trying until clean or max attempts
    for attempt in range(1, MAX_WIPE_ATTEMPTS + 1):
        is_clean = wipe_drive_once(drive, attempt)
        if is_clean:
            success(f"Drive wiped: {device}")
            return True
        if attempt < MAX_WIPE_ATTEMPTS:
            warn(f"Partitions still present, retrying ({attempt}/{MAX_WIPE_ATTEMPTS})...")
            time.sleep(2)

    # Final check after all attempts
    remaining = get_partition_list(drive)
    if remaining:
        warn(f"Drive {device} still has partitions after {MAX_WIPE_ATTEMPTS} attempts: {remaining}")
        return False

    success(f"Drive wiped: {device}")
    return True


# =============================================================================
# Verification
# =============================================================================


def verify_clean(devices: list[str]) -> bool:
    """Verify drives are clean

    Returns True if all clean, False otherwise
    """
    print()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("Verification")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()

    # Force partition table refresh before verification
    print("Refreshing partition tables before verification...")
    for device in devices:
        device_info = get_device_info(device)
        drive = device_info["real_path"]
        if device_info["exists"]:
            sync_kernel_partitions(drive, 1)
    # Extra wait after all syncs
    time.sleep(2)
    print()

    all_clean = True

    for device in devices:
        device_info = get_device_info(device)
        drive = device_info["real_path"]

        print(f"Checking: {device}")

        if not device_info["exists"]:
            warn("  Device not found, skipping verification")
            continue

        # Check for partitions
        partitions = get_partition_list(drive)
        if partitions:
            warn(f"  Still has partitions: {partitions}")
            all_clean = False
        else:
            success("  No partitions")

        # Check for filesystem signatures
        result = run_command(["blkid", drive], check=False)
        if result.returncode == 0 and result.stdout.strip():
            warn("  Still has filesystem signatures!")
            print(f"    {result.stdout.strip()}")
            all_clean = False
        else:
            success("  No filesystem signatures")

        # Check for LVM
        if which("pvs"):
            result = run_command(["pvs", "--noheadings", drive], check=False)
            if result.returncode == 0 and result.stdout.strip():
                warn("  Still has LVM metadata!")
                all_clean = False
            else:
                success("  No LVM metadata")

        # Check for RAID metadata
        if which("mdadm"):
            result = run_command(["mdadm", "--examine", drive], check=False)
            if result.returncode == 0 and "Array UUID" in result.stdout:
                warn("  Still has RAID metadata!")
                all_clean = False
            else:
                success("  No RAID metadata")

        print()

    if all_clean:
        success("All drives verified clean!")
        return True
    warn("Some drives may not be completely clean. Review warnings above.")
    return False


# =============================================================================
# Device Input
# =============================================================================


def get_devices_interactive() -> list[str]:
    """Get device list from user interactively with smart defaults"""
    # Show all devices
    show_all_devices()

    # Get non-USB devices as default
    default_devices = get_non_usb_devices()

    if not default_devices:
        error("No non-USB block devices found!")

    # Show USB devices that will be excluded
    all_devices = get_all_block_devices()
    usb_devices = [dev for dev in all_devices if is_usb_device(dev)]

    if usb_devices:
        info("USB devices detected (will be excluded by default):")
        for dev in usb_devices:
            print(f"  🔒 {dev} (protected)")
        print()

    # Show default selection
    info("Non-USB devices that will be wiped:")
    for dev in default_devices:
        device_info = get_device_info(dev)
        print(f"  ✗ {dev}")
        if "lsblk" in device_info:
            for line in device_info["lsblk"].split("\n")[1:]:  # Skip header
                print(f"    {line}")
    print()

    # Prepare default value string
    default_str = " ".join(default_devices)

    info("Press Enter to wipe all non-USB devices shown above")
    info("OR specify custom devices (space-separated):")
    info("Examples:")
    print("  - /dev/sda /dev/sdb")
    print("  - /dev/nvme0n1")
    print()

    devices_input = input(f"Devices [{default_str}]: ").strip()

    # Use default if empty
    if not devices_input:
        info("Using default: all non-USB devices")
        return default_devices

    # Parse custom input
    devices = devices_input.split()

    # Validate device paths
    valid_devices = []
    for device in devices:
        if not device.startswith("/dev/"):
            warn(f"Invalid device path (must start with /dev/): {device}")
            continue

        # Check if it's a USB device
        if is_usb_device(device):
            warn(f"Refusing to wipe USB device: {device} (likely your boot drive!)")
            confirm = input("  Override and wipe this USB device anyway? Type 'YES' to confirm: ")
            if confirm == "YES":
                valid_devices.append(device)
            else:
                info(f"  Skipping {device}")
            continue

        valid_devices.append(device)

    if not valid_devices:
        error("No valid devices specified")

    return valid_devices


# =============================================================================
# Main Function
# =============================================================================


def main() -> int:
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Disk Wipe Tool - Completely wipes storage devices",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  sudo python3 disk-wiper.py /dev/sda
  sudo python3 disk-wiper.py /dev/sda /dev/sdb
  sudo python3 disk-wiper.py

⚠️  WARNING: This will PERMANENTLY DESTROY ALL DATA on specified devices
        """,
    )
    parser.add_argument("devices", nargs="*", help="Device paths to wipe (e.g., /dev/sda /dev/sdb)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")

    args = parser.parse_args()

    check_root()
    check_tools()

    print()
    print("╔═══════════════════════════════════════════════════════════╗")
    print("║                                                           ║")
    print("║              Home Server Disk Wipe Tool                   ║")
    print("║                                                           ║")
    print("╚═══════════════════════════════════════════════════════════╝")
    print()

    # Get devices from arguments or interactively
    if args.devices:
        devices = []
        for device in args.devices:
            # Validate device path
            if not device.startswith("/dev/"):
                error(f"Invalid device path (must start with /dev/): {device}")

            # Check if device exists
            if not Path(device).exists():
                error(f"Device does not exist: {device}")

            # Check if it's a USB device
            if is_usb_device(device):
                warn(f"Refusing to wipe USB device: {device} (likely your boot drive!)")
                print()
                confirm = input("  Override and wipe this USB device anyway? Type 'YES' to confirm: ")
                if confirm == "YES":
                    devices.append(device)
                else:
                    info(f"  Skipping {device}")
                continue

            devices.append(device)

        if not devices:
            error("No valid devices specified")
    else:
        devices = get_devices_interactive()

    # Show devices to wipe
    show_devices_to_wipe(devices)

    # Get confirmation
    if not confirm_wipe(devices):
        return 0

    # Wipe each drive
    print()
    print("Starting wipe operation...")
    for device in devices:
        wipe_drive(device)

    # Verify clean
    verify_clean(devices)

    print()
    success("╔═══════════════════════════════════════════════════════════╗")
    success("║                                                           ║")
    success("║         Disk wipe completed successfully!                ║")
    success("║                                                           ║")
    success("╚═══════════════════════════════════════════════════════════╝")
    print()
    print("All specified devices have been wiped clean.")
    print()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Cancelled by user{Colors.NC}")
        sys.exit(1)
    except Exception as e:
        print(f"{Colors.RED}Error: {e}{Colors.NC}", file=sys.stderr)
        sys.exit(1)
