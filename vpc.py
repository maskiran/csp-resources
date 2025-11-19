#!/usr/bin/env python3
"""
VPC/VNet Management Script - Discover and manage VPCs/VNets from all cloud providers.

This script provides discovery and management capabilities for virtual networks:
- List and filter VPCs/VNets by cloud provider or account
- View detailed network information (including console URLs)
- Add tags to VPCs/VNets (similar to VM tagging)
- Save inventory to vpc.json file
- Parallel discovery across all regions/zones for maximum efficiency

Supported resources:
- AWS: Virtual Private Clouds (VPCs)
- Azure: Virtual Networks (VNets)  
- GCP: VPC Networks

Usage examples:
  # Discover all VPCs/VNets
  python vpc.py --refresh
  
  # List all VPCs/VNets from inventory
  python vpc.py
  
  # Show VPCs by index, ID, or name
  python vpc.py -i 1,5,vpc-12345
  
  # Load VPC identifiers from a file
  python vpc.py -i @/tmp/vpc_ids.txt
  
  # Delete specific VPCs
  python vpc.py -i 1,2,3 -d
  
  # Add custom tag to VPCs
  python vpc.py -i 1,2,3 -t Environment -v Production
"""

import argparse
import logging
import sys
from typing import Any

from tabulate import tabulate

from csp import vpc as csp_vpc
from utils import find_items_by_identifier, load_from_json, process_identifiers_input, save_to_json, truncate_account_name, save_to_excel, setup_logging, log_discovery_stats, get_inventory_path

logger = logging.getLogger(__name__)


def prepare_vpc_table_data(vpcs: list[dict[str, Any]]) -> list[list[Any]]:
    """Prepare VPC data for Excel export."""
    data = []
    for vpc in vpcs:
        # Get account info
        account = ""
        if 'profile' in vpc:
            account = vpc['profile']
        elif 'account_id' in vpc:
            account = vpc['account_id']

        # Get location/region
        location = vpc.get('region', vpc.get('location', 'global'))

        # Get CIDR or address info
        cidr = ""
        if 'cidr_block' in vpc:
            cidr = vpc['cidr_block']
        elif 'address_prefixes' in vpc and vpc['address_prefixes']:
            cidr = ', '.join(vpc['address_prefixes'][:2])  # Show first 2
            if len(vpc['address_prefixes']) > 2:
                cidr += '...'
        elif 'subnet_mode' in vpc:
            cidr = vpc['subnet_mode']

        # Only show ID for AWS VPCs
        vpc_id = vpc.get('id', '') if vpc.get(
            'cloud', '').lower() == 'aws' else ''

        # Prepare row data
        row = [
            vpc.get('name', ''),
            vpc_id,
            vpc.get('cloud', '').upper(),
            account,
            location,
            cidr,
            vpc.get('eni_count', 0),
            vpc.get('vm_count', 0)
        ]
        data.append(row)

    return data


def save_vpcs_to_excel(vpcs: list[dict[str, Any]], filename: str):
    """Save VPC data to Excel file with filtering and sorting."""
    data = prepare_vpc_table_data(vpcs)
    headers = ["Name", "ID", "Cloud", "Account",
               "Region", "CIDR/Mode", "ENIs", "VMs"]
    save_to_excel(filename, "VPCs", headers, data)


def print_vpcs(vpcs: list[dict[str, Any]]) -> None:
    """Print VPCs/VNets in a table format."""
    if not vpcs:
        logger.info("No VPCs/VNets found.")
        return

    # Prepare data for table
    table_data = []
    for idx, vpc in enumerate(vpcs, 1):
        # Skip default VPCs but maintain numbering
        if vpc.get('is_default', False):
            continue

        name = vpc.get('name', 'unnamed')
        # If name is unnamed or empty, use VPC ID
        if not name or name == 'unnamed':
            name = vpc.get('id', 'unknown')
        cloud = vpc.get('cloud', 'unknown').upper()

        # Get account info
        account = ''
        if 'profile' in vpc:
            account = truncate_account_name(vpc['profile'])
        elif 'account_id' in vpc:
            account = truncate_account_name(vpc['account_id'])

        # Get location/region
        location = vpc.get('region', vpc.get('location', 'global'))

        # Get CIDR or address info
        cidr = ''
        if 'cidr_block' in vpc:
            cidr = vpc['cidr_block']
        elif 'address_prefixes' in vpc and vpc['address_prefixes']:
            cidr = ', '.join(vpc['address_prefixes'][:2])  # Show first 2
            if len(vpc['address_prefixes']) > 2:
                cidr += '...'
        elif 'subnet_mode' in vpc:
            cidr = vpc['subnet_mode']

        # Get resource counts
        eni_count = vpc.get('eni_count', 0)
        vm_count = vpc.get('vm_count', 0)

        table_data.append([idx, name, cloud, account,
                          location, cidr, eni_count, vm_count])

    # Define headers
    headers = ["ID", "Name", "Cloud", "Account",
               "Region", "CIDR/Mode", "ENIs", "VMs"]

    # Print table using tabulate
    print(tabulate(table_data, headers=headers, tablefmt="github"))
    print()


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Discover and manage VPCs/VNets',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Discovery option
    parser.add_argument(
        '-r', '--refresh',
        action='store_true',
        help='Discover VPCs/VNets across all clouds and save to JSON'
    )

    # Selection filters
    parser.add_argument(
        '-i', '--vpcs',
        type=str,
        help='Absolute selection: VPC indices (comma-separated, e.g., "1,3,5") or IDs/names to select. Use @filepath to load from file'
    )

    # Action options
    parser.add_argument(
        '-d', '--delete',
        action='store_true',
        help='Delete the selected VPCs'
    )
    parser.add_argument(
        '-t', '--tag',
        type=str,
        help='Tag name/key to add to VPC(s)'
    )
    parser.add_argument(
        '-v', '--value',
        type=str,
        help='Tag value for the specified tag'
    )

    args = parser.parse_args()

    # Validation: --tag and --value must be used together
    if (args.tag and not args.value) or (args.value and not args.tag):
        logger.error("--tag and --value must be used together.")
        sys.exit(1)

    return args


def refresh():
    """Refresh VPC inventory - discover VPCs and save to files."""
    result = csp_vpc.discover()

    # Log discovery stats
    log_discovery_stats(result['stats'], 'VPC')

    save_to_json(result['items'], str(get_inventory_path('vpc', 'json')))
    save_vpcs_to_excel(result['items'], str(get_inventory_path('vpc', 'xlsx')))


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
    # Step 1: Load all VPCs
    target_vpcs = load_from_json(str(get_inventory_path('vpc', 'json')))

    # Step 2: Apply filters sequentially (each filter operates on the current selection)
    # Track if any filter was applied (for safety check on delete)
    filter_applied = False

    # Filter 1: Absolute selection by -i (indices/names from file)
    if args.vpcs:
        filter_applied = True
        processed_identifiers = process_identifiers_input(args.vpcs)
        target_vpcs = find_items_by_identifier(
            target_vpcs, processed_identifiers)
        if not target_vpcs:
            logger.warning("No VPCs found matching the specified identifiers.")
            return

    # Step 2: Apply action on target_vpcs
    if args.delete:
        # Safety check: require at least one filter when deleting
        if not filter_applied:
            logger.error("Delete action requires at least one filter (-i).")
            logger.error("This prevents accidental deletion of all VPCs.")
            return

        csp_vpc.delete(target_vpcs)

    elif args.tag and args.value:
        csp_vpc.add_tag(target_vpcs, args.tag, args.value)

    else:
        # No action specified, show table
        print_vpcs(target_vpcs)


if __name__ == "__main__":
    main()
