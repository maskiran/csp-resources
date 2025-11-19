"""Azure-specific VNet utility functions."""

from azure.identity import AzureCliCredential
from azure.mgmt.network import NetworkManagementClient

from .session import (build_discovery_tasks, create_compute_client,
                      create_network_client, create_resource_client)
from utils import execute_discovery_tasks, load_from_json, get_inventory_path


def get_resource_counts_from_inventory(subscription_id: str, location: str, vnet_name: str) -> dict:
    """
    Get resource counts for a specific VNet from inventory files.
    
    Args:
        subscription_id: Azure subscription ID
        location: Azure location/region
        vnet_name: VNet name to get counts for
        
    Returns:
        dict with keys: vm_count
    """
    # Configuration mapping count keys to their resource types
    resource_configs = {
        'vm_count': 'vm'
    }
    
    # Common filters for all resources
    common_filters = {'cloud': 'azure', 'account_id': subscription_id, 'location': location, 'vnet_name': vnet_name}
    
    # Initialize counts
    counts = {key: 0 for key in resource_configs.keys()}
    
    # Process each resource type
    for count_key, resource_type in resource_configs.items():
        try:
            file_path = get_inventory_path(resource_type, 'json')
            if file_path.exists():
                items = load_from_json(str(file_path))
                for item in items:
                    # Check if all filters match
                    if all(item.get(k) == v for k, v in common_filters.items()):
                        counts[count_key] += 1
        except Exception:
            pass
    
    return counts


def get_vpcs(subscription_id: str) -> list[dict]:
    """
    Get all Virtual Networks in Azure subscription.

    Args:
        subscription_id (str): Azure subscription ID

    Returns:
        list[dict]: List of VNet info dictionaries
    """
    vnets = []

    try:
        credential = AzureCliCredential()
        network_client = NetworkManagementClient(credential, subscription_id)

        # Get all virtual networks
        virtual_networks = network_client.virtual_networks.list_all()

        for vnet in virtual_networks:
            # Parse resource group from ID
            resource_group = vnet.id.split('/')[4] if vnet.id else 'unknown'

            # Get address prefixes
            address_prefixes = []
            if vnet.address_space and vnet.address_space.address_prefixes:
                address_prefixes = list(vnet.address_space.address_prefixes)

            # Get resource counts from inventory files for this VNet
            inventory_counts = get_resource_counts_from_inventory(subscription_id, vnet.location, vnet.name)
            vm_count = inventory_counts['vm_count']

            vnets.append({
                'id': vnet.name,
                'name': vnet.name,
                'resource_group': resource_group,
                'location': vnet.location,
                'address_prefixes': address_prefixes,
                'eni_count': 0,  # Not implemented for Azure yet
                'vm_count': vm_count,
                'provisioning_state': vnet.provisioning_state,
                'account_id': subscription_id,
                'cloud': 'azure',
                'tags': dict(vnet.tags) if vnet.tags else {}
            })

    except Exception as e:
        print(f"Error getting Azure VNets: {e}")

    return vnets


def delete(vpc_info: dict) -> bool:
    """
    Delete an Azure VNet (if empty).

    Args:
        vpc_info (dict): VNet info dictionary with required attributes:
            - id (str): VNet name
            - account_id (str): Azure subscription ID  
            - resource_group (str): Azure resource group name

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        vnet_name = vpc_info.get('id')
        subscription_id = vpc_info.get('account_id')
        resource_group = vpc_info.get('resource_group')

        if not all([vnet_name, subscription_id, resource_group]):
            print(f"Error: Missing required information for Azure VNet")
            return False

        credential = AzureCliCredential()
        network_client = NetworkManagementClient(credential, subscription_id)

        # Delete the VNet (this is a long-running operation)
        poller = network_client.virtual_networks.begin_delete(
            resource_group_name=resource_group,
            virtual_network_name=vnet_name
        )
        poller.result()  # Wait for completion

        print(f"Successfully deleted Azure VNet {vnet_name}")
        return True
    except Exception as e:
        print(f"Error deleting Azure VNet {vpc_info.get('id')}: {e}")
        return False


def add_tag(vpc_info: dict, tag_name: str, tag_value: str) -> bool:
    """
    Add a tag to an Azure VNet.

    Args:
        vpc_info (dict): VNet info dictionary with required attributes:
            - id (str): VNet name
            - account_id (str): Azure subscription ID
            - resource_group (str): Azure resource group name
        tag_name (str): Tag key/name
        tag_value (str): Tag value

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        vnet_name = vpc_info.get('id')
        subscription_id = vpc_info.get('account_id')
        resource_group = vpc_info.get('resource_group')

        if not all([vnet_name, subscription_id, resource_group]):
            print(f"Error: Missing required information for Azure VNet tagging")
            return False

        credential = AzureCliCredential()
        network_client = NetworkManagementClient(credential, subscription_id)

        # Get the VNet to retrieve current tags
        target_vnet = network_client.virtual_networks.get(
            resource_group_name=resource_group,
            virtual_network_name=vnet_name
        )

        # Get current tags and add new one
        current_tags = target_vnet.tags or {}
        current_tags[tag_name] = tag_value

        # Update tags
        network_client.virtual_networks.begin_create_or_update(
            resource_group_name=resource_group,
            virtual_network_name=vnet_name,
            parameters={
                'location': target_vnet.location,
                'tags': current_tags
            }
        ).result()

        print(f"Successfully added {tag_name} tag to Azure VNet {vnet_name}")
        return True
    except Exception as e:
        print(f"Error adding tag to Azure VNet {vpc_info.get('id')}: {e}")
        return False


def discover() -> list[dict]:
    """
    Discover VNets across all configured Azure subscriptions.

    Returns:
        list[dict]: List of all VNet info
    """
    tasks = build_discovery_tasks(get_vpcs, "VNet")
    return execute_discovery_tasks(tasks, max_workers=10)
