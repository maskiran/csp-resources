"""GCP-specific VPC utility functions."""

from google.cloud import compute_v1

from .session import (build_discovery_tasks, create_compute_client,
                      create_networks_client)
from utils import execute_discovery_tasks, load_from_json, get_inventory_path


def get_resource_counts_from_inventory(project_id: str, network_name: str) -> dict:
    """
    Get resource counts for a specific VPC network from inventory files.

    Args:
        project_id: GCP project ID
        network_name: VPC network name to get counts for

    Returns:
        dict with keys: vm_count
    """
    # Configuration mapping count keys to their resource types
    resource_configs = {
        'vm_count': 'vm'
    }

    # Common filters for all resources
    common_filters = {'cloud': 'gcp',
                      'account_id': project_id, 'network_name': network_name}

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


def get_vpcs(project_id: str) -> list[dict]:
    """
    Get all VPC networks in GCP project.
    Uses aggregated list API to get all subnets across all regions in one call.

    Args:
        project_id (str): GCP project ID

    Returns:
        list[dict]: List of VPC network info dictionaries
    """
    vpcs = []

    try:
        # Get networks
        networks_client = compute_v1.NetworksClient()
        networks = networks_client.list(project=project_id)

        for network in networks:
            # Get subnet mode
            subnet_mode = 'legacy'
            if hasattr(network, 'auto_create_subnetworks'):
                if network.auto_create_subnetworks:
                    subnet_mode = 'auto'
                else:
                    subnet_mode = 'custom'

            # Get resource counts from inventory files for this network
            inventory_counts = get_resource_counts_from_inventory(
                project_id, network.name)
            vm_count = inventory_counts['vm_count']

            vpcs.append({
                'id': network.name,
                'name': network.name,
                'description': getattr(network, 'description', ''),
                'subnet_mode': subnet_mode,
                'eni_count': 0,  # Not implemented for GCP yet
                'vm_count': vm_count,
                'routing_mode': getattr(network.routing_config, 'routing_mode', 'unknown') if hasattr(network, 'routing_config') and network.routing_config else 'unknown',
                'mtu': getattr(network, 'mtu', 1460),
                'account_id': project_id,
                'cloud': 'gcp'
            })

    except Exception as e:
        print(f"Error getting GCP VPC networks: {e}")

    return vpcs


def delete(vpc_info: dict) -> bool:
    """
    Delete a GCP VPC network (if empty).

    Args:
        vpc_info (dict): VPC network info dictionary with required attributes:
            - id (str): VPC network name
            - account_id (str): GCP project ID

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        network_name = vpc_info.get('id')
        project_id = vpc_info.get('account_id')

        if not all([network_name, project_id]):
            print(f"Error: Missing required information for GCP VPC network")
            return False

        # Check if it's the default network
        if network_name == 'default':
            print(f"Error: Cannot delete default VPC network")
            return False

        networks_client = compute_v1.NetworksClient()

        # Delete network (will fail if not empty)
        operation = networks_client.delete(
            project=project_id,
            network=network_name
        )
        operation.result()  # Wait for completion

        print(f"Successfully deleted GCP VPC network {network_name}")
        return True
    except Exception as e:
        print(f"Error deleting GCP VPC network {vpc_info.get('id')}: {e}")
        return False


def add_tag(vpc_info: dict, tag_name: str, tag_value: str) -> bool:
    """
    Add a label to a GCP VPC network.

    Args:
        vpc_info (dict): VPC network info dictionary with required attributes:
            - id (str): VPC network name
            - account_id (str): GCP project ID
        tag_name (str): Label key/name (will be converted to lowercase)
        tag_value (str): Label value

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        network_name = vpc_info.get('id')
        project_id = vpc_info.get('account_id')

        if not all([network_name, project_id]):
            print(f"Error: Missing required information for GCP VPC network tagging")
            return False

        networks_client = compute_v1.NetworksClient()

        # Get current network
        network = networks_client.get(
            project=project_id,
            network=network_name
        )

        # Get current labels and add new one
        # GCP labels must be lowercase and can only contain lowercase letters, numbers, hyphens, and underscores
        current_labels = dict(network.labels.items()) if network.labels else {}
        # Convert tag name to lowercase and normalize tag value
        label_name = tag_name.lower()
        label_value = tag_value.lower().replace('.', '-')
        current_labels[label_name] = label_value

        # Update labels
        request = compute_v1.SetLabelsNetworkRequest(
            project=project_id,
            network=network_name,
            networks_set_labels_request_resource=compute_v1.NetworksSetLabelsRequest(
                labels=current_labels,
                label_fingerprint=network.label_fingerprint
            )
        )

        operation = networks_client.set_labels(request=request)
        operation.result()

        print(
            f"Successfully added {label_name} label to GCP VPC network {network_name}")
        return True
    except Exception as e:
        print(
            f"Error adding label to GCP VPC network {vpc_info.get('id')}: {e}")
        return False


def discover() -> list[dict]:
    """
    Discover VPC networks across all configured GCP projects.

    Returns:
        list[dict]: List of all VPC network info
    """
    tasks = build_discovery_tasks(get_vpcs, "VPC")
    return execute_discovery_tasks(tasks, max_workers=10)
