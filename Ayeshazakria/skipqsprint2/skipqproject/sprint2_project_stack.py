from aws_cdk import (
    core as cdk,
    aws_lambda as _lambda,
    aws_events as events_,
    aws_events_targets as targets_,
    aws_iam,
    aws_cloudwatch as cloudwatch_,
    aws_sns as sns,
    aws_sns_subscriptions as subscriptions_,
    aws_cloudwatch_actions as actions_,
    aws_s3 as s3_,
    aws_dynamodb as db,
    aws_codedeploy as codedeploy
)
import boto3

dynamodb_client = boto3.client('dynamodb')
from uploadtobucket import upload_file, get_file
import constant as constants

class SprintTwoProjectStack(cdk.Stack):

    def __init__(self, scope: cdk.Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        lambda_role=self.create_lambda_role()
        # The code that defines your stack goes here
        HWlambda=self.create_lambda('WebHealthLambda', './resources','webhealthlambda.lambda_handler' ,lambda_role)
        
        db_lambda_role = self.create_db_lambda_role()
        dynamodb_lambda=self.create_lambda('Dynamolambda', './resources','dynamo_lambda.lambda_handler' ,db_lambda_role)
 
        #Creating an event after every one minute
        lambda_schedule= events_.Schedule.rate(cdk.Duration.minutes(1))
        #Setting target to our New WH lambda for the event##
        lambda_target= targets_.LambdaFunction(handler=HWlambda)
        #defining rule for lambda function invokation event
        rule=events_.Rule(self, "WebHealth_Invokation",
            description="Periodic Lambda",enabled=True,
            schedule= lambda_schedule,
            targets=[lambda_target])
            
            
        #create table in dynamo db
        try:
            dynamo_db = self.create_table("DynamoTable")
        except dynamodb_client.exceptions.ResourceInUseException:
            print("Table Already Exists")
        
        dynamo_db.grant_full_access(dynamodb_lambda)
        
        ###defining SNS service    
        topic = sns.Topic(self,"WebHealthTopic")
        topic.add_subscription(subscriptions_.EmailSubscription(email_address="ayesha.zakria.s@skipq.org"))
        topic.add_subscription(subscriptions_.LambdaSubscription(fn=dynamodb_lambda))

        urls = get_file("ayeshaskipqbucket","url_list.txt")
        self.create_alarm(topic,urls)
        
        ############Creating Alarm on aws metrics for lambda duration ###########
        metricduration= cloudwatch_.Metric(namespace='AWS/Lambda', metric_name='Duration',
            dimensions_map={'FunctionName': dynamodb_lambda.function_name}  )
        
        failure_alarm =cloudwatch_.Alarm(self, 'FailureAlarm', metric=metricduration,
            threshold=4000,
            comparison_operator= cloudwatch_.ComparisonOperator.GREATER_THAN_THRESHOLD,
            evaluation_periods=1) 
                
        ##Defining alias for my url health lambda    
        try:
            db_alias=_lambda.Alias(self, "AyeshaAlias",
            alias_name="AyeshaWhAlias",
            version=HWlambda.current_version)
        #### Defining code deployment group to auto roll back, on the basis of
        ####  aws lambda function's Alarm on metrics(Duration).               ########### 
            codedeploy.LambdaDeploymentGroup(self, "id",alias=db_alias,
            alarms=[failure_alarm])
        except: pass


    def create_lambda_role(self):
        lambdaRole=aws_iam.Role(self,"lambda-role",
        assumed_by=aws_iam.ServicePrincipal('lambda.amazonaws.com'),
        managed_policies=[
                aws_iam.ManagedPolicy.from_aws_managed_policy_name('service-role/AWSLambdaBasicExecutionRole'),
                aws_iam.ManagedPolicy.from_aws_managed_policy_name('CloudWatchFullAccess')
            ]) 
        return lambdaRole
    
    def create_db_lambda_role(self):
        lambdaRole = aws_iam.Role(self, "lambda-role-db",
                        assumed_by = aws_iam.ServicePrincipal('lambda.amazonaws.com'),
                        managed_policies=[
                            aws_iam.ManagedPolicy.from_aws_managed_policy_name('service-role/AWSLambdaBasicExecutionRole'),
                            aws_iam.ManagedPolicy.from_aws_managed_policy_name('AmazonDynamoDBFullAccess'),
                            aws_iam.ManagedPolicy.from_aws_managed_policy_name('AmazonSNSFullAccess'),
                        ])
            
        return lambdaRole
    
    
    
    def create_lambda(self,id,asset,handler, role):#
        return _lambda.Function(self, id,
        code=_lambda.Code.from_asset(asset),
        handler=handler,
        runtime=_lambda.Runtime.PYTHON_3_6,
        role=role
        )


    def create_table(self,id):
        dynamo_table = db.Table(
            self, 
            id,
            partition_key = db.Attribute(name="id", type=db.AttributeType.STRING),
            sort_key = db.Attribute(name="timestamp",type=db.AttributeType.STRING),
        )
        return dynamo_table
        

    def create_alarm(self, topic, urls):
        for url in urls:
            dimension= {'URL':  url}
            
            #create cloudwatch metric for availability 
            availability_metric=(cloudwatch_.Metric(namespace=constants.URL_MONITOR_NAMESPACE,metric_name=url+constants.URL_MONITOR_NAME1A,
            dimensions_map=dimension, period=cdk.Duration.minutes(1), label=url+'Avaiability_metric'))
            
            #setting an alarm for availability
            availability_alarm=( cloudwatch_.Alarm(self,
                id=url+'Availability_alarm', metric=availability_metric,
                comparison_operator= cloudwatch_.ComparisonOperator.LESS_THAN_THRESHOLD, 
                datapoints_to_alarm=1,
                evaluation_periods=1, 
                threshold= constants.THRESHOLD_AVAIL
                ))
                
            #create a metric class for latency
            latency_metric=(cloudwatch_.Metric(namespace= constants.URL_MONITOR_NAMESPACE, metric_name=url+constants.URL_MONITOR_NAME1L, 
                dimensions_map=dimension, period=cdk.Duration.minutes(1),label=url+'Latency_metric'))
            
            #create an alarm for latency
            latency_alarm=(cloudwatch_.Alarm(self,
                id=url+'Latency_alarm', metric=latency_metric,
                comparison_operator= cloudwatch_.ComparisonOperator.GREATER_THAN_THRESHOLD,
                datapoints_to_alarm=1,
                evaluation_periods=1,  
                threshold=constants.THRESHOLD_LATENCY
                ))
            
            #link sns and sns subscription to alarm
            availability_alarm.add_alarm_action(actions_.SnsAction(topic))
            latency_alarm.add_alarm_action(actions_.SnsAction(topic))