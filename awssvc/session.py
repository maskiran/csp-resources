"""AWS-specific authentication and service creation functions."""

from collections.abc import Callable

import boto3
from botocore.config import Config

import config


def create_session(profile: str, region: str = 'us-east-1'):
    """
    Create AWS session for a specific profile and region.

    Args:
        profile (str): AWS profile name
        region (str): AWS region (default: us-east-1)

    Returns:
        boto3.Session: AWS session object
    """
    return boto3.Session(profile_name=profile, region_name=region)


def create_client(service: str, profile: str, region: str = 'us-east-1'):
    """
    Create AWS client for a specific service, profile and region with enhanced retry configuration.

    Args:
        service (str): AWS service name (e.g., 'ec2', 'elbv2', 'vpc')
        profile (str): AWS profile name
        region (str): AWS region (default: us-east-1)

    Returns:
        boto3.client: AWS service client with retry configuration
    """
    # Enhanced retry configuration for all AWS services
    retry_config = Config(
        retries={
            'max_attempts': 10,
            'mode': 'adaptive'
        },
        connect_timeout=10,  # seconds to wait for connection
        read_timeout=60      # seconds to wait for response
    )

    session = create_session(profile, region)
    return session.client(service, config=retry_config)


def get_regions(profile: str = None) -> list[str]:
    """
    Get all available AWS regions.

    Args:
        profile (str): AWS profile name (uses first profile from config if None)

    Returns:
        list[str]: List of AWS region names
    """
    if not profile:
        profiles = config.get_aws_profiles()
        if not profiles:
            raise ValueError("No AWS profiles found in config")
        profile = profiles[0]

    ec2_client = create_client('ec2', profile)
    regions = ec2_client.describe_regions()['Regions']
    return [region['RegionName'] for region in regions]


def get_profiles() -> list[str]:
    """Get all AWS profiles from config."""
    return config.get_aws_profiles()


def get_account_id(profile: str, region: str = 'us-east-1') -> str:
    """
    Get AWS account ID for a specific profile.

    Args:
        profile: AWS profile name
        region: AWS region (default: us-east-1)

    Returns:
        str: AWS account ID
    """
    sts_client = create_client('sts', profile, region)
    account_info = sts_client.get_caller_identity()
    return account_info['Account']


def build_discovery_tasks(get_resource_func: Callable, resource_name: str) -> list[dict[str, any]]:
    """
    Build discovery tasks for AWS resources across all profiles and regions.

    Args:
        get_resource_func: Function to call for each profile-region combination
        resource_name: Human-readable name of the resource (for logging)

    Returns:
        list[dict]: List of tasks with 'func', 'args', and 'context'
    """
    tasks = []

    try:
        profiles = get_profiles()
        if not profiles:
            return tasks

        for profile in profiles:
            try:
                regions = get_regions(profile)
                for region in regions:
                    tasks.append({
                        'func': get_resource_func,
                        'args': (profile, region),
                        'context': {
                            'cloud': 'aws',
                            'location': f"{profile} {region}",
                            'resource': resource_name
                        }
                    })
            except Exception as e:
                print(f"AWS {profile}: Error getting regions - {e}")
    except Exception as e:
        print(f"Error in AWS discovery task building: {e}")

    return tasks
