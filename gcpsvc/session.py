"""GCP-specific authentication and service creation functions."""

from collections.abc import Callable
from typing import Any

import config
from google.cloud import compute_v1


def create_compute_client():
    """
    Create GCP Compute client.

    Returns:
        compute_v1.InstancesClient: GCP compute client
    """
    return compute_v1.InstancesClient()


def create_networks_client():
    """
    Create GCP Networks client.

    Returns:
        compute_v1.NetworksClient: GCP networks client
    """
    return compute_v1.NetworksClient()


def create_zones_client():
    """
    Create GCP Zones client.

    Returns:
        compute_v1.ZonesClient: GCP zones client
    """
    return compute_v1.ZonesClient()


def create_regions_client():
    """
    Create GCP Regions client.

    Returns:
        compute_v1.RegionsClient: GCP regions client
    """
    return compute_v1.RegionsClient()


def get_zones(project_id: str) -> list[str]:
    """
    Get all available GCP zones for a project.

    Args:
        project_id (str): GCP project ID

    Returns:
        list[str]: List of GCP zone names
    """
    zones_client = create_zones_client()
    zones = zones_client.list(project=project_id)
    return [zone.name for zone in zones]


def get_projects() -> list[str]:
    """Get all GCP projects from config."""
    return config.get_gcp_projects()


def build_discovery_tasks(get_resource_func: Callable, resource_name: str) -> list[dict[str, Any]]:
    """
    Build discovery tasks for GCP resources across all projects.

    Args:
        get_resource_func: Function to call for each project
        resource_name: Human-readable name of the resource (for logging)

    Returns:
        list[dict]: List of tasks with 'func', 'args', and 'context'
    """
    tasks = []

    try:
        projects = get_projects()
        if not projects:
            return tasks

        for project_id in projects:
            tasks.append({
                'func': get_resource_func,
                'args': (project_id,),
                'context': {
                    'cloud': 'gcp',
                    'location': project_id,
                    'resource': resource_name
                }
            })
    except Exception as e:
        print(f"Error in GCP discovery task building: {e}")

    return tasks
