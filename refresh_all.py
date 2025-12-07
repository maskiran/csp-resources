#!/usr/bin/env python3
"""
CSP Resources Refresh Script

This script discovers and saves VM and VPC/VNet data from all cloud providers.
"""

import time

# Import modules
import vm
import vpc


def format_duration(seconds: int) -> str:
    """Format duration in seconds to human readable format."""
    minutes = seconds // 60
    remaining_seconds = seconds % 60
    return f"{minutes}m {remaining_seconds}s"


def main() -> None:
    """Refresh VM and VPC resources from all cloud providers."""
    print("=== Starting Refresh of CSP Resources ===\n")

    start_time = time.time()

    # Refresh VM and VPC resources
    vm.refresh()
    vpc.refresh()

    # Calculate and display total time
    end_time = time.time()
    total_time = int(end_time - start_time)

    print("\n=== Refresh Complete ===")
    print(f"\nInventory files updated in the 'inventory/' directory:")
    print(f"  - {vm.INVENTORY_JSON_PATH.name} & {vm.INVENTORY_XLSX_PATH.name}")
    print(f"  - {vpc.INVENTORY_JSON_PATH.name} & {vpc.INVENTORY_XLSX_PATH.name}")
    print(f"\nTotal time: {format_duration(total_time)}\n")


if __name__ == "__main__":
    main()
