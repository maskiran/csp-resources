"""
Unified VPC management across all cloud providers.
"""

from typing import Any

from awssvc import vpc as awsvpc
from azuresvc import vpc as azurevpc
from gcpsvc import vpc as gcpvpc
from utils import discover_across_clouds, execute_items_operation


def discover() -> dict[str, Any]:
    """
    Discover VPCs/VNets across all cloud providers in parallel.

    Returns:
        Dict with 'items' (list of VPCs/VNets) and 'stats' (discovery statistics)
    """
    return discover_across_clouds({
        'aws': awsvpc.discover,
        'azure': azurevpc.discover,
        'gcp': gcpvpc.discover
    })


def delete(vpcs: list[dict[str, Any]]) -> None:
    """
    Delete VPCs/VNets across all cloud providers in parallel.

    Args:
        vpcs: List of VPC dictionaries from any cloud provider
    """
    cloud_operations = {
        'aws': awsvpc.delete,
        'azure': azurevpc.delete,
        'gcp': gcpvpc.delete
    }
    execute_items_operation(vpcs, cloud_operations,
                            "Delete VPCs", confirm=True)


def add_tag(vpcs: list[dict[str, Any]], tag_name: str, tag_value: str) -> None:
    """
    Add tags to VPCs/VNets across all cloud providers in parallel.

    Args:
        vpcs: List of VPC dictionaries from any cloud provider
        tag_name: Tag name/key to add
        tag_value: Tag value to add
    """
    print(f"\nTag to add: {tag_name} = {tag_value}")

    cloud_operations = {
        'aws': lambda vpc: awsvpc.add_tag(vpc, tag_name, tag_value),
        'azure': lambda vpc: azurevpc.add_tag(vpc, tag_name, tag_value),
        'gcp': lambda vpc: gcpvpc.add_tag(vpc, tag_name, tag_value)
    }
    execute_items_operation(vpcs, cloud_operations, "Tag VPCs", confirm=True)
