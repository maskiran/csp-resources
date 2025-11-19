"""AWS-specific utility functions for VM management."""

from . import session
from .session import build_discovery_tasks, create_client
from utils import execute_discovery_tasks, normalize_tags


def get_vms(profile: str, region: str) -> list[dict]:
    """Get all EC2 instances in a specific AWS region."""
    vms = []

    try:
        ec2_client = create_client('ec2', profile, region)

        # Get account info
        account_id = session.get_account_id(profile, region)
        account_name = profile  # Use profile as account name

        # Get instances
        paginator = ec2_client.get_paginator('describe_instances')
        page_iterator = paginator.paginate()

        for page in page_iterator:
            for reservation in page['Reservations']:
                for instance in reservation['Instances']:
                    # Extract and normalize tags
                    tags = normalize_tags(instance.get('Tags'))

                    # Get instance name (prefer Name tag, fall back to instance ID)
                    name = tags.get('name', instance['InstanceId'])

                    # Get AMI name
                    ami_id = instance.get('ImageId', 'unknown')
                    ami_name = ami_id  # Default to AMI ID
                    try:
                        ami_response = ec2_client.describe_images(
                            ImageIds=[ami_id])
                        if ami_response['Images']:
                            ami_name = ami_response['Images'][0].get(
                                'Name', ami_id)
                    except Exception:
                        pass  # Keep AMI ID if can't resolve name

                    # Convert launch time to YYYY-MM-DDTHH:MM:SS format
                    launch_time = instance.get('LaunchTime')
                    if launch_time:
                        launch_time = launch_time.strftime('%Y-%m-%dT%H:%M:%S')

                    # Get availability zone from placement
                    zone = instance.get('Placement', {}).get(
                        'AvailabilityZone', '')

                    vm_info = {
                        'account_id': account_id,
                        'account_name': account_name,
                        'cloud': 'aws',
                        'id': instance['InstanceId'],
                        'state': instance['State']['Name'],
                        'image_name': ami_name,
                        'name': name,
                        'profile': profile,
                        'launch_time': launch_time,
                        'region': region,
                        'zone': zone,
                        'vpc_id': instance.get('VpcId', ''),
                        'subnet_id': instance.get('SubnetId', ''),
                        'tags': tags
                    }

                    vms.append(vm_info)

    except Exception as e:
        print(f"Error getting VMs in AWS {profile} {region}: {e}")

    return vms


def delete(vm: dict[str, any]) -> bool:
    """
    Delete an AWS EC2 instance.

    Args:
        vm (dict[str, any]): VM dictionary with instance details.
            Required attributes:
            - id (str): AWS EC2 instance ID
            - region (str): AWS region
            - profile (str): AWS profile name for authentication

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        instance_id = vm.get('id')
        region = vm.get('region')
        profile = vm.get('profile')

        if not all([instance_id, region, profile]):
            print(f"Error: Missing required information for AWS VM")
            return False

        ec2 = create_client('ec2', profile, region)

        ec2.terminate_instances(InstanceIds=[instance_id])
        print(f"Successfully initiated deletion of AWS instance {instance_id}")
        return True
    except Exception as e:
        print(f"Error deleting AWS instance {vm.get('id')}: {e}")
        return False


def add_tag(vm: dict[str, any], tag_name: str, tag_value: str) -> bool:
    """
    Add a tag to an AWS EC2 instance.

    Args:
        vm (dict[str, any]): VM dictionary with instance details.
            Required attributes:
            - id (str): AWS EC2 instance ID
            - region (str): AWS region
            - profile (str): AWS profile name for authentication
        tag_name (str): Tag key/name
        tag_value (str): Tag value

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        instance_id = vm.get('id')
        region = vm.get('region')
        profile = vm.get('profile')

        if not all([instance_id, region, profile]):
            print(f"Error: Missing required information for AWS VM")
            return False

        ec2 = create_client('ec2', profile, region)

        ec2.create_tags(
            Resources=[instance_id],
            Tags=[
                {
                    'Key': tag_name,
                    'Value': tag_value
                }
            ]
        )
        print(
            f"Successfully added {tag_name} tag to AWS instance {instance_id}")
        return True
    except Exception as e:
        print(f"Error adding tag to AWS instance {vm.get('id')}: {e}")
        return False


def set_protection(vm: dict[str, any], value: bool) -> bool:
    """
    Enable or disable API termination and stop protection for an AWS EC2 instance.

    Args:
        vm (dict[str, any]): VM dictionary with instance details.
            Required attributes:
            - id (str): AWS EC2 instance ID
            - region (str): AWS region
            - profile (str): AWS profile name for authentication
        value (bool): True to enable protection, False to disable

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        instance_id = vm.get('id')
        region = vm.get('region')
        profile = vm.get('profile')

        if not all([instance_id, region, profile]):
            print(f"Error: Missing required information for AWS VM")
            return False

        ec2 = create_client('ec2', profile, region)

        # Set termination protection
        ec2.modify_instance_attribute(
            InstanceId=instance_id,
            DisableApiTermination={'Value': value}
        )

        # Set stop protection
        ec2.modify_instance_attribute(
            InstanceId=instance_id,
            DisableApiStop={'Value': value}
        )

        status = "enabled" if value else "disabled"
        print(
            f"Successfully {status} API termination and stop protection for AWS instance {instance_id}")
        return True
    except Exception as e:
        print(
            f"Error setting termination/stop protection for AWS instance {vm.get('id')}: {e}")
        return False


def discover() -> list[dict]:
    """
    Discover VMs across all configured AWS profiles and regions in parallel.

    Returns:
        list[dict]: List of all VM info
    """
    tasks = build_discovery_tasks(get_vms, "VM")
    return execute_discovery_tasks(tasks, max_workers=20)
