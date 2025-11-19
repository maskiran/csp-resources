"""Azure-specific authentication and service creation functions."""

from collections.abc import Callable
from typing import Any

import config
from azure.identity import AzureCliCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.resource import ResourceManagementClient


def create_compute_client(subscription_id: str):
    """
    Create Azure Compute Management client.

    Args:
        subscription_id (str): Azure subscription ID

    Returns:
        ComputeManagementClient: Azure compute client
    """
    credential = AzureCliCredential()
    return ComputeManagementClient(credential, subscription_id)


def create_network_client(subscription_id: str):
    """
    Create Azure Network Management client.

    Args:
        subscription_id (str): Azure subscription ID

    Returns:
        NetworkManagementClient: Azure network client
    """
    credential = AzureCliCredential()
    return NetworkManagementClient(credential, subscription_id)


def create_resource_client(subscription_id: str):
    """
    Create Azure Resource Management client.

    Args:
        subscription_id (str): Azure subscription ID

    Returns:
        ResourceManagementClient: Azure resource client
    """
    credential = AzureCliCredential()
    return ResourceManagementClient(credential, subscription_id)


def get_subscriptions() -> list[str]:
    """Get all Azure subscriptions from config."""
    return config.get_azure_subs()


def build_discovery_tasks(get_resource_func: Callable, resource_name: str) -> list[dict[str, Any]]:
    """
    Build discovery tasks for Azure resources across all subscriptions.

    Args:
        get_resource_func: Function to call for each subscription
        resource_name: Human-readable name of the resource (for logging)

    Returns:
        list[dict]: List of tasks with 'func', 'args', and 'context'
    """
    tasks = []

    try:
        subscriptions = get_subscriptions()
        if not subscriptions:
            return tasks

        for subscription_id in subscriptions:
            tasks.append({
                'func': get_resource_func,
                'args': (subscription_id,),
                'context': {
                    'cloud': 'azure',
                    'location': subscription_id,
                    'resource': resource_name
                }
            })
    except Exception as e:
        print(f"Error in Azure discovery task building: {e}")

    return tasks
