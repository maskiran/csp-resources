"""GCP-specific utility functions for VM management."""

from datetime import datetime

from google.cloud import compute_v1

from .session import build_discovery_tasks, create_compute_client
from utils import execute_discovery_tasks, normalize_tags


def get_vms(project_id: str) -> list[dict]:
    """Get all VM instances across all zones in a GCP project using aggregated list."""
    vms = []

    try:
        compute_client = create_compute_client()

        # Use project_id as account_id and account_name
        account_id = project_id
        account_name = project_id  # Use project ID as account name

        # Use aggregated_list to get all instances across all zones in one API call
        request = compute_v1.AggregatedListInstancesRequest(project=project_id)
        agg_list = compute_client.aggregated_list(request=request)

        # Iterate through all zones
        for zone, response in agg_list:
            if response.instances:
                # Extract zone name from the zone key (format: "zones/zone-name")
                zone_name = zone.split('/')[-1] if '/' in zone else zone

                for instance in response.instances:
                    # Extract and normalize labels (GCP's version of tags)
                    # Convert labels mapping to dict if present
                    raw_labels = None
                    if hasattr(instance, 'labels') and instance.labels:
                        raw_labels = dict(instance.labels.items())
                    labels = normalize_tags(raw_labels)

                    # Get instance name
                    name = getattr(instance, 'name', 'unknown')

                    # Convert creation timestamp to YYYY-MM-DDTHH:MM:SS format
                    launch_time = None
                    if hasattr(instance, 'creation_timestamp') and instance.creation_timestamp:
                        try:
                            # Parse ISO 8601 timestamp and format to YYYY-MM-DDTHH:MM:SS
                            dt = datetime.fromisoformat(
                                instance.creation_timestamp.replace('Z', '+00:00'))
                            launch_time = dt.strftime('%Y-%m-%dT%H:%M:%S')
                        except Exception:
                            launch_time = None

                    # Get image name from boot disk
                    image_name = 'unknown'
                    if instance.disks:
                        for disk in instance.disks:
                            if disk.boot and hasattr(disk, 'source'):
                                # Extract image name from source URL
                                source = disk.source
                                if source and 'disks/' in source:
                                    image_name = source.split('/')[-1]
                                break

                    # Get network name and subnetwork name from network interface
                    network_name = ''
                    subnetwork_name = ''
                    try:
                        if instance.network_interfaces:
                            network_url = instance.network_interfaces[0].network
                            subnetwork_url = instance.network_interfaces[0].subnetwork
                            # Extract network name from URL
                            # Format: https://www.googleapis.com/compute/v1/projects/{project}/global/networks/{network}
                            if network_url and '/networks/' in network_url:
                                network_name = network_url.split(
                                    '/networks/')[-1]
                            # Extract subnetwork name from URL
                            # Format: https://www.googleapis.com/compute/v1/projects/{project}/regions/{region}/subnetworks/{subnetwork}
                            if subnetwork_url and '/subnetworks/' in subnetwork_url:
                                subnetwork_name = subnetwork_url.split(
                                    '/subnetworks/')[-1]
                    except Exception:
                        pass  # Keep empty if we can't determine network/subnetwork

                    # Extract region from zone (zone format: us-central1-a -> region: us-central1)
                    region_name = zone_name
                    if zone_name and '-' in zone_name:
                        # Split by '-' and take all but the last part
                        parts = zone_name.rsplit('-', 1)
                        region_name = parts[0] if len(parts) > 1 else zone_name

                    vm_info = {
                        'account_id': account_id,
                        'account_name': account_name,
                        'cloud': 'gcp',
                        'id': name,  # GCP uses VM name as ID
                        'state': instance.status.lower() if hasattr(instance, 'status') else 'unknown',
                        'image_name': image_name,
                        'launch_time': launch_time,
                        'name': name,
                        'vpc_id': network_name,
                        'subnet_id': subnetwork_name,
                        'region': region_name,
                        'zone': zone_name,
                        'tags': labels  # GCP calls them labels
                    }

                    vms.append(vm_info)

    except Exception as e:
        print(f"Error getting VMs in GCP {project_id}: {e}")

    return vms


def delete(vm: dict[str, any]) -> bool:
    """
    Delete a GCP VM instance.

    Args:
        vm (dict[str, any]): VM dictionary with instance details.
            Required attributes:
            - id (str): GCP instance name
            - account_id (str): GCP project ID
            - zone (str): GCP zone (or region as fallback)

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        instance_name = vm.get('id')  # In GCP, 'id' is the instance name
        project_id = vm.get('account_id')
        zone = vm.get('zone', vm.get('region'))

        if not all([instance_name, project_id, zone]):
            print(f"Error: Missing required information for GCP VM")
            return False

        instance_client = compute_v1.InstancesClient()

        # Delete the instance (this is a long-running operation)
        operation = instance_client.delete(
            project=project_id,
            zone=zone,
            instance=instance_name
        )
        operation.result()  # Wait for completion

        print(f"Successfully deleted GCP instance {instance_name}")
        return True
    except Exception as e:
        print(f"Error deleting GCP instance {vm.get('id')}: {e}")
        return False


def add_tag(vm: dict[str, any], tag_name: str, tag_value: str) -> bool:
    """
    Add a label to a GCP VM instance.

    Args:
        vm (dict[str, any]): VM dictionary with instance details.
            Required attributes:
            - id (str): GCP instance name
            - account_id (str): GCP project ID
            - zone (str): GCP zone (or region as fallback)
        tag_name (str): Label key/name (will be converted to lowercase)
        tag_value (str): Label value

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        instance_name = vm.get('id')  # In GCP, 'id' is the instance name
        project_id = vm.get('account_id')
        zone = vm.get('zone', vm.get('region'))

        if not all([instance_name, project_id, zone]):
            print(f"Error: Missing required information for GCP VM")
            return False

        instance_client = compute_v1.InstancesClient()

        # Get current instance
        instance = instance_client.get(
            project=project_id,
            zone=zone,
            instance=instance_name
        )

        # Get current labels and add new one
        # GCP labels must be lowercase and can only contain lowercase letters, numbers, hyphens, and underscores
        current_labels = dict(instance.labels.items()
                              ) if instance.labels else {}
        # Convert tag name to lowercase and normalize tag value
        label_name = tag_name.lower()
        label_value = tag_value.lower().replace('.', '-')
        current_labels[label_name] = label_value

        # Update labels
        request = compute_v1.SetLabelsInstanceRequest(
            project=project_id,
            zone=zone,
            instance=instance_name,
            instances_set_labels_request_resource=compute_v1.InstancesSetLabelsRequest(
                labels=current_labels,
                label_fingerprint=instance.label_fingerprint
            )
        )

        operation = instance_client.set_labels(request=request)
        operation.result()

        print(
            f"Successfully added {label_name} label to GCP instance {instance_name}")
        return True
    except Exception as e:
        print(f"Error adding label to GCP instance {vm.get('id')}: {e}")
        return False


def set_protection(vm: dict[str, any], value: bool) -> bool:
    """
    Enable or disable protection for a GCP VM instance.
    Note: GCP uses "deletionProtection" attribute on instances.

    Args:
        vm (dict[str, any]): VM dictionary with instance details.
        value (bool): True to enable protection, False to disable

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        instance_name = vm.get('id')  # In GCP, 'id' is the instance name
        project_id = vm.get('account_id')
        zone = vm.get('zone', vm.get('region'))

        if not all([instance_name, project_id, zone]):
            print(f"Error: Missing required information for GCP VM")
            return False

        instance_client = compute_v1.InstancesClient()

        # Set deletion protection
        operation = instance_client.set_deletion_protection(
            project=project_id,
            zone=zone,
            resource=instance_name,
            deletion_protection=value
        )
        operation.result()  # Wait for completion

        status = "enabled" if value else "disabled"
        print(
            f"Successfully {status} deletion protection for GCP instance {instance_name}")
        return True
    except Exception as e:
        print(
            f"Error setting deletion protection for GCP instance {vm.get('id')}: {e}")
        return False


def discover() -> list[dict]:
    """
    Discover VMs across all configured GCP projects in parallel.
    Uses aggregated list API to get all VMs across all zones per project in one call.

    Returns:
        list[dict]: List of all VM info
    """
    tasks = build_discovery_tasks(get_vms, "VM")
    return execute_discovery_tasks(tasks, max_workers=20)
