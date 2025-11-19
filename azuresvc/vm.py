"""Azure-specific utility functions for VM management."""

from azure.identity import AzureCliCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient

from .session import build_discovery_tasks, create_compute_client
from utils import execute_discovery_tasks, normalize_tags


def get_vms(subscription_id: str) -> list[dict]:
    """Get all VMs in Azure subscription."""
    vms = []

    try:
        compute_client = create_compute_client(subscription_id)
        credential = AzureCliCredential()
        network_client = NetworkManagementClient(credential, subscription_id)

        # Use subscription_id as account_id, try to get a better name from subscription
        account_id = subscription_id
        account_name = subscription_id  # Default to subscription_id

        # Build mappings of NIC ID to VNet name and Subnet name (fetch all NICs once)
        nic_to_vnet = {}
        nic_to_subnet = {}
        try:
            all_nics = network_client.network_interfaces.list_all()
            for nic in all_nics:
                if nic.ip_configurations:
                    subnet_id = nic.ip_configurations[0].subnet.id
                    # Extract VNet name and Subnet name from subnet ID
                    # Format: /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnet}/subnets/{subnet}
                    if '/virtualNetworks/' in subnet_id and '/subnets/' in subnet_id:
                        vnet_name = subnet_id.split(
                            '/virtualNetworks/')[1].split('/')[0]
                        subnet_name = subnet_id.split('/subnets/')[-1]
                        nic_to_vnet[nic.id.lower()] = vnet_name
                        nic_to_subnet[nic.id.lower()] = subnet_name
        except Exception as e:
            print(
                f"Warning: Could not fetch network interfaces for {subscription_id}: {e}")

        # List all VMs across all resource groups
        vm_list = compute_client.virtual_machines.list_all()

        for vm in vm_list:
            # Extract and normalize tags
            tags = normalize_tags(getattr(vm, 'tags', None))

            # Extract resource group from VM ID
            resource_group = vm.id.split('/')[4] if vm.id else 'unknown'

            # Get VM name
            name = getattr(vm, 'name', 'unknown')

            # Convert creation time to YYYY-MM-DDTHH:MM:SS format
            launch_time = None
            if hasattr(vm, 'time_created') and vm.time_created:
                try:
                    launch_time = vm.time_created.strftime('%Y-%m-%dT%H:%M:%S')
                except Exception:
                    launch_time = None

            # Get image reference info
            image_name = 'unknown'
            if vm.storage_profile and vm.storage_profile.image_reference:
                img_ref = vm.storage_profile.image_reference
                if img_ref.publisher and img_ref.offer and img_ref.sku:
                    image_name = f"{img_ref.publisher}/{img_ref.offer}/{img_ref.sku}"
                    if img_ref.version:
                        image_name += f"/{img_ref.version}"

            # Get VNet name and Subnet name from pre-built mapping
            vnet_name = ''
            subnet_name = ''
            region = getattr(vm, 'location', 'unknown')
            if vm.network_profile and vm.network_profile.network_interfaces:
                # Get the first network interface ID
                nic_id = vm.network_profile.network_interfaces[0].id
                vnet_name = nic_to_vnet.get(nic_id.lower(), '')
                subnet_name = nic_to_subnet.get(nic_id.lower(), '')

            # Get availability zone if present (Azure zones are like "1", "2", "3")
            zone = ''
            if hasattr(vm, 'zones') and vm.zones:
                # zones is a list, get first one (just the number)
                zone = vm.zones[0] if vm.zones else ''

            vm_info = {
                'account_id': account_id,
                'account_name': account_name,
                'cloud': 'azure',
                'id': name,  # Azure uses VM name as ID
                'image_name': image_name,
                'launch_time': launch_time,
                'name': name,
                'region': region,
                'zone': zone,
                'resource_group': resource_group,
                'vpc_id': vnet_name,
                'subnet_id': subnet_name,
                'tags': tags
            }

            vms.append(vm_info)

    except Exception as e:
        print(f"Error getting VMs in Azure {subscription_id}: {e}")

    return vms


def delete(vm: dict[str, any]) -> bool:
    """
    Delete an Azure VM.

    Args:
        vm (dict[str, any]): VM dictionary with instance details.
            Required attributes:
            - id (str): Azure VM name
            - account_id (str): Azure subscription ID
            - resource_group (str): Azure resource group name

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        vm_name = vm.get('id')  # In Azure, 'id' is the VM name
        subscription_id = vm.get('account_id')
        resource_group = vm.get('resource_group')

        if not all([vm_name, subscription_id, resource_group]):
            print(
                f"Error: Missing required information for Azure VM (name, subscription, or resource group)")
            return False

        credential = AzureCliCredential()
        compute_client = ComputeManagementClient(credential, subscription_id)

        # Delete the VM (this is a long-running operation)
        poller = compute_client.virtual_machines.begin_delete(
            resource_group_name=resource_group,
            vm_name=vm_name
        )
        poller.result()  # Wait for completion

        print(f"Successfully deleted Azure VM {vm_name}")
        return True
    except Exception as e:
        print(f"Error deleting Azure VM {vm.get('id')}: {e}")
        return False


def add_tag(vm: dict[str, any], tag_name: str, tag_value: str) -> bool:
    """
    Add a tag to an Azure VM.

    Args:
        vm (dict[str, any]): VM dictionary with instance details.
            Required attributes:
            - id (str): Azure VM name
            - account_id (str): Azure subscription ID
            - resource_group (str): Azure resource group name
        tag_name (str): Tag key/name
        tag_value (str): Tag value

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        vm_name = vm.get('id')  # In Azure, 'id' is the VM name
        subscription_id = vm.get('account_id')
        resource_group = vm.get('resource_group')

        if not all([vm_name, subscription_id, resource_group]):
            print(
                f"Error: Missing required information for Azure VM (name, subscription, or resource group)")
            return False

        credential = AzureCliCredential()
        compute_client = ComputeManagementClient(credential, subscription_id)

        # Get the VM to retrieve current tags
        target_vm = compute_client.virtual_machines.get(
            resource_group_name=resource_group,
            vm_name=vm_name
        )

        # Get current tags and add new one
        current_tags = target_vm.tags or {}
        current_tags[tag_name] = tag_value

        # Update tags
        compute_client.virtual_machines.begin_update(
            resource_group_name=resource_group,
            vm_name=vm_name,
            parameters={'tags': current_tags}
        ).result()

        print(f"Successfully added {tag_name} tag to Azure VM {vm_name}")
        return True
    except Exception as e:
        print(f"Error adding tag to Azure VM {vm.get('id')}: {e}")
        return False


def set_protection(vm: dict[str, any], value: bool) -> bool:
    """
    Enable or disable protection for an Azure VM.
    Note: Azure doesn't have direct equivalent to AWS DisableApiTermination.
    Azure uses resource locks for protection.

    Args:
        vm (dict[str, any]): VM dictionary with instance details.
        value (bool): True to enable protection, False to disable

    Returns:
        bool: False (not supported)
    """
    print(
        f"Warning: Protection is not supported for Azure VMs (VM: {vm.get('id')})")
    return False


def discover() -> list[dict]:
    """
    Discover VMs across all configured Azure subscriptions in parallel.

    Returns:
        list[dict]: List of all VM info
    """
    tasks = build_discovery_tasks(get_vms, "VM")
    return execute_discovery_tasks(tasks, max_workers=10)
