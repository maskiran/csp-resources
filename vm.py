#!/usr/bin/env python3
"""
VM Management Script - Query, filter, and manage VMs from inventory.

This script provides management capabilities for VMs:
- List all VMs from inventory
- View detailed VM information (including console URLs)
- Add tags to VMs
- Set protection to prevent deletion and stopping (AWS & GCP)
- Delete VMs with safety confirmations

The script uses 1-based indexing for user display.

Usage examples:
  # Refresh VM inventory
  python vm.py --refresh
  
  # List all VMs from inventory
  python vm.py

  # Show specific VMs by index or name
  python vm.py -i 5,10,15

  # Load VM identifiers from a file
  python vm.py -i @/tmp/vm_ids.txt

  # Delete VMs by index
  python vm.py -i 5,10 -d

  # Add custom tag to VMs
  python vm.py -i 5,10,15 -t Environment -v Production

  # Protect VMs (prevent deletion and stopping)
  python vm.py -i 5,10,15 --protected true

  # Unprotect VMs (allow deletion and stopping)
  python vm.py -i 5,10 --protected false
"""

import argparse
import logging
import sys

from tabulate import tabulate

from csp import vm as csp_vm
from utils import find_items_by_identifier, load_from_json, process_identifiers_input, save_to_json, truncate_account_name, save_to_excel, setup_logging, log_discovery_stats, get_inventory_path

logger = logging.getLogger(__name__)


def prepare_vm_table_data(vms: list[dict]) -> list[list]:
    """Prepare VM data for Excel export."""
    data = []
    for vm in vms:
        # Extract EKS Cluster name from kubernetes tags
        tags = vm.get('tags', {})
        eks_cluster = ''
        for key in tags:
            if key.startswith('kubernetes.io/cluster/'):
                eks_cluster = key.replace('kubernetes.io/cluster/', '')
                break

        row = [
            vm.get('name', ''),
            vm.get('id', '') if vm.get(
                'cloud') == 'aws' else '',  # ID only for AWS
            vm.get('cloud', '').upper(),
            vm.get('account_name', vm.get('account_id', '')),
            vm.get('region', ''),
            vm.get('zone', ''),
            vm.get('vpc_id', ''),
            vm.get('subnet_id', ''),
            vm.get('launch_time', ''),
            eks_cluster
        ]
        data.append(row)

    return data


def save_vms_to_excel(vms: list[dict], filename: str):
    """Save VM data to Excel file with filtering and sorting."""
    data = prepare_vm_table_data(vms)
    headers = ["Name", "ID", "Cloud", "Account", "Region", "Zone", "VPC", "Subnet",
               "Created", "EKS Cluster"]
    save_to_excel(filename, "VMs", headers, data)


def print_vms(vms: list[dict[str, any]]) -> None:
    """
    Print VMs with their absolute index in a table format.

    Args:
        vms (list[dict[str, any]]): List of VMs
    """
    if not vms:
        logger.info("No VMs found matching the criteria.")
        return

    logger.info(f"Found {len(vms)} VM(s):")

    # Prepare data for table
    table_data = []
    for idx, vm in enumerate(vms, start=1):
        name = vm.get('name', '').strip()
        # Use ID if name is empty or missing
        if not name:
            name = vm.get('id', 'unknown')

        # Replace newlines and multiple spaces with single space
        name = ' '.join(name.split())

        # Truncate name if longer than 32 characters
        if len(name) > 32:
            name = name[:22] + "..." + name[-7:]

        cloud = vm.get('cloud', 'unknown')
        account = truncate_account_name(
            vm.get('account_name', vm.get('account_id', 'unknown')))
        region = vm.get('region', 'unknown')

        table_data.append([idx, name, cloud, account, region])

    # Define headers
    headers = ["ID", "VM Name", "Cloud", "Account", "Region"]

    # Print table using tabulate
    print(tabulate(table_data, headers=headers, tablefmt="github"))
    print()


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Discover and manage VMs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Discovery option
    parser.add_argument(
        '-r', '--refresh',
        action='store_true',
        help='Discover VMs from all cloud providers and save to JSON'
    )

    # Selection filters
    parser.add_argument(
        '-i', '--vms',
        type=str,
        help='Absolute selection: VM indices (comma-separated, e.g., "1,3,5") or names to select. Use @filepath to load from file'
    )

    # Action options
    parser.add_argument(
        '-d', '--delete',
        action='store_true',
        help='Delete the selected VMs'
    )
    parser.add_argument(
        '-t', '--tag',
        type=str,
        help='Tag name/key to add to VM(s)'
    )
    parser.add_argument(
        '-v', '--value',
        type=str,
        help='Tag value for the specified tag'
    )
    parser.add_argument(
        '--protected',
        type=str,
        choices=['true', 'false'],
        help='Set protection status for VMs. '
             'true: Prevents deletion and stopping via API/console (AWS: enables DisableApiTermination & DisableApiStop, GCP: enables deletionProtection). '
             'false: Allows deletion and stopping via API/console (removes protection)'
    )

    args = parser.parse_args()

    # Validation: --tag and --value must be used together
    if (args.tag and not args.value) or (args.value and not args.tag):
        logger.error("--tag and --value must be used together.")
        sys.exit(1)

    return args


def refresh():
    """Refresh VM inventory - discover VMs and save to files."""
    result = csp_vm.discover()

    # Log discovery stats
    log_discovery_stats(result['stats'], 'VM')

    save_to_json(result['items'], str(get_inventory_path('vm', 'json')))
    save_vms_to_excel(result['items'], str(get_inventory_path('vm', 'xlsx')))


def main():
    """Main function to execute the script."""
    # Setup logging
    setup_logging()

    args = parse_arguments()

    # Discovery mode - discover, save, and exit
    if args.refresh:
        refresh()
        return

    # For all other operations, we need to work with the inventory
    # Step 1: Load all VMs
    target_vms = load_from_json(str(get_inventory_path('vm', 'json')))

    # Step 2: Apply filters sequentially (each filter operates on the current selection)
    # Track if any filter was applied (for safety check on delete)
    filter_applied = False

    # Filter 1: Absolute selection by -i (indices/names from file)
    if args.vms:
        filter_applied = True
        processed_identifiers = process_identifiers_input(args.vms)
        target_vms = find_items_by_identifier(
            target_vms, processed_identifiers)
        if not target_vms:
            logger.warning("No VMs found matching the specified identifiers.")
            return

    # Step 3: Apply action on target_vms
    if args.delete:
        # Safety check: require at least one filter when deleting
        if not filter_applied:
            logger.error("Delete action requires at least one filter (-i).")
            logger.error("This prevents accidental deletion of all VMs.")
            return

        csp_vm.delete(target_vms)

    elif args.tag and args.value:
        csp_vm.add_tag(target_vms, args.tag, args.value)

    elif args.protected:
        value = args.protected == 'true'
        csp_vm.set_protection(target_vms, value=value)

    else:
        # No action specified, show table
        print_vms(target_vms)


if __name__ == "__main__":
    main()
