"""AWS-specific VPC utility functions."""

from .session import build_discovery_tasks, create_client
from utils import execute_discovery_tasks, load_from_json, normalize_tags, get_inventory_path


def get_resource_counts_from_inventory(profile: str, region: str, vpc_id: str) -> dict:
    """
    Get resource counts for a specific VPC from inventory files.

    Args:
        profile: AWS profile name
        region: AWS region
        vpc_id: VPC ID to get counts for

    Returns:
        dict with keys: vm_count
    """
    # Configuration mapping count keys to their resource types
    resource_configs = {
        'vm_count': 'vm'
    }

    # Common filters for all resources
    common_filters = {'cloud': 'aws', 'profile': profile,
                      'region': region, 'vpc_id': vpc_id}

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


def get_eni_counts(ec2_client, vpc_ids: list[str]) -> dict[str, int]:
    """Get network interface (ENI) counts per VPC."""
    eni_counts = {}
    try:
        # Paginate through network interfaces
        next_token = None
        while True:
            if next_token:
                response = ec2_client.describe_network_interfaces(
                    Filters=[{'Name': 'vpc-id', 'Values': vpc_ids}],
                    NextToken=next_token
                )
            else:
                response = ec2_client.describe_network_interfaces(
                    Filters=[{'Name': 'vpc-id', 'Values': vpc_ids}]
                )

            for eni in response['NetworkInterfaces']:
                vpc_id = eni['VpcId']
                eni_counts[vpc_id] = eni_counts.get(vpc_id, 0) + 1

            next_token = response.get('NextToken')
            if not next_token:
                break
    except Exception:
        pass
    return eni_counts


def get_vpcs(profile: str, region: str) -> list[dict]:
    """
    Get all VPCs in a specific AWS region.

    Args:
        profile (str): AWS profile name
        region (str): AWS region

    Returns:
        list[dict]: List of VPC info dictionaries
    """
    vpcs = []

    try:
        ec2_client = create_client('ec2', profile, region)

        # Paginate through VPCs
        all_vpcs = []
        next_token = None
        while True:
            if next_token:
                response = ec2_client.describe_vpcs(NextToken=next_token)
            else:
                response = ec2_client.describe_vpcs()

            all_vpcs.extend(response['Vpcs'])

            next_token = response.get('NextToken')
            if not next_token:
                break

        # Collect all VPC IDs first
        vpc_ids = [vpc['VpcId'] for vpc in all_vpcs]

        if not vpc_ids:
            return vpcs

        # Get counts from CSP
        eni_counts = get_eni_counts(ec2_client, vpc_ids)

        for vpc in all_vpcs:
            vpc_id = vpc['VpcId']

            # Get tags
            tags = {}
            raw_tags = vpc.get('Tags', [])
            if raw_tags:
                tags = normalize_tags(raw_tags)

            # Get VPC name from tags (normalized to lowercase), fallback to VPC ID
            vpc_name = tags.get('name', vpc_id)

            # Get resource counts from inventory files for this VPC
            inventory_counts = get_resource_counts_from_inventory(
                profile, region, vpc_id)

            # Get counts from CSP
            eni_count = eni_counts.get(vpc_id, 0)

            vpcs.append({
                'id': vpc_id,
                'name': vpc_name,
                'cidr_block': vpc['CidrBlock'],
                'state': vpc['State'],
                'is_default': vpc['IsDefault'],
                'eni_count': eni_count,
                'vm_count': inventory_counts['vm_count'],
                'region': region,
                'profile': profile,
                'cloud': 'aws',
                'tags': tags
            })

    except Exception as e:
        print(f"Error getting AWS VPCs in {region}: {e}")

    return vpcs


def delete_vpc_endpoints(ec2_client, vpc_id: str, vpc_name: str) -> None:
    """Delete all VPC endpoints in a VPC."""
    print(f"{vpc_name}: Deleting VPC endpoints...")
    try:
        # Paginate through VPC endpoints
        all_endpoints = []
        next_token = None
        while True:
            if next_token:
                endpoints_response = ec2_client.describe_vpc_endpoints(
                    Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}],
                    NextToken=next_token
                )
            else:
                endpoints_response = ec2_client.describe_vpc_endpoints(
                    Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
                )

            all_endpoints.extend(endpoints_response['VpcEndpoints'])

            next_token = endpoints_response.get('NextToken')
            if not next_token:
                break

        for endpoint in all_endpoints:
            endpoint_id = endpoint['VpcEndpointId']
            try:
                ec2_client.delete_vpc_endpoints(VpcEndpointIds=[endpoint_id])
                print(f"{vpc_name}: Deleted VPC endpoint {endpoint_id}")
            except Exception as e:
                print(
                    f"{vpc_name}: Warning: Failed to delete VPC endpoint {endpoint_id}: {e}")
    except Exception as e:
        print(f"{vpc_name}: Error listing VPC endpoints: {e}")


def delete_subnets(ec2_client, vpc_id: str, vpc_name: str) -> None:
    """Delete all subnets in a VPC."""
    print(f"{vpc_name}: Deleting subnets...")
    try:
        # Paginate through subnets
        all_subnets = []
        next_token = None
        while True:
            if next_token:
                subnets_response = ec2_client.describe_subnets(
                    Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}],
                    NextToken=next_token
                )
            else:
                subnets_response = ec2_client.describe_subnets(
                    Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
                )

            all_subnets.extend(subnets_response['Subnets'])

            next_token = subnets_response.get('NextToken')
            if not next_token:
                break

        for subnet in all_subnets:
            subnet_id = subnet['SubnetId']
            try:
                ec2_client.delete_subnet(SubnetId=subnet_id)
                print(f"{vpc_name}: Deleted subnet {subnet_id}")
            except Exception as e:
                print(
                    f"{vpc_name}: Warning: Failed to delete subnet {subnet_id}: {e}")
    except Exception as e:
        print(f"{vpc_name}: Error listing subnets: {e}")


def revoke_security_group_rules(ec2_client, vpc_id: str, vpc_name: str) -> None:
    """Revoke all ingress and egress rules from security groups in a VPC (including default)."""
    print(f"{vpc_name}: Revoking security group rules...")
    try:
        # Paginate through security groups
        all_security_groups = []
        next_token = None
        while True:
            if next_token:
                sg_response = ec2_client.describe_security_groups(
                    Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}],
                    NextToken=next_token
                )
            else:
                sg_response = ec2_client.describe_security_groups(
                    Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
                )

            all_security_groups.extend(sg_response['SecurityGroups'])

            next_token = sg_response.get('NextToken')
            if not next_token:
                break

        for sg in all_security_groups:
            sg_id = sg['GroupId']
            sg_name = sg['GroupName']

            # Revoke ingress rules (including from default security group)
            if sg.get('IpPermissions'):
                try:
                    ec2_client.revoke_security_group_ingress(
                        GroupId=sg_id,
                        IpPermissions=sg['IpPermissions']
                    )
                    print(
                        f"{vpc_name}: Revoked ingress rules from security group {sg_id} ({sg_name})")
                except Exception as e:
                    print(
                        f"{vpc_name}: Warning: Failed to revoke ingress rules from {sg_id}: {e}")

            # Revoke egress rules (including from default security group)
            if sg.get('IpPermissionsEgress'):
                try:
                    ec2_client.revoke_security_group_egress(
                        GroupId=sg_id,
                        IpPermissions=sg['IpPermissionsEgress']
                    )
                    print(
                        f"{vpc_name}: Revoked egress rules from security group {sg_id} ({sg_name})")
                except Exception as e:
                    print(
                        f"{vpc_name}: Warning: Failed to revoke egress rules from {sg_id}: {e}")
    except Exception as e:
        print(f"{vpc_name}: Error listing security groups: {e}")


def delete_security_groups(ec2_client, vpc_id: str, vpc_name: str) -> None:
    """Delete all security groups in a VPC (except default)."""
    print(f"{vpc_name}: Deleting security groups...")
    try:
        # Paginate through security groups
        all_security_groups = []
        next_token = None
        while True:
            if next_token:
                sg_response = ec2_client.describe_security_groups(
                    Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}],
                    NextToken=next_token
                )
            else:
                sg_response = ec2_client.describe_security_groups(
                    Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
                )

            all_security_groups.extend(sg_response['SecurityGroups'])

            next_token = sg_response.get('NextToken')
            if not next_token:
                break

        for sg in all_security_groups:
            # Skip default security group
            if sg['GroupName'] == 'default':
                continue
            sg_id = sg['GroupId']
            try:
                ec2_client.delete_security_group(GroupId=sg_id)
                print(f"{vpc_name}: Deleted security group {sg_id}")
            except Exception as e:
                print(
                    f"{vpc_name}: Warning: Failed to delete security group {sg_id}: {e}")
    except Exception as e:
        print(f"{vpc_name}: Error listing security groups: {e}")


def delete_route_tables(ec2_client, vpc_id: str, vpc_name: str) -> None:
    """Delete all route tables in a VPC (except main)."""
    print(f"{vpc_name}: Deleting route tables...")
    try:
        # Paginate through route tables
        all_route_tables = []
        next_token = None
        while True:
            if next_token:
                rt_response = ec2_client.describe_route_tables(
                    Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}],
                    NextToken=next_token
                )
            else:
                rt_response = ec2_client.describe_route_tables(
                    Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
                )

            all_route_tables.extend(rt_response['RouteTables'])

            next_token = rt_response.get('NextToken')
            if not next_token:
                break

        for rt in all_route_tables:
            # Skip main route table
            is_main = any(assoc.get('Main', False)
                          for assoc in rt.get('Associations', []))
            if is_main:
                continue
            rt_id = rt['RouteTableId']
            try:
                ec2_client.delete_route_table(RouteTableId=rt_id)
                print(f"{vpc_name}: Deleted route table {rt_id}")
            except Exception as e:
                print(
                    f"{vpc_name}: Warning: Failed to delete route table {rt_id}: {e}")
    except Exception as e:
        print(f"{vpc_name}: Error listing route tables: {e}")


def delete_internet_gateways(ec2_client, vpc_id: str, vpc_name: str) -> None:
    """Delete all internet gateways attached to a VPC."""
    print(f"{vpc_name}: Deleting internet gateways...")
    try:
        # Paginate through internet gateways
        all_internet_gateways = []
        next_token = None
        while True:
            if next_token:
                igw_response = ec2_client.describe_internet_gateways(
                    Filters=[{'Name': 'attachment.vpc-id', 'Values': [vpc_id]}],
                    NextToken=next_token
                )
            else:
                igw_response = ec2_client.describe_internet_gateways(
                    Filters=[{'Name': 'attachment.vpc-id', 'Values': [vpc_id]}]
                )

            all_internet_gateways.extend(igw_response['InternetGateways'])

            next_token = igw_response.get('NextToken')
            if not next_token:
                break

        for igw in all_internet_gateways:
            igw_id = igw['InternetGatewayId']
            try:
                # Detach from VPC first
                ec2_client.detach_internet_gateway(
                    InternetGatewayId=igw_id,
                    VpcId=vpc_id
                )
                print(f"{vpc_name}: Detached internet gateway {igw_id}")
                # Then delete
                ec2_client.delete_internet_gateway(InternetGatewayId=igw_id)
                print(f"{vpc_name}: Deleted internet gateway {igw_id}")
            except Exception as e:
                print(
                    f"{vpc_name}: Warning: Failed to delete internet gateway {igw_id}: {e}")
    except Exception as e:
        print(f"{vpc_name}: Error listing internet gateways: {e}")


def delete(vpc_info: dict) -> bool:
    """
    Delete an AWS VPC by first cleaning up all dependencies.

    Deletion sequence:
    1. Delete all VPC endpoints
    2. Delete all subnets
    3. Revoke all security group rules (removes cross-references)
    4. Delete all security groups (except default)
    5. Delete all route tables (except main)
    6. Delete all internet gateways
    7. Delete the VPC

    Args:
        vpc_info (dict): VPC info dictionary with required attributes:
            - id (str): VPC ID
            - region (str): AWS region
            - profile (str): AWS profile name
            - name (str): VPC name (for logging)

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        vpc_id = vpc_info.get('id')
        region = vpc_info.get('region')
        profile = vpc_info.get('profile')
        vpc_name = vpc_info.get('name', vpc_id)

        if not all([vpc_id, region, profile]):
            print(f"{vpc_name}: Error: Missing required information for AWS VPC")
            return False

        ec2_client = create_client('ec2', profile, region)

        # Execute cleanup sequence
        delete_vpc_endpoints(ec2_client, vpc_id, vpc_name)
        delete_subnets(ec2_client, vpc_id, vpc_name)
        revoke_security_group_rules(ec2_client, vpc_id, vpc_name)
        delete_security_groups(ec2_client, vpc_id, vpc_name)
        delete_route_tables(ec2_client, vpc_id, vpc_name)
        delete_internet_gateways(ec2_client, vpc_id, vpc_name)

        # Delete the VPC
        print(f"{vpc_name}: Deleting VPC...")
        ec2_client.delete_vpc(VpcId=vpc_id)
        print(f"{vpc_name}: Successfully deleted VPC {vpc_id}")
        return True

    except Exception as e:
        print(
            f"{vpc_info.get('name', vpc_info.get('id'))}: Error deleting AWS VPC: {e}")
        return False


def add_tag(vpc_info: dict, tag_name: str, tag_value: str) -> bool:
    """
    Add a tag to an AWS VPC.

    Args:
        vpc_info (dict): VPC info dictionary with required attributes:
            - id (str): VPC ID
            - region (str): AWS region
            - profile (str): AWS profile name
        tag_name (str): Tag key/name
        tag_value (str): Tag value

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        vpc_id = vpc_info.get('id')
        region = vpc_info.get('region')
        profile = vpc_info.get('profile')

        if not all([vpc_id, region, profile]):
            print(f"Error: Missing required information for AWS VPC tagging")
            return False

        ec2_client = create_client('ec2', profile, region)

        ec2_client.create_tags(
            Resources=[vpc_id],
            Tags=[
                {
                    'Key': tag_name,
                    'Value': tag_value
                }
            ]
        )
        print(f"Successfully added {tag_name} tag to AWS VPC {vpc_id}")
        return True
    except Exception as e:
        print(f"Error adding tag to AWS VPC {vpc_info.get('id')}: {e}")
        return False


def discover() -> list[dict]:
    """
    Discover VPCs across all configured AWS profiles and regions in parallel.

    Returns:
        list[dict]: List of all VPC info
    """
    tasks = build_discovery_tasks(get_vpcs, "VPC")
    return execute_discovery_tasks(tasks, max_workers=20)
