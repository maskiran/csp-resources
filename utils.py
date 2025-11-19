"""
Utility functions shared across multiple scripts.
"""

import json
import logging
import sys
import termios
import time
import tty
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.worksheet.table import Table

logger = logging.getLogger(__name__)

# Inventory configuration
# Path is relative to the project root (where utils.py is located)
INVENTORY_DIR = Path(__file__).parent / "inventory"


def get_inventory_path(resource_type: str, extension: str = 'json') -> Path:
    """
    Get the full path to an inventory file.

    Args:
        resource_type: Type of resource (e.g., 'vm', 'vpc')
        extension: File extension without dot (default: 'json')

    Returns:
        Path object to the inventory file (e.g., 'inventory/vm.json')
    """
    filename = f"{resource_type}.{extension}"
    return INVENTORY_DIR / filename


def setup_logging(level: str = "INFO") -> None:
    """
    Configure logging for the application.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        force=True
    )

    # Set specific logger levels for noisy libraries
    logging.getLogger('azure').setLevel(logging.WARNING)
    logging.getLogger('boto3').setLevel(logging.WARNING)
    logging.getLogger('botocore').setLevel(logging.WARNING)
    logging.getLogger('google').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)


def log_discovery_stats(stats: dict[str, Any], resource_type: str) -> None:
    """
    Log discovery statistics for resources.

    Args:
        stats: Statistics dict with cloud-specific and overall stats
        resource_type: Type of resource (e.g., 'VM', 'VPC')
    """
    logger.info("Resource Discovery Summary")
    logger.info("=" * 50)
    for cloud in ['aws', 'azure', 'gcp']:
        if cloud in stats:
            cloud_stats = stats[cloud]
            logger.info(
                f"{cloud.upper():<6}: {cloud_stats['duration']:>6.2f}s | {cloud_stats['count']:>3} {resource_type}(s)")
            if cloud_stats['status'] == 'failed':
                logger.error(
                    f"    Error: {cloud_stats.get('error', 'Unknown')}")
    logger.info("=" * 50)
    logger.info(f"Total {resource_type}s discovered: {stats['all']['count']}")
    logger.info(f"Total discovery time: {stats['all']['duration']:.2f}s")


def process_identifiers_input(identifiers: str) -> str:
    """
    Process identifier input, handling file input if prefixed with @.

    If the input starts with @, read identifiers from the specified file
    (one identifier per line, like copy-pasted from Excel).

    Args:
        identifiers: String containing identifiers or @filepath

    Returns:
        str: Comma-separated string of identifiers

    Raises:
        SystemExit: If file cannot be read or is empty
    """
    if not identifiers.startswith('@'):
        return identifiers

    file_path_str = identifiers[1:].strip()
    if not file_path_str:
        logger.error("No file path specified after @")
        sys.exit(1)

    file_path = Path(file_path_str).expanduser()
    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        sys.exit(1)

    try:
        lines = file_path.read_text().splitlines(keepends=True)
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")
        sys.exit(1)

    identifiers_list = [line.strip() for line in lines if line.strip()]
    if not identifiers_list:
        logger.error(f"No identifiers found in file: {file_path}")
        sys.exit(1)

    result = ','.join(identifiers_list)
    logger.info(
        f"Loaded {len(identifiers_list)} identifier(s) from {file_path}")
    return result


def truncate_account_name(account_name: str) -> str:
    """Truncate account name to max 20 chars (first 10 + ... + last 7)."""
    if len(account_name) > 20:
        return account_name[:10] + "..." + account_name[-7:]
    return account_name


def normalize_tags(tags_input) -> dict:
    """
    Normalize tags/labels to lowercase keys.

    Args:
        tags_input: Can be:
            - AWS: list of {'Key': str, 'Value': str} dicts
            - Azure/GCP: dict with string keys and values
            - None/empty

    Returns:
        dict: Normalized tags with lowercase keys
    """
    tags = {}

    if not tags_input:
        return tags

    # Handle AWS format: list of {'Key': 'key', 'Value': 'value'} dicts
    if isinstance(tags_input, list):
        for tag in tags_input:
            if isinstance(tag, dict) and 'Key' in tag and 'Value' in tag:
                tags[tag['Key'].lower()] = tag['Value']

    # Handle Azure/GCP format: dict with string keys
    elif isinstance(tags_input, dict):
        for key, value in tags_input.items():
            tags[key.lower()] = value

    return tags


def getch() -> str:
    """Get single character from user without waiting for Enter."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def confirm_action(items: list[dict[str, Any]], action_description: str) -> bool:
    """
    Ask for confirmation before performing an action on items.

    Args:
        items: List of items for the action (with name, cloud, account info)
        action_description: Description of the action (e.g., "Delete 5 VMs", "Tag 3 VPCs")

    Returns:
        bool: True if user confirms, False otherwise
    """
    if not items:
        return False

    print(f"\n{action_description}:")
    print("-" * 60)

    for item in items:
        cloud = item.get('cloud', 'Unknown').upper()
        name = item.get('name', 'Unknown')

        # Get account info based on cloud type
        account = ''
        if 'profile' in item:
            account = item['profile']
        elif 'account_id' in item:
            account = item['account_id']
        elif 'subscription_id' in item:
            account = item['subscription_id']

        # Get location
        location = item.get('region', item.get('location', 'Unknown'))

        print(f"{name} - {cloud}/{account}/{location}")

    print("-" * 60)
    print(f"Total: {len(items)} item(s)")

    print("\nContinue? (y/n): ", end='', flush=True)
    response = getch().lower()
    print(response)  # Echo the character
    return response == 'y'


def load_from_json(filename: str) -> list[dict[str, Any]]:
    """
    Load items from JSON file with standardized error handling.

    Args:
        filename: Path to the JSON file

    Returns:
        List of items loaded from file

    Raises:
        SystemExit: If file not found or invalid JSON
    """
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"File {filename} not found. Run with --refresh first.")
        sys.exit(1)
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in {filename}")
        sys.exit(1)


def save_to_json(items: list[dict[str, Any]], filename: str):
    """
    Save items to JSON file with standardized formatting.

    Args:
        items: List of items to save
        filename: Path to save the JSON file
    """
    # Ensure directory exists
    file_path = Path(filename)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    file_path.write_text(json.dumps(items, indent=2))

    logger.info(f"Saved {len(items)} items to {filename}")


def save_to_excel(filename: str, title: str, headers: list[str], data: list[list[Any]]) -> None:
    """
    Save data to Excel file with filtering and sorting capabilities.

    Args:
        filename (str): Full path to the Excel file to create
        title (str): Worksheet title
        headers (list[str]): Column headers
        data (list[list[Any]]): Data rows (each row is a list of values)
    """
    if not data:
        logger.warning(f"No data to export to {filename}")
        return

    # Create directory if it doesn't exist
    file_path = Path(filename)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Create workbook and worksheet
    wb = Workbook()
    ws = wb.active
    ws.title = title

    # Add headers
    ws.append(headers)

    # Add data rows
    for row in data:
        ws.append(row)

    # Create table for filtering and sorting
    if len(data) > 0:
        table_range = f"A1:{chr(ord('A') + len(headers) - 1)}{len(data) + 1}"
        # Remove spaces for table name
        table_name = title.replace(' ', '') + "Table"
        table = Table(displayName=table_name, ref=table_range)
        ws.add_table(table)

    # Auto-adjust column widths
    for column in ws.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = min(max_length + 2, 80)  # Cap at 80 characters
        ws.column_dimensions[column_letter].width = adjusted_width

    # Save workbook
    wb.save(str(file_path))
    logger.info(f"Saved {len(data)} rows to {filename}")


def find_items_by_identifier(
    items: list[dict[str, Any]],
    identifiers: str,
    id_key: str = 'id',     # Key for ID lookup
    name_key: str = 'name'  # Key for name lookup
) -> list[dict[str, Any]]:
    """
    Find items by list index, ID, or name. Supports comma-separated values.

    Args:
        items: List of items to search through
        identifiers: Comma-separated list of indices (1-based), IDs, or names
        id_key: Key for ID lookup (default: 'id')
        name_key: Key for name lookup (default: 'name')

    Returns:
        List of matching items
    """
    identifier_list = [id.strip() for id in identifiers.split(',')]

    # Create lookup maps for faster searching
    id_map = {item.get(id_key): item for item in items if item.get(id_key)}
    name_map = {
        item.get(name_key): item for item in items if item.get(name_key)}

    matching_items = []

    for identifier in identifier_list:
        # Try to parse as integer (1-based list index)
        try:
            index = int(identifier)
            if 1 <= index <= len(items):
                matching_items.append(items[index - 1])
            else:
                logger.error(f"Index {index} out of range (1-{len(items)})")
        except ValueError:
            # Not an integer, try ID and name lookup
            if identifier in id_map:
                matching_items.append(id_map[identifier])
            elif identifier in name_map:
                matching_items.append(name_map[identifier])
            else:
                logger.error(f"No item found with ID or name: {identifier}")

    return matching_items


def discover_across_clouds(
    cloud_discovery_functions: dict[str, Callable],
    max_workers: int = 3
) -> dict[str, Any]:
    """
    Discover resources across multiple cloud providers in parallel with timing stats.

    Args:
        cloud_discovery_functions: Dict mapping cloud names to discovery functions
        max_workers: ThreadPoolExecutor max workers

    Returns:
        Dict with 'items' (list of resources) and 'stats' (dict with keys: 'aws', 'azure', 'gcp', 'all')
    """
    all_resources = []
    stats = {}

    # Initialize overall stats with start time
    stats['all'] = {'start_time': datetime.now()}

    # Discover across all cloud providers in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit tasks and record start times
        futures = {}

        for cloud_name, discover_func in cloud_discovery_functions.items():
            start_time = datetime.now()
            stats[cloud_name] = {'start_time': start_time}
            future = executor.submit(discover_func)
            futures[future] = cloud_name

        for future in as_completed(futures):
            cloud = futures[future]
            end_time = datetime.now()
            start_time = stats[cloud]['start_time']
            duration = (end_time - start_time).total_seconds()

            try:
                resources = future.result()
                all_resources.extend(resources)
                stats[cloud].update({
                    'end_time': end_time,
                    'duration': duration,
                    'count': len(resources),
                    'status': 'success'
                })
            except Exception as e:
                stats[cloud].update({
                    'end_time': end_time,
                    'duration': duration,
                    'count': 0,
                    'status': 'failed',
                    'error': str(e)
                })

    # Update overall stats with end time, duration, and count
    end_time = datetime.now()
    duration = (end_time - stats['all']['start_time']).total_seconds()
    stats['all'].update({
        'end_time': end_time,
        'duration': duration,
        'count': len(all_resources),
        'status': 'success'
    })

    return {
        'items': all_resources,
        'stats': stats
    }


def execute_items_operation(
    items: list[dict[str, Any]],
    cloud_operations: dict[str, Callable],
    action_description: str,
    confirm: bool = True,
    max_workers: int = 10
) -> None:
    """
    Execute cloud-specific operations in parallel across all items.

    Args:
        items: List of items to process
        cloud_operations: Dict mapping cloud names (e.g., 'aws', 'azure', 'gcp') to callable functions.
            Each callable receives a single item from the items list as its argument.
            Example: {'aws': awsvm.delete, 'azure': azurevm.delete, 'gcp': gcpvm.delete}
            Where: def awsvm.delete(vm: dict[str, any]) -> bool
        action_description: Description of the action (e.g., "Delete VMs", "Tag VPCs")
        confirm: Whether to show confirmation prompt
        max_workers: Maximum number of concurrent operations (default: 10)
    """
    if not items:
        logger.info("No items to process.")
        return

    if confirm and not confirm_action(items, f"{action_description} {len(items)} item(s)"):
        logger.info("Operation cancelled.")
        return

    logger.info(f"{action_description} {len(items)} item(s) in parallel...")

    success_count = 0
    processed_count = 0
    total_count = len(items)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_item = {}

        for item in items:
            cloud = item.get('cloud', '').lower()
            if cloud in cloud_operations:
                future = executor.submit(cloud_operations[cloud], item)
                future_to_item[future] = item
            else:
                logger.warning(
                    f"Unknown cloud provider '{cloud}' for {item.get('name', 'unknown')}")

        for future in as_completed(future_to_item):
            item = future_to_item[future]
            processed_count += 1
            name = item.get('name', item.get('id', 'Unknown'))
            cloud = item.get('cloud', 'unknown').upper()

            logger.info(f"[{processed_count}/{total_count}] {cloud} - {name}")

            try:
                if future.result():
                    success_count += 1
            except Exception as e:
                logger.error(f"  Error: {e}")

    logger.info(
        f"{action_description} completed: {success_count} out of {total_count} item(s) successful")


def execute_discovery_tasks(tasks: list[dict[str, Any]], max_workers: int = 20) -> list[dict[str, Any]]:
    """
    Execute discovery tasks in parallel and collect results.

    Args:
        tasks: List of task dictionaries with 'func', 'args', and 'context'
        max_workers: Maximum number of concurrent workers

    Returns:
        list[dict[str, Any]]: Combined results from all tasks
    """
    all_resources = []

    if not tasks:
        return all_resources

    total_tasks = len(tasks)
    completed_tasks = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_context = {
            executor.submit(task['func'], *task['args']): task['context']
            for task in tasks
        }

        for future in as_completed(future_to_context):
            context = future_to_context[future]
            completed_tasks += 1

            # Extract context info for logging
            cloud = context['cloud'].upper()
            location = context.get('location', '')

            try:
                resources = future.result()
                all_resources.extend(resources)

                resource_name = context['resource']
                logger.info(
                    f"{completed_tasks}/{total_tasks} {cloud} {location}: found {len(resources)} {resource_name}(s)")
            except Exception as e:
                logger.error(
                    f"{completed_tasks}/{total_tasks} {cloud} {location}: Error - {e}")

    return all_resources
