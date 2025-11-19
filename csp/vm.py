"""
Unified VM management across all cloud providers.
"""

from typing import Any

from awssvc import vm as awsvm
from azuresvc import vm as azurevm
from gcpsvc import vm as gcpvm
from utils import discover_across_clouds, execute_items_operation


def discover() -> dict[str, Any]:
    """
    Discover VMs across all cloud providers in parallel.

    Returns:
        Dict with 'items' (list of VMs) and 'stats' (discovery statistics)
    """
    return discover_across_clouds({
        'aws': awsvm.discover,
        'azure': azurevm.discover,
        'gcp': gcpvm.discover
    })


def delete(vms: list[dict[str, Any]]) -> None:
    """
    Delete VMs across all cloud providers in parallel.

    Args:
        vms: List of VM dictionaries from any cloud provider
    """
    cloud_operations = {
        'aws': awsvm.delete,
        'azure': azurevm.delete,
        'gcp': gcpvm.delete
    }
    execute_items_operation(vms, cloud_operations, "Delete VMs", confirm=True)


def add_tag(vms: list[dict[str, Any]], tag_name: str, tag_value: str) -> None:
    """
    Add tags to VMs across all cloud providers in parallel.

    Args:
        vms: List of VM dictionaries from any cloud provider
        tag_name: Tag name/key to add
        tag_value: Tag value to add
    """
    print(f"\nTag to add: {tag_name} = {tag_value}")

    cloud_operations = {
        'aws': lambda vm: awsvm.add_tag(vm, tag_name, tag_value),
        'azure': lambda vm: azurevm.add_tag(vm, tag_name, tag_value),
        'gcp': lambda vm: gcpvm.add_tag(vm, tag_name, tag_value)
    }
    execute_items_operation(vms, cloud_operations, "Tag VMs", confirm=True)


def set_protection(vms: list[dict[str, Any]], value: bool) -> None:
    """
    Enable or disable protection for VMs across all cloud providers.

    Args:
        vms: List of VM dictionaries from any cloud provider
        value: True to enable protection, False to disable
    """
    status = "enable" if value else "disable"
    print(f"\nProtection: {status}")

    cloud_operations = {
        'aws': lambda vm: awsvm.set_protection(vm, value),
        'azure': lambda vm: azurevm.set_protection(vm, value),
        'gcp': lambda vm: gcpvm.set_protection(vm, value)
    }
    execute_items_operation(
        vms, cloud_operations, f"{status.capitalize()} protection", confirm=True)
