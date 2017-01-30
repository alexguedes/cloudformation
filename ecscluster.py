from troposphere import Template, Parameter, Ref, Join, Base64
from troposphere.ecs import Cluster
from troposphere.ec2 import SecurityGroup, SecurityGroupIngress
from troposphere.logs import LogGroup
from troposphere.iam import Role, InstanceProfile, Policy
from troposphere.autoscaling import AutoScalingGroup, LaunchConfiguration
import troposphere.elasticloadbalancingv2 as elb

template = Template()
template.add_version('2010-09-09')

# Param: VPC ID
vpc_id_param = template.add_parameter(Parameter(
    'VpcId',
    Description='VPC ID for ECS Cluster',
    Type='AWS::EC2::VPC::Id',
))

# Param: Subnet ID
subnet_id_param = template.add_parameter(Parameter(
    'SubnetId',
    Description='Select the subnets to be used by the cluster',
    Type='List<AWS::EC2::Subnet::Id>'
))

# Param: KeyName
keyname_param = template.add_parameter(Parameter(
    'KeyName',
    Description='Name of existing key pair for SSH access',
    Type='AWS::EC2::KeyPair::KeyName'
))

# Params: Auto Scaling Min, Max and Desired sizes
minsize_param = template.add_parameter(Parameter(
    'MinSize',
    Description='Minimum size of Auto Scaling group (at least one per AZ recommended)',
    Type='Number'
))

maxsize_param = template.add_parameter(Parameter(
    'MaxSize',
    Description='Maximum size of Auto Scaling group',
    Type='Number'
))

desired_param = template.add_parameter(Parameter(
    'DesiredCapacity',
    Description='Desired capacity of Auto Scaling group',
    Type='Number'
))

# Resource -> ECS -> Cluster -> Description: ECSCluster
EcsCluster = template.add_resource(Cluster(
    'ECSCluster',
))

# Resource -> Security Group -> Description: EcsSecurityGroup
EcsSecurityGroup = template.add_resource(SecurityGroup(
    'EcsSecurityGroup',
    GroupDescription='ECS Security Group',
    VpcId=Ref(vpc_id_param)
))

# Resource -> Security Group -> Description: ElbSecurityGroup
ElbSecurityGroup = template.add_resource(SecurityGroup(
    'ElbSecurityGroup',
    GroupDescription='ELB Security Group',
    VpcId=Ref(vpc_id_param)
))

# Resource -> Security Group Ingress -> Description: ElbSecurityGroupInbound80
ElbSecurityGroupInbound80 = template.add_resource(SecurityGroupIngress(
    'ElbSecurityGroupInbound80',
    GroupId=Ref(ElbSecurityGroup),
    IpProtocol='tcp',
    FromPort=80,
    ToPort=80,
    CidrIp='0.0.0.0/0'

))

# Resource -> Security Group Ingress -> Description: EcsSecurityGroupInboundElb
EcsSecurityGroupInboundElb = template.add_resource(SecurityGroupIngress(
    'EcsSecurityGroupInboundElb',
    GroupId=Ref(EcsSecurityGroup),
    IpProtocol='tcp',
    FromPort=80,
    ToPort=80,
    SourceSecurityGroupId=Ref(ElbSecurityGroup)
))

# Resource -> Cloudwatch Logs -> Description: EcsLogGroup
EcsLogGroup = template.add_resource(LogGroup(
    'EcsLogGroup',
    LogGroupName=Join('', ['EcsLogGroup-', Ref("AWS::StackName")]),
    RetentionInDays=14
))

# Resource -> Application Load Balancer -> LoadBalancer -> Description: EcsLoadBalancer
EcsLoadBalancer = template.add_resource(elb.LoadBalancer(
    'EcsLoadBalancer',
    Name='EcsLoadBalancer',
    Scheme='internet-facing',
    LoadBalancerAttributes=[elb.LoadBalancerAttributes(
        Key='idle_timeout.timeout_seconds',
        Value='30'
    )],
    Subnets=Ref(subnet_id_param),
    SecurityGroups=[Ref(ElbSecurityGroup)]
))

# Resource -> Application Load Balancer -> TargetGroup -> Description: EcsLoadBalancerTargetGroup
EcsLoadBalancerTargetGroup = template.add_resource(elb.TargetGroup(
    'EcsLoadBalancerTargetGroup',
    Name="EcsLoadBalancerTargetGroup",
    DependsOn="EcsLoadBalancer",
    HealthCheckIntervalSeconds=10,
    HealthCheckPath='/',
    HealthCheckProtocol='HTTP',
    HealthCheckTimeoutSeconds=5,
    HealthyThresholdCount=2,
    UnhealthyThresholdCount=2,
    Port=80,
    Protocol="HTTP",
    VpcId=Ref(vpc_id_param)
))

# Resource -> Application Load Balancer -> Listener -> Description: EcsLoadBalancerListener
EcsLoadBalancerListener = template.add_resource(elb.Listener(
    'EcsLoadBalancerListener',
    Port=80,
    Protocol='HTTP',
    LoadBalancerArn=Ref(EcsLoadBalancer),
    DefaultActions=[elb.Action(
        Type='forward',
        TargetGroupArn=Ref(EcsLoadBalancerTargetGroup)
    )]
))

"""
# Resource -> Application Load Balancer -> ListenerRule -> Description: EcsLoadBalancerListenerRule
EcsLoadBalancerListenerRule = template.add_resource(elb.ListenerRule(
    DependsOn='EcsLoadBalancerListener',
    Actions=[elb.Action(
        Type='forward',
        TargetGroupArn=Ref(EcsLoadBalancerTargetGroup)
    )],
    Conditions=[elb.Condition(
        Field='path-pattern',
        Values=['/']
    )],
    ListenerArn='EcsLoadBalancerListener',
    Priority=1
))
"""

# Resource -> IAM -> Role -> Description: EcsEcs2Role
EcsEc2Role = template.add_resource(Role(
    'EcsEc2Role',
    AssumeRolePolicyDocument={'Statement': [{'Action': 'sts:AssumeRole',
                                             'Principal': {"Service": ["ec2.amazonaws.com"]},
                                             'Effect': 'Allow'
                                             }]
                              },
    Path='/',
    Policies=[Policy(
        PolicyName='EcsPolicy',
        PolicyDocument={'Statement': [{'Action': ['ecs:CreateCluster',
                                                  'ecs:DeregisterContainerInstance',
                                                  'ecs:DiscoverPollEndpoint',
                                                  'ecs:Poll',
                                                  'ecs:RegisterContainerInstance',
                                                  'ecs:StartTelemetrySession',
                                                  'ecs:Submit*',
                                                  'logs:CreateLogStream',
                                                  'logs:PutLogEvents'],
                                       'Resource': '*',
                                       'Effect': 'Allow'
                                       }]
                        }
    )]
))

# Resource -> IAM -> InstanceProfile -> Description: EcsEc2InstanceProfile
EcsEc2InstanceProfile = template.add_resource(InstanceProfile(
    'EcsEc2InstanceProfile',
    Path='/',
    Roles=[Ref(EcsEc2Role)]
))

# Resource -> Auto Scaling -> LaunchConfiguration -> Description: EcsAutoScalingLaunchConfig
EcsAutoScalingLaunchConfig = template.add_resource(LaunchConfiguration(
    'EcsAutoScalingLaunchConfig',
    ImageId='ami-328a8056',  # CoreOS stable 1235.6.0 (HVM)
    SecurityGroups=[Ref(EcsSecurityGroup)],
    InstanceType='t2.micro',
    IamInstanceProfile=Ref(EcsEc2InstanceProfile),  # Create IAM Instance Profile
    KeyName=Ref(keyname_param),
    UserData=Base64(Join('',
                         [
                             '#cloud-config\n\n',
                             'coreos:\n',
                             ' units:\n',
                             '   - name: amazon-ecs-agent.service\n',
                             '     command: start\n',
                             '     runtime: true\n',
                             '     content: |\n',
                             '       [Unit]\n',
                             '       Description=AWS ECS Agent\n',
                             '       Documentation=https://docs.aws.amazon.com/AmazonECS/latest/developerguide/\n',
                             '       Requires=docker.socket\n',
                             '       After=docker.socket\n\n',
                             '       [Service]\n',
                             '       Environment=ECS_CLUSTER=',
                                     Ref(EcsCluster),
                                     '\n',
                             '       Environment=ECS_LOGLEVEL=info\n',
                             '       Environment=ECS_VERSION=latest\n',
                             '       Restart=on-failure\n',
                             '       RestartSec=30\n',
                             '       RestartPreventExitStatus=5\n',
                             '       SyslogIdentifier=ecs-agent\n',
                             '       ExecStartPre=-/bin/mkdir -p /var/log/ecs /var/ecs-data /etc/ecs\n',
                             '       ExecStartPre=-/usr/bin/touch /etc/ecs/ecs.config\n',
                             '       ExecStartPre=-/usr/bin/docker kill ecs-agent\n',
                             '       ExecStartPre=-/usr/bin/docker rm ecs-agent\n',
                             '       ExecStartPre=/usr/bin/docker pull amazon/amazon-ecs-agent:${ECS_VERSION}\n',
                             '       ExecStart=/usr/bin/docker run --name ecs-agent ',
                                                                  '--env-file=/etc/ecs/ecs.config ',
                                                                  '--volume=/var/run/docker.sock:/var/run/docker.sock ',
                                                                  '--volume=/var/log/ecs:/log ',
                                                                  '--volume=/var/ecs-data:/data ',
                                                                  '--volume=/sys/fs/cgroup:/sys/fs/cgroup:ro ',
                                                                  '--volume=/run/docker/execdriver/native:/var/lib/docker/execdriver/native:ro ',
                                                                  '--publish=127.0.0.1:51678:51678 ',
                                                                  '--env=ECS_LOGFILE=/log/ecs-agent.log ',
                                                                  '--env=ECS_LOGLEVEL=info ',
                                                                  '--env=ECS_DATADIR=/data ',
                                                                  '--env=ECS_CLUSTER=${ECS_CLUSTER} ',
                                                                  '--env=ECS_AVAILABLE_LOGGING_DRIVERS=[\"json-file\",\"awslogs\"] ',
                                                                  'amazon/amazon-ecs-agent:latest\n\n',
                             '   - name: docker-cleanup.service\n',
                             '     content: |\n',
                             '       [Unit]\n',
                             '       Description=Docker images cleanup\n',
                             '       [Service]\n',
                             '       Type=oneshot\n',
                             '       ExecStart=-/usr/bin/sh -c "docker images -q | xargs --no-run-if-empty docker rmi"\n\n',
                             '   - name: docker-cleanup.timer\n',
                             '     command: start\n',
                             '     content: |\n',
                             '       [Unit]\n',
                             '       Description=Run Docker cleanup daily\n\n',
                             '       [Timer]\n',
                             '       OnCalendar=daily\n',
                             '       Persistent=true\n'
                         ]))

))


# Resource -> Auto Scaling -> AutoScalingGroup -> Description: EcsAutoScalingGroup
EcsAutoScalingGroup = template.add_resource(AutoScalingGroup(
    "EcsAutoScalingGroup",
    VPCZoneIdentifier=Ref(subnet_id_param),
    LaunchConfigurationName=Ref(EcsAutoScalingLaunchConfig),
    MinSize=Ref(minsize_param),
    MaxSize=Ref(maxsize_param),
    DesiredCapacity=Ref(desired_param)
))

print(template.to_json())